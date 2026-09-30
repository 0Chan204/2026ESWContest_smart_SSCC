"""
프론트(대시보드) 및 AI 재실 판단 모델이 호출하는 REST API입니다.

Swagger 문서를 인덕션 쪽과 분리하기 위해 별도 태그("dashboard")로 묶습니다.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from app import commands_service, safety_service, state_store
from app.config import settings
from app.schemas import (
    ApplianceSnapshot,
    BurnerCommandRequest,
    CommandAccepted,
    CommandRecord,
    KitchenAbsencePolicy,
    KitchenRoomSnapshot,
    PresenceAccepted,
    PresenceReport,
    SafetyEvent,
    SafetyEventFeedback,
    SafetyEventFeedbackResult,
    SafetyEventListResponse,
    SessionRecord,
    SnapshotResponse,
)

logger = logging.getLogger("induction.dashboard")

router = APIRouter(tags=["dashboard"])


# ---------------------------------------------------------------------------
# 재실 판단 (AI 모델 -> 서버)
# ---------------------------------------------------------------------------

@router.post("/presence", response_model=PresenceAccepted, status_code=status.HTTP_202_ACCEPTED)
def report_presence(report: PresenceReport) -> PresenceAccepted:
    """AI 모델은 '관찰 사실'만 보고합니다. 조치 결정(자동 저감/차단)은 전적으로 서버 몫입니다."""
    safety_phase, triggered_event_id = safety_service.evaluate_presence(report)
    return PresenceAccepted(accepted=True, safetyPhase=safety_phase, triggeredEventId=triggered_event_id)


# ---------------------------------------------------------------------------
# 초기 전체 상태
# ---------------------------------------------------------------------------

@router.get("/snapshot", response_model=SnapshotResponse)
def read_snapshot() -> SnapshotResponse:
    """앱을 켤 때 한 번 호출: 프론트의 loadSnapshot()에 1:1 대응."""
    device_id = settings.INDUCTION_DEVICE_ID
    room = settings.KITCHEN_ROOM

    telemetry = state_store.get_telemetry(device_id)
    presence = state_store.get_presence(room)
    active_session_id = state_store.get_active_session_id(device_id)
    session = state_store.get_session(active_session_id) if active_session_id else None

    safety_phase = safety_service.compute_safety_phase(room, device_id)
    active_incident = _compute_active_incident()

    appliance = ApplianceSnapshot(
        deviceId=device_id,
        online=state_store.is_online(device_id),
        burners=telemetry.burners if telemetry else [],
        lastControl=telemetry.lastControl if telemetry else None,
    )

    return SnapshotResponse(
        serverTime=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        session=session,
        rooms={room: KitchenRoomSnapshot(presence=presence, environment={}, safetyPhase=safety_phase)},
        appliances=[appliance],
        activeIncident=active_incident,
    )


# ---------------------------------------------------------------------------
# 화구 제어
# ---------------------------------------------------------------------------

@router.post(
    "/appliances/{appliance_id}/burners/{burner_id}/commands",
    response_model=CommandAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def send_burner_command(appliance_id: str, burner_id: str, request: BurnerCommandRequest) -> CommandAccepted:
    """
    화구 제어는 전부 이 엔드포인트 하나로 처리합니다.
    사용자 명령과 시스템(부재중 정책) 자동 명령이 같은 형태로 이력에 남아야 감사가 됩니다.
    과열 상태에서 turn_on/set_level을 시도하면 409로 거부됩니다.
    """
    try:
        record = commands_service.dispatch_command(appliance_id, burner_id, request, actor="user")
    except commands_service.CommandRejected as exc:
        safety_service.handle_command_blocked(
            settings.KITCHEN_ROOM,
            state_store.get_active_session_id(appliance_id),
            exc.reasons,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BURNER_OVERHEATED", "details": {"reasons": exc.reasons, "allowedCommands": ["turn_off"]}},
        ) from exc

    return CommandAccepted(commandId=record.commandId, status="pending", issuedAt=record.issuedAt)


@router.get("/commands/{command_id}", response_model=CommandRecord)
def read_command(command_id: str) -> CommandRecord:
    """WebSocket을 못 쓸 때의 폴백용 명령 상태 조회."""
    record = state_store.get_command(command_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 commandId를 찾을 수 없습니다.")
    return record


# ---------------------------------------------------------------------------
# 안전 이력
# ---------------------------------------------------------------------------

@router.get("/safety-events", response_model=SafetyEventListResponse)
def list_safety_events(
    room: Optional[str] = None,
    sessionId: Optional[str] = None,
    type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> SafetyEventListResponse:
    events = state_store.list_safety_events(room=room, session_id=sessionId, type_=type)
    total = len(events)
    start = max(page - 1, 0) * size
    page_items = events[start : start + size]
    return SafetyEventListResponse(items=page_items, page=page, size=size, total=total)


@router.get("/safety-events/{event_id}", response_model=SafetyEvent)
def read_safety_event(event_id: str) -> SafetyEvent:
    event = state_store.get_safety_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 eventId를 찾을 수 없습니다.")
    return event


@router.post("/safety-events/{event_id}/feedback", response_model=SafetyEventFeedbackResult, status_code=201)
def submit_safety_event_feedback(event_id: str, feedback: SafetyEventFeedback) -> SafetyEventFeedbackResult:
    """즉시 정책을 바꾸지 않습니다. 학습 데이터로만 축적합니다 (거부 한 번에 안전 임계값을 풀면 위험)."""
    event = state_store.get_safety_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 eventId를 찾을 수 없습니다.")

    submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    logger.info("안전 이벤트 피드백 수신 (eventId=%s, verdict=%s)", event_id, feedback.verdict)
    return SafetyEventFeedbackResult(eventId=event_id, verdict=feedback.verdict, submittedAt=submitted_at)


# ---------------------------------------------------------------------------
# 조리 세션
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}", response_model=SessionRecord)
def read_session(session_id: str) -> SessionRecord:
    session = state_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 sessionId를 찾을 수 없습니다.")
    return session


# ---------------------------------------------------------------------------
# 부재중 안전 정책
# ---------------------------------------------------------------------------

@router.get("/policies/kitchen-absence", response_model=KitchenAbsencePolicy)
def read_policy() -> KitchenAbsencePolicy:
    return state_store.get_policy()


@router.put("/policies/kitchen-absence", response_model=KitchenAbsencePolicy)
def update_policy(policy: KitchenAbsencePolicy) -> KitchenAbsencePolicy:
    """코드에 임계값을 박아두지 않고 API로 분리한 이유: 시연/튜닝 때마다 재배포하지 않아도 되도록."""
    state_store.set_policy(policy)
    return policy


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _compute_active_incident() -> Optional[SafetyEvent]:
    """
    데모 단순화 버전: 가장 최근 안전 이벤트가 아직 해소되지 않은 위험 이벤트
    (overheat_detected / auto_power_off / command_blocked)라면 진행 중인 사건으로 간주합니다.
    """
    events = state_store.list_safety_events()
    if not events:
        return None
    last = events[-1]
    if last.type in ("overheat_detected", "auto_power_off", "command_blocked"):
        return last
    return None
