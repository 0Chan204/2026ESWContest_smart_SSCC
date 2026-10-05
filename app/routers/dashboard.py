"""
프론트(대시보드) 및 AI 재실 판단 모델이 호출하는 REST API입니다.

Swagger 문서에서는 엔드포인트마다 기능별 태그(회원 정보 / 낙상 사고 감지 / AI 재실 판단 /
인덕션 제어 / 대시보드 화면 / 안전 이벤트)를 붙여 섹션을 나눕니다. 태그 목록은 app/main.py 참고.

v0.2.1 추가: 낙상 사고 안전 기능 (보호자 연락처 등록, 낙상 감지 접수,
낙상 사건 해결/신고, 낙상 안전 정책). 실제 로직은 app/fall_service.py에 있고
여기서는 HTTP 입출력 변환 + 에러 코드 매핑만 담당합니다.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from app import commands_service, fall_service, safety_service, state_store
from app.config import settings
from app.schemas import (
    ApplianceSnapshot,
    BurnerCommandRequest,
    CommandAccepted,
    CommandRecord,
    FallActionResult,
    FallDetectedReport,
    FallIncident,
    FallIncidentAccepted,
    FallPolicy,
    GuardianContact,
    GuardianContactUpdateResult,
    KitchenAbsencePolicy,
    KitchenRoomSnapshot,
    PresenceAccepted,
    PresenceReport,
    SafetyEvent,
    SafetyEventFeedback,
    SafetyEventFeedbackResult,
    SafetyEventListResponse,
    SafetyEventFeedbackRecord,
    SessionRecord,
    SmsLogListResponse,
    SnapshotResponse,
    UserContact,
    UserContactUpdateResult,
)

logger = logging.getLogger("induction.dashboard")

router = APIRouter()


# ---------------------------------------------------------------------------
# 재실 판단 (AI 모델 -> 서버)
# ---------------------------------------------------------------------------

@router.post("/presence", response_model=PresenceAccepted, status_code=status.HTTP_202_ACCEPTED, tags=["AI 재실 판단"], summary="재실 판단 결과 보고 (AI 모델 → 서버)")
def report_presence(report: PresenceReport) -> PresenceAccepted:
    """AI 모델은 '관찰 사실'만 보고합니다. 조치 결정(자동 저감/차단)은 전적으로 서버 몫입니다."""
    safety_phase, triggered_event_id = safety_service.evaluate_presence(report)
    return PresenceAccepted(accepted=True, safetyPhase=safety_phase, triggeredEventId=triggered_event_id)


# ---------------------------------------------------------------------------
# 초기 전체 상태
# ---------------------------------------------------------------------------

@router.get("/snapshot", response_model=SnapshotResponse, tags=["대시보드 화면"], summary="초기 전체 상태 조회")
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
    tags=["인덕션 제어"], summary="화구 제어 명령 전송",
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


@router.get("/commands/{command_id}", response_model=CommandRecord, tags=["인덕션 제어"], summary="제어 명령 처리 상태 조회")
def read_command(command_id: str) -> CommandRecord:
    """WebSocket을 못 쓸 때의 폴백용 명령 상태 조회."""
    record = state_store.get_command(command_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 commandId를 찾을 수 없습니다.")
    return record


# ---------------------------------------------------------------------------
# 안전 이력
# ---------------------------------------------------------------------------

@router.get("/safety-events", response_model=SafetyEventListResponse, tags=["안전 이벤트"], summary="안전 이벤트 목록 조회")
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


@router.get("/safety-events/{event_id}", response_model=SafetyEvent, tags=["안전 이벤트"], summary="안전 이벤트 단건 조회")
def read_safety_event(event_id: str) -> SafetyEvent:
    event = state_store.get_safety_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 eventId를 찾을 수 없습니다.")
    return event


@router.post("/safety-events/{event_id}/feedback", response_model=SafetyEventFeedbackResult, status_code=201, tags=["안전 이벤트"], summary="안전 이벤트 피드백 제출")
def submit_safety_event_feedback(event_id: str, feedback: SafetyEventFeedback) -> SafetyEventFeedbackResult:
    """즉시 정책을 바꾸지 않습니다. 학습 데이터로만 축적합니다 (거부 한 번에 안전 임계값을 풀면 위험).
    제출한 의견은 해당 이벤트에 함께 저장되어 이벤트 조회 시 feedback 항목으로 확인할 수 있습니다.
    같은 이벤트에 다시 제출하면 가장 최근 의견으로 바뀝니다."""
    if state_store.get_safety_event(event_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 eventId를 찾을 수 없습니다.")

    submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state_store.update_safety_event(
        event_id,
        feedback=SafetyEventFeedbackRecord(
            verdict=feedback.verdict, comment=feedback.comment, submittedAt=submitted_at
        ),
    )
    logger.info("안전 이벤트 피드백 저장 (eventId=%s, verdict=%s)", event_id, feedback.verdict)
    return SafetyEventFeedbackResult(eventId=event_id, verdict=feedback.verdict, submittedAt=submitted_at)


# ---------------------------------------------------------------------------
# 조리 세션
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}", response_model=SessionRecord, tags=["대시보드 화면"], summary="조리 세션 타임라인 조회")
def read_session(session_id: str) -> SessionRecord:
    session = state_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 sessionId를 찾을 수 없습니다.")
    return session


# ---------------------------------------------------------------------------
# 부재중 안전 정책
# ---------------------------------------------------------------------------

@router.get("/policies/kitchen-absence", response_model=KitchenAbsencePolicy, tags=["AI 재실 판단"], summary="부재중 자동 제어 정책 조회")
def read_policy() -> KitchenAbsencePolicy:
    return state_store.get_policy()


@router.put("/policies/kitchen-absence", response_model=KitchenAbsencePolicy, tags=["AI 재실 판단"], summary="부재중 자동 제어 정책 수정")
def update_policy(policy: KitchenAbsencePolicy) -> KitchenAbsencePolicy:
    """코드에 임계값을 박아두지 않고 API로 분리한 이유: 시연/튜닝 때마다 재배포하지 않아도 되도록."""
    state_store.set_policy(policy)
    return policy


# ---------------------------------------------------------------------------
# 낙상 사고 안전 기능
# ---------------------------------------------------------------------------

@router.put("/user", response_model=UserContactUpdateResult, tags=["회원 정보"], summary="사용자 연락처 등록·변경")
def update_user(contact: UserContact) -> UserContactUpdateResult:
    """
    사용자(거주자 본인) 연락처를 등록/변경합니다. 저장과 동시에 그 번호로 확인 문자를 발송합니다.
    낙상 사고 문자는 보호자에게만 발송되며, 사용자 이름은 그 문자 문구에 포함됩니다.
    """
    return fall_service.update_user(contact)


@router.get("/user", response_model=UserContact, tags=["회원 정보"], summary="사용자 연락처 조회")
def read_user() -> UserContact:
    user = fall_service.get_user()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자 연락처가 아직 등록되지 않았습니다.")
    return user


@router.put("/guardian", response_model=GuardianContactUpdateResult, tags=["회원 정보"], summary="보호자 연락처 등록·변경")
def update_guardian(contact: GuardianContact) -> GuardianContactUpdateResult:
    """
    보호자 연락처를 등록/변경합니다 (최초 등록과 변경 모두 이 엔드포인트 하나로 처리:
    /policies/kitchen-absence와 동일한 패턴). 현재는 1명만 지원합니다(팀 결정).
    저장과 동시에 그 번호로 확인 문자를 바로 발송해서, 연락처가 유효한지(문자가 잘 오는지)
    바로 검증할 수 있게 합니다. (verificationSent로 발송 성공 여부 확인)
    """
    return fall_service.update_guardian(contact)


@router.get("/guardian", response_model=GuardianContact, tags=["회원 정보"], summary="보호자 연락처 조회")
def read_guardian() -> GuardianContact:
    guardian = fall_service.get_guardian()
    if guardian is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="보호자 연락처가 아직 등록되지 않았습니다.")
    return guardian


@router.get("/sms-logs", response_model=SmsLogListResponse, tags=["회원 정보"], summary="문자 발송 이력 조회")
def list_sms_logs(limit: int = 50) -> SmsLogListResponse:
    """최근 발송한 문자의 기록을 최신순으로 돌려줍니다. 문자 본문은 저장하지 않습니다."""
    logs = state_store.list_sms_logs()
    newest_first = list(reversed(logs))[: max(limit, 0)]
    return SmsLogListResponse(items=newest_first, total=len(logs))


@router.post("/safety/fall-events", response_model=FallIncidentAccepted, status_code=status.HTTP_202_ACCEPTED, tags=["낙상 사고 감지"], summary="낙상 감지 보고 (AI 모델 → 서버)")
def report_fall_event(report: FallDetectedReport) -> FallIncidentAccepted:
    """
    낙상 감지 AI 모델 -> 서버. 재실 판단 모델(POST /presence)과 같은 패턴으로,
    모델은 '감지 사실'만 보고합니다. 접수 즉시 서버가 인덕션 비상 전원 차단(0단계),
    대시보드 알림, 보호자 SMS 발송을 모두 수행합니다.
    """
    incident = fall_service.report_fall(report)
    return FallIncidentAccepted(incidentId=incident.incidentId, status=incident.status, confirmUrl=incident.confirmUrl)


@router.get("/fall-incidents/{incident_id}", response_model=FallIncident, tags=["낙상 사고 감지"], summary="낙상 사건 상태 조회")
def read_fall_incident(incident_id: str) -> FallIncident:
    incident = state_store.get_fall_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 incidentId를 찾을 수 없습니다.")
    return incident


@router.post("/fall-incidents/{incident_id}/resolve", response_model=FallActionResult, tags=["낙상 사고 감지"], summary="낙상 사건 '해결' 처리")
def resolve_fall_incident(incident_id: str, token: str) -> FallActionResult:
    """보호자가 SMS 링크(프론트의 모바일 확인 페이지)에서 '해결'을 눌렀을 때 호출됩니다."""
    try:
        incident = fall_service.resolve_fall_incident(incident_id, token)
    except fall_service.FallIncidentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FallActionResult(incidentId=incident.incidentId, status=incident.status, message="해결 처리되었습니다.")


@router.post("/fall-incidents/{incident_id}/report", response_model=FallActionResult, tags=["낙상 사고 감지"], summary="낙상 사건 '신고' 처리")
def report_fall_incident(incident_id: str, token: str) -> FallActionResult:
    """보호자가 SMS 링크(프론트의 모바일 확인 페이지)에서 '신고'를 눌렀을 때 호출됩니다."""
    try:
        incident = fall_service.report_fall_incident(incident_id, token)
    except fall_service.FallIncidentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FallActionResult(incidentId=incident.incidentId, status=incident.status, message="신고 처리되었습니다.")


@router.get("/policies/fall-safety", response_model=FallPolicy, tags=["낙상 사고 감지"], summary="낙상 안전 정책 조회")
def read_fall_policy() -> FallPolicy:
    return state_store.get_fall_policy()


@router.put("/policies/fall-safety", response_model=FallPolicy, tags=["낙상 사고 감지"], summary="낙상 안전 정책 수정")
def update_fall_policy(policy: FallPolicy) -> FallPolicy:
    """테스트 중엔 autoReportSec=60(1분)처럼 짧게 두고, 운영 값은 재배포 없이 여기서 조정합니다."""
    state_store.set_fall_policy(policy)
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
