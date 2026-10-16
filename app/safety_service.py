"""
안전 이벤트 생성과 재실 판단 결과 저장을 담당하는 서비스입니다.

v0.3 변경: 백엔드가 직접 하던 부재중 자동 제어 판단(관찰 -> 화력 저감 -> 전원 차단)을 제거했습니다.
모든 제어 판단은 AI 중앙 판정 엔진이 하고, 그 결과는 POST /ai/decisions 로 들어옵니다 (app/ai_service.py).
POST /presence 는 이제 재실 판단 결과를 저장하고 대시보드로 전달하기만 합니다.
과열 감지 이벤트처럼 기기 보호를 위한 최소한의 안전 규칙은 그대로 유지합니다.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app import state_store, ws_hub
from app.config import settings
from app.schemas import PresenceReport, SafetyEvent

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
    decision_id: Optional[str] = None,
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
        decisionId=decision_id,
    )
    state_store.save_safety_event(event)
    ws_hub.broadcast_threadsafe("safety.event", event.model_dump())
    logger.info("안전 이벤트 발생: %s (%s)", event.type, event.eventId)
    return event


def compute_safety_phase(room: str, device_id: str) -> str:
    """대시보드 표시용 안전 단계. (v0.3: 부재중 자동 제어 단계는 제거되어 과열 여부만 판단)"""
    telemetry = state_store.get_telemetry(device_id)
    if telemetry is not None and any(b.deviceState == "overheated" for b in telemetry.burners):
        return "overheat"
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
# 재실 판단 결과 (저장 + 대시보드 전달만)
# ---------------------------------------------------------------------------

def evaluate_presence(report: PresenceReport) -> tuple[str, Optional[str]]:
    """재실 판단 결과를 저장하고 대시보드로 전달합니다. 가전 제어는 하지 않습니다. (v0.3)"""
    state_store.save_presence(report)
    ws_hub.broadcast_threadsafe("presence.updated", report.model_dump())
    return compute_safety_phase(report.room, settings.INDUCTION_DEVICE_ID), None
