"""
가전(MQTT)로부터 들어온 telemetry/ack 메시지를 실제 상태 변화로 해석하는 서비스입니다.

하는 일:
1) telemetry 수신 -> 최신 상태 저장 + WebSocket으로 실시간 전달(burner.telemetry)
2) deviceState가 overheated로/에서 전이될 때 안전 이벤트 발생
3) 화구가 켜지고 꺼지는 시점을 기준으로 "조리 세션" 시작/종료 관리
4) ack 수신 -> commands_service에 위임
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from app import commands_service, safety_service, state_store, ws_hub
from app.config import settings
from app.schemas import AckReport, BurnerTelemetry, SessionRecord, SessionTimelineEntry, TelemetryReport

logger = logging.getLogger("induction.device")


def _new_session_id() -> str:
    return f"session-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def handle_telemetry(device_id: str, report: TelemetryReport) -> None:
    previous = state_store.get_telemetry(device_id)
    state_store.save_telemetry(device_id, report)

    ws_hub.broadcast_threadsafe(
        "burner.telemetry",
        {
            "deviceId": device_id,
            "reportedAt": report.reportedAt,
            "burners": [b.model_dump() for b in report.burners],
        },
    )

    room = settings.KITCHEN_ROOM
    session_id = state_store.get_active_session_id(device_id)

    for burner in report.burners:
        previous_burner = None
        if previous is not None:
            previous_burner = next((b for b in previous.burners if b.burnerId == burner.burnerId), None)

        if previous_burner is not None and previous_burner.deviceState != burner.deviceState:
            ws_hub.broadcast_threadsafe(
                "burner.state_changed",
                {
                    "deviceId": device_id,
                    "burnerId": burner.burnerId,
                    "from": previous_burner.deviceState,
                    "to": burner.deviceState,
                },
            )

            became_overheated = burner.deviceState == "overheated"
            left_overheated = previous_burner.deviceState == "overheated" and not became_overheated
            if became_overheated or left_overheated:
                safety_service.handle_overheat_transition(
                    device_id, room, session_id, became_overheated, burner.temperature
                )

        # --- 조리 세션 시작/종료 판단 (화구 1개 기준) ---
        if burner.deviceState == "on" and session_id is None:
            session_id = _start_session(device_id, room, burner.temperature)
        elif burner.deviceState == "off" and session_id is not None:
            still_active = any(b.deviceState in ("on", "overheated", "cooling") for b in report.burners)
            if not still_active:
                _end_session(device_id, room, session_id)
                session_id = None

    if session_id is not None:
        _update_session_peak(session_id, report.burners)


def handle_ack(device_id: str, ack: AckReport) -> None:
    commands_service.on_ack_received(device_id, ack)


def _start_session(device_id: str, room: str, temperature: float) -> str:
    session_id = _new_session_id()
    record = SessionRecord(
        sessionId=session_id,
        startedAt=_now_iso(),
        endedAt=None,
        status="active",
        peakTemperature=temperature,
        timeline=[SessionTimelineEntry(at=_now_iso(), type="cooking_started", summary="화구 켜짐")],
    )
    state_store.save_session(record)
    state_store.set_active_session_id(device_id, session_id)
    safety_service.emit_event("cooking_started", "info", room, session_id=session_id, temperature=temperature)
    ws_hub.broadcast_threadsafe("session.updated", record.model_dump())
    return session_id


def _end_session(device_id: str, room: str, session_id: str) -> None:
    record = state_store.get_session(session_id)
    if record is None:
        state_store.set_active_session_id(device_id, None)
        return

    entry = SessionTimelineEntry(at=_now_iso(), type="cooking_ended", summary="화구 꺼짐")
    updated = record.model_copy(update={
        "endedAt": _now_iso(),
        "status": "ended",
        "timeline": [*record.timeline, entry],
    })
    state_store.save_session(updated)
    state_store.set_active_session_id(device_id, None)
    safety_service.emit_event("cooking_ended", "info", room, session_id=session_id)
    ws_hub.broadcast_threadsafe("session.updated", updated.model_dump())


def _update_session_peak(session_id: str, burners: Iterable[BurnerTelemetry]) -> None:
    record = state_store.get_session(session_id)
    if record is None:
        return
    max_temp = max((b.temperature for b in burners), default=record.peakTemperature)
    if max_temp > record.peakTemperature:
        state_store.save_session(record.model_copy(update={"peakTemperature": max_temp}))
