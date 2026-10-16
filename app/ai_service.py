"""
AI 중앙 판정 엔진과 연동하는 서비스입니다. (v0.3)

역할 분담 (팀 결정):
- 판단: AI 중앙 판정 엔진이 위치·행동·신뢰도·기기 상태를 종합해 시나리오별로 판단합니다.
- 실행: 서버는 받은 판단(actions)대로 가전을 제어하고, 결과를 기록하고, 대시보드에 알립니다.

제공하는 것:
- get_device_states(): 판정 엔진이 판단에 쓰는 기기 상태 (device / is_on / current_state / control_state)
- handle_decision():   판정 결과를 받아 실행. 같은 decisionId가 다시 오면 다시 실행하지 않습니다.
- link_feedback():     사용자가 남긴 피드백을 판단 기록에 연결 (판정 엔진의 가중치 조정용)

시나리오별 처리:
- fall_detected  : 낙상 처리 흐름(인덕션 비상 차단 + 전등 깜빡임 -> 사용자 -> 보호자 -> 자동 신고)을 실행
- 그 외          : actions에 적힌 제어를 순서대로 실행 (bedtime_light_off, stove_absence, water_dispense 등)
- restore_power  : HomeVIS가 인덕션을 끄거나 낮추기 직전 화력으로 다시 켭니다.
- weatherBriefing: true면 미리 받아 둔 날씨로 안내를 만들어 대시보드(weather.briefing)와 응답(weather)에 담습니다.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from app import (
    commands_service,
    device_registry,
    fall_service,
    home_device_service,
    safety_service,
    state_store,
    weather_service,
    ws_hub,
)
from app.config import settings
from app.schemas import (
    AiAction,
    AiActionResult,
    AiDecisionRecord,
    AiDecisionRequest,
    BurnerCommandRequest,
    DeviceInfo,
    FallDetectedReport,
    HomeDeviceCommandRequest,
    LastControl,
    SafetyEvent,
)

logger = logging.getLogger("induction.ai")

FALL_SCENARIO = "fall_detected"
STOVE_ACTIONS = ("turn_on", "turn_off", "set_level", "restore_power")
# 낙상 처리 흐름이 직접 실행하는 제어 (판단 결과의 actions에 같이 와도 중복 실행하지 않음)
FALL_BUILTIN_ACTIONS = {("stove", "turn_off"), ("light", "blink")}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 기기 상태 (판정 엔진 입력용)
# ---------------------------------------------------------------------------

def _control_state(last_control: Optional[LastControl]) -> Optional[str]:
    """마지막으로 상태를 바꾼 주체: 서버(시스템/AI)가 보낸 명령이면 homevis, 그 외는 user"""
    if last_control is None:
        return None
    if last_control.commandId:
        record = state_store.get_command(last_control.commandId)
        if record is not None:
            return "homevis" if record.actor in ("system", "ai") else "user"
    return "homevis" if last_control.publisher == "system" else "user"


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="seconds") if value else None


def get_device_info(device: device_registry.Device) -> DeviceInfo:
    if device.type == device_registry.STOVE:
        telemetry = state_store.get_telemetry(device.deviceId)
        burner = telemetry.burners[0] if telemetry and telemetry.burners else None
        return DeviceInfo(
            device=device.type,
            deviceId=device.deviceId,
            room=device.room,
            online=state_store.is_online(device.deviceId),
            is_on=burner is not None and burner.deviceState == "on",
            current_state=(
                {"state": burner.deviceState, "level": burner.level, "temperature": burner.temperature}
                if burner
                else None
            ),
            control_state=_control_state(telemetry.lastControl) if telemetry else None,
            updatedAt=_iso(state_store.get_last_seen_at(device.deviceId)),
        )

    state = state_store.get_device_state(device.deviceId)
    last_control = None
    if state and state.get("lastControl"):
        last_control = LastControl.model_validate(state["lastControl"])
    if device.type == device_registry.LIGHT:
        is_on = bool(state) and state.get("power") == "on"
    else:
        is_on = bool(state) and state.get("status") == "dispensing"
    return DeviceInfo(
        device=device.type,
        deviceId=device.deviceId,
        room=device.room,
        online=state_store.is_device_online(device.deviceId),
        is_on=is_on,
        current_state={k: v for k, v in state.items() if k != "lastControl"} if state else None,
        control_state=_control_state(last_control),
        updatedAt=_iso(state_store.get_device_last_seen(device.deviceId)),
    )


def get_device_states() -> list[DeviceInfo]:
    return [get_device_info(d) for d in device_registry.list_devices()]


# ---------------------------------------------------------------------------
# 판단 결과 실행
# ---------------------------------------------------------------------------

def handle_decision(request: AiDecisionRequest) -> tuple[AiDecisionRecord, bool]:
    """(판단 기록, 중복 여부)를 돌려줍니다. 이미 받은 decisionId면 실행하지 않고 처음 기록을 돌려줍니다."""
    existing = state_store.get_ai_decision(request.decisionId)
    if existing is not None:
        logger.info("이미 처리한 AI 판단이라 다시 실행하지 않습니다 (decisionId=%s)", request.decisionId)
        return existing, True

    results: list[AiActionResult] = []
    fall_incident_id: Optional[str] = None

    if request.scenario == FALL_SCENARIO:
        incident = fall_service.report_fall(
            FallDetectedReport(
                room=request.room or settings.KITCHEN_ROOM,
                confidence=request.confidence,
                observedAt=request.timestamp,
                modelVersion=f"central-engine:{request.decisionId}",
            )
        )
        fall_incident_id = incident.incidentId
        results.append(
            AiActionResult(
                device="stove",
                deviceId=settings.INDUCTION_DEVICE_ID,
                action="turn_off",
                status="sent" if incident.shutoffSent else "failed",
                message="낙상 비상 차단",
            )
        )
        if incident.lightDeviceId is not None:
            results.append(
                AiActionResult(
                    device="light",
                    deviceId=incident.lightDeviceId,
                    action="blink",
                    status="sent" if incident.lightBlinkSent else "failed",
                    message="낙상 알림 깜빡임",
                )
            )

    for action in request.actions:
        if request.scenario == FALL_SCENARIO and (action.device, action.action) in FALL_BUILTIN_ACTIONS:
            continue  # 낙상 처리 흐름이 이미 실행한 제어라 두 번 보내지 않습니다.
        results.append(_execute(action, request))

    record = AiDecisionRecord(
        decisionId=request.decisionId,
        scenario=request.scenario,
        confidence=request.confidence,
        reason=request.reason,
        timestamp=request.timestamp,
        room=request.room,
        receivedAt=_now_iso(),
        weatherBriefing=request.weatherBriefing,
        actions=results,
        fallIncidentId=fall_incident_id,
    )

    if request.scenario != FALL_SCENARIO:
        event = _emit_decision_event(request, results)
        record = record.model_copy(update={"eventId": event.eventId})
    elif incident.eventId is not None:
        # 낙상은 낙상 처리 흐름이 만든 fall_detected 이벤트를 이 판단에 연결합니다.
        # (대시보드에서 그 이벤트에 피드백을 남기면 판단 기록에도 복사되도록)
        state_store.update_safety_event(incident.eventId, decisionId=request.decisionId)
        record = record.model_copy(update={"eventId": incident.eventId})

    if request.weatherBriefing:
        # 인터넷이 끊겨 있어도 응답이 늦어지지 않도록, 미리 받아 둔 날씨로만 안내합니다.
        briefing = weather_service.build_briefing()
        record = record.model_copy(update={"weather": briefing})
        ws_hub.broadcast_threadsafe(
            "weather.briefing", {"decisionId": request.decisionId, "room": request.room, **briefing.model_dump()}
        )

    state_store.save_ai_decision(record)
    ws_hub.broadcast_threadsafe("ai.decision", record.model_dump())
    return record, False


def _emit_decision_event(request: AiDecisionRequest, results: list[AiActionResult]) -> SafetyEvent:
    summary = ", ".join(f"{r.deviceId or r.device} {r.action} {r.status}" for r in results) or "실행할 제어 없음"
    has_problem = any(r.status != "sent" for r in results)
    return safety_service.emit_event(
        "ai_control",
        "warning" if has_problem else "info",
        request.room or settings.KITCHEN_ROOM,
        trigger=f"AI 판단 {request.scenario} (신뢰도 {request.confidence:.2f})",
        action=summary,
        reasoning=request.reason,
        decision_id=request.decisionId,
    )


def _result(action: AiAction, device_id: Optional[str], status: str, **extra) -> AiActionResult:
    return AiActionResult(device=action.device, deviceId=device_id, action=action.action, status=status, **extra)


def _execute(action: AiAction, request: AiDecisionRequest) -> AiActionResult:
    """제어 1건 실행. 실패해도 예외를 던지지 않고 결과(rejected/failed)로 돌려줍니다."""
    if action.deviceId is not None:
        device = device_registry.get_device(action.deviceId)
        if device is None or device.type != action.device:
            return _result(action, action.deviceId, "rejected", message="등록되지 않았거나 종류가 다른 기기입니다.")
    else:
        device = device_registry.find_device(action.device, request.room)
        if device is None:
            return _result(action, None, "rejected", message="해당 종류의 기기가 등록되어 있지 않습니다.")

    reason = f"ai:{request.scenario}"
    try:
        if device.type == device_registry.STOVE:
            record = _execute_stove(action, device.deviceId, reason, request.decisionId)
        else:
            try:
                command = HomeDeviceCommandRequest(
                    type=action.action, durationSec=action.durationSec, amountMl=action.amountMl
                )
            except ValidationError:
                return _result(action, device.deviceId, "rejected", message=f"{device.type}에 쓸 수 없는 동작입니다.")
            record = home_device_service.dispatch(
                device.deviceId, command, actor="ai", reason=reason, decision_id=request.decisionId
            )
    except commands_service.CommandRejected as exc:
        return _result(action, device.deviceId, "rejected", message="; ".join(exc.reasons))
    except Exception:
        logger.exception("AI 판단 제어 실행 실패 (decisionId=%s, device=%s)", request.decisionId, device.deviceId)
        return _result(action, device.deviceId, "failed", message="명령 전송 실패 (기기 통신 상태 확인 필요)")

    return _result(action, device.deviceId, "sent", commandId=record.commandId)


def _execute_stove(action: AiAction, device_id: str, reason: str, decision_id: str):
    if action.action not in STOVE_ACTIONS:
        raise commands_service.CommandRejected([f"인덕션에 쓸 수 없는 동작입니다: {action.action}"])

    burner_id = settings.BURNER_ID
    if action.action == "restore_power":
        level = state_store.get_restore_level(device_id)
        if level is None:
            raise commands_service.CommandRejected(["복구할 이전 화력이 없습니다. (HomeVIS가 끄거나 낮춘 기록 없음)"])
        record = commands_service.dispatch_command(
            device_id, burner_id, BurnerCommandRequest(type="turn_on", level=level),
            actor="ai", reason=reason, decision_id=decision_id,
        )
        state_store.set_restore_level(device_id, None)
        return record

    if action.action == "set_level" and action.level is None:
        raise commands_service.CommandRejected(["set_level에는 화력(level)이 필요합니다."])

    _remember_level_before_lowering(device_id, action)
    return commands_service.dispatch_command(
        device_id, burner_id, BurnerCommandRequest(type=action.action, level=action.level),
        actor="ai", reason=reason, decision_id=decision_id,
    )


def _remember_level_before_lowering(device_id: str, action: AiAction) -> None:
    """HomeVIS가 화구를 끄거나 낮추기 직전 화력을 저장합니다. 이미 저장된 값이 있으면 처음 값을 유지합니다."""
    telemetry = state_store.get_telemetry(device_id)
    burner = telemetry.burners[0] if telemetry and telemetry.burners else None
    if burner is None or burner.deviceState != "on" or burner.level <= 0:
        return
    lowering = action.action == "turn_off" or (action.action == "set_level" and (action.level or 0) < burner.level)
    if lowering and state_store.get_restore_level(device_id) is None:
        state_store.set_restore_level(device_id, burner.level)


# ---------------------------------------------------------------------------
# 피드백 연결
# ---------------------------------------------------------------------------

def link_feedback(event: SafetyEvent) -> None:
    """AI 판단으로 생긴 이벤트에 피드백이 달리면 판단 기록에도 복사합니다."""
    if event.decisionId and event.feedback is not None:
        state_store.update_ai_decision(event.decisionId, feedback=event.feedback)
