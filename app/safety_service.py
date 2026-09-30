"""
안전 이벤트 생성 + 부재중 자동 제어 정책(policies/kitchen-absence)을 담당하는 서비스입니다.

부재중 정책 요약 (GET/PUT /policies/kitchen-absence 값 기준):
- absentSec >= watchAfterSec  -> 관찰만 (absence_detected 이벤트, 조치 없음)
- absentSec >= reduceAfterSec -> 화력을 reduceToLevel로 자동 저감 (auto_power_reduced)
- absentSec >= offAfterSec    -> 전원 자동 차단 (auto_power_off)
- zone == "near"  -> 임계값에 nearZoneMultiplier를 곱해서 덜 민감하게 (더 오래 기다림)
- present == True -> 이전에 조치가 있었다면 user_returned 이벤트, 단계 초기화
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app import commands_service, state_store, ws_hub
from app.config import settings
from app.schemas import BurnerCommandRequest, PresenceReport, SafetyEvent

logger = logging.getLogger("induction.safety")


def _new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit_event(
    type_: str,
    severity: str,
    room: str,
    session_id: Optional[str] = None,
    temperature: Optional[float] = None,
    trigger: Optional[str] = None,
    action: Optional[str] = None,
    reasoning: Optional[str] = None,
) -> SafetyEvent:
    event = SafetyEvent(
        eventId=_new_event_id(),
        type=type_,
        severity=severity,
        occurredAt=_now_iso(),
        room=room,
        sessionId=session_id,
        temperature=temperature,
        trigger=trigger,
        action=action,
        reasoning=reasoning,
    )
    state_store.save_safety_event(event)
    ws_hub.broadcast_threadsafe("safety.event", event.model_dump())
    logger.info("안전 이벤트 발생: %s (%s)", event.type, event.eventId)
    return event


def compute_safety_phase(room: str, device_id: str) -> str:
    telemetry = state_store.get_telemetry(device_id)
    if telemetry is not None and any(b.deviceState == "overheated" for b in telemetry.burners):
        return "overheat"

    stage = state_store.get_absence_stage(room)
    if stage == "off":
        return "auto_off"
    if stage == "reduce":
        return "auto_reduced"
    if stage == "watch":
        return "absence_watch"
    return "normal"


# ---------------------------------------------------------------------------
# 과열 상태 전이 (device_service가 telemetry 처리 중 호출)
# ---------------------------------------------------------------------------

def handle_overheat_transition(
    device_id: str,
    room: str,
    session_id: Optional[str],
    became_overheated: bool,
    temperature: float,
) -> None:
    if became_overheated:
        emit_event(
            "overheat_detected",
            "danger",
            room,
            session_id=session_id,
            temperature=temperature,
            trigger=f"온도 {temperature:.1f}℃ >= 과열 임계값",
            action="화구 전원 잠금(turn_on/set_level 차단)",
            reasoning="화구 온도가 안전 임계값을 초과해 과열 상태로 전환됨",
        )
    else:
        emit_event(
            "overheat_cleared",
            "info",
            room,
            session_id=session_id,
            temperature=temperature,
            trigger=f"온도 {temperature:.1f}℃로 하강",
            action="과열 잠금 해제",
            reasoning="화구 온도가 안전 범위로 복귀함",
        )


def handle_command_blocked(room: str, session_id: Optional[str], reasons: list[str]) -> None:
    emit_event(
        "command_blocked",
        "warning",
        room,
        session_id=session_id,
        trigger="과열 상태에서 켜기/화력 상향 명령 수신",
        action="명령 거부",
        reasoning="; ".join(reasons),
    )


# ---------------------------------------------------------------------------
# 부재중 자동 제어 정책
# ---------------------------------------------------------------------------

def evaluate_presence(report: PresenceReport) -> tuple[str, Optional[str]]:
    state_store.save_presence(report)
    device_id = settings.INDUCTION_DEVICE_ID
    burner_id = settings.BURNER_ID
    policy = state_store.get_policy()
    triggered_event_id: Optional[str] = None

    if report.confidence < policy.minConfidence:
        # 신뢰도가 낮으면 기록만 하고 조치는 하지 않음
        ws_hub.broadcast_threadsafe("presence.updated", report.model_dump())
        return compute_safety_phase(report.room, device_id), None

    stage = state_store.get_absence_stage(report.room)

    if report.present:
        if stage is not None:
            event = emit_event(
                "user_returned",
                "info",
                report.room,
                trigger="재실 감지(present=true)",
                action="부재중 자동 조치 단계 초기화",
                reasoning=f"absentSec={report.absentSec}",
            )
            triggered_event_id = event.eventId
        state_store.set_absence_stage(report.room, None)
    else:
        multiplier = policy.nearZoneMultiplier if report.zone == "near" else 1.0
        watch_at = policy.watchAfterSec * multiplier
        reduce_at = policy.reduceAfterSec * multiplier
        off_at = policy.offAfterSec * multiplier

        if report.absentSec >= off_at and stage != "off":
            _dispatch_system_command(device_id, burner_id, BurnerCommandRequest(type="turn_off"))
            event = emit_event(
                "auto_power_off",
                "danger",
                report.room,
                trigger=f"부재 {report.absentSec}초 경과 (기준 {off_at:.0f}초)",
                action="화구 전원 자동 차단",
                reasoning="장시간 미복귀로 정책에 따라 자동 종료",
            )
            triggered_event_id = event.eventId
            state_store.set_absence_stage(report.room, "off")
        elif report.absentSec >= reduce_at and stage not in ("reduce", "off"):
            _dispatch_system_command(
                device_id, burner_id, BurnerCommandRequest(type="set_level", level=policy.reduceToLevel)
            )
            event = emit_event(
                "auto_power_reduced",
                "warning",
                report.room,
                trigger=f"부재 {report.absentSec}초 경과 (기준 {reduce_at:.0f}초)",
                action=f"화력을 {policy.reduceToLevel}단계로 자동 저감",
                reasoning="일정 시간 이탈이 지속되어 정책에 따라 화력을 낮춤",
            )
            triggered_event_id = event.eventId
            state_store.set_absence_stage(report.room, "reduce")
        elif report.absentSec >= watch_at and stage is None:
            event = emit_event(
                "absence_detected",
                "warning",
                report.room,
                trigger=f"부재 {report.absentSec}초 경과 (기준 {watch_at:.0f}초)",
                action="조치 없음 (관찰 시작)",
                reasoning="이탈이 감지되어 관찰 단계로 진입",
            )
            triggered_event_id = event.eventId
            state_store.set_absence_stage(report.room, "watch")

    ws_hub.broadcast_threadsafe("presence.updated", report.model_dump())
    return compute_safety_phase(report.room, device_id), triggered_event_id


def _dispatch_system_command(device_id: str, burner_id: str, request: BurnerCommandRequest) -> None:
    try:
        commands_service.dispatch_command(device_id, burner_id, request, actor="system", reason="kitchen-absence policy")
    except commands_service.CommandRejected as exc:
        # 과열 등으로 이미 잠겨있는 경우 등. 시스템 명령이라 그냥 로그만 남기고 넘어감.
        logger.info("부재중 자동 제어 명령이 거부됨: %s", exc.reasons)
