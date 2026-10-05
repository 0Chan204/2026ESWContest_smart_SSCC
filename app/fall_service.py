"""
낙상 사고 안전 기능의 핵심 서비스입니다.

흐름:
1) report_fall(): 낙상 감지 AI 모델 -> POST /safety/fall-events 로 들어오면
   (a) 인덕션 비상 전원 차단(재실 기반 점진적 저감과 달리 즉시 0단계/turn_off)
   (b) 안전 이벤트 생성 + 대시보드 실시간 알림(WebSocket)
   (c) 보호자에게 확인 링크가 담긴 SMS 발송
   (d) autoReportSec 뒤에도 응답이 없으면 자동으로 "신고" 처리하는 타이머 예약
   을 한 번에 수행하고 FallIncident를 만듭니다.
2) resolve_fall_incident() / report_fall_incident(): 보호자가 SMS 링크(프론트가
   만드는 모바일 확인 페이지)에서 "해결"/"신고" 버튼을 누르면 그 페이지가 호출합니다.
   confirmUrl에 들어있는 token으로 본인 확인을 하며, 이미 처리된 사건이면 거부합니다.
3) update_guardian(): 대시보드에서 보호자 연락처를 등록/변경하면, 그 번호로 바로
   확인 문자를 보내 "연락처가 잘 오는지" 검증합니다 (팀 요구사항).
"""

import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import commands_service, safety_service, sms_service, state_store, ws_hub
from app.config import settings
from app.schemas import (
    BurnerCommandRequest,
    FallDetectedReport,
    FallIncident,
    GuardianContact,
    GuardianContactUpdateResult,
    SmsLog,
    UserContact,
    UserContactUpdateResult,
)

logger = logging.getLogger("induction.fall")


class FallIncidentError(Exception):
    """라우터에서 적절한 HTTP 상태 코드로 변환하기 위한 예외."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_incident_id() -> str:
    return f"fall-{uuid.uuid4().hex[:10]}"


def _send_sms(to_phone: str, content: str, purpose: str, incident_id: Optional[str] = None) -> bool:
    """문자를 보내고, 성공/실패와 관계없이 발송 이력을 남깁니다."""
    success = sms_service.send_sms(to_phone, content)
    state_store.save_sms_log(
        SmsLog(
            logId=f"sms-{uuid.uuid4().hex[:12]}",
            to=to_phone,
            purpose=purpose,
            success=success,
            sentAt=_now_iso(),
            incidentId=incident_id,
        )
    )
    return success


# ---------------------------------------------------------------------------
# 낙상 감지 접수
# ---------------------------------------------------------------------------

def report_fall(report: FallDetectedReport) -> FallIncident:
    device_id = settings.INDUCTION_DEVICE_ID
    burner_id = settings.BURNER_ID
    policy = state_store.get_fall_policy()

    incident_id = _new_incident_id()
    token = secrets.token_urlsafe(16)
    auto_report_at = datetime.now(timezone.utc) + timedelta(seconds=policy.autoReportSec)
    confirm_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/fall/{incident_id}?token={token}"

    incident = FallIncident(
        incidentId=incident_id,
        room=report.room,
        status="pending",
        detectedAt=report.observedAt,
        confidence=report.confidence,
        confirmUrl=confirm_url,
        autoReportAt=auto_report_at.isoformat(timespec="seconds"),
    )
    state_store.save_fall_incident(incident, token)

    # (a) 인덕션 비상 전원 차단: 재실 기반 정책(watch/reduce/off)과 달리 단계를 거치지 않고
    #     바로 turn_off(0단계). rules.py상 turn_off는 overheated 상태에서도 항상 허용되므로
    #     이 호출이 거부되는 일은 없어야 정상입니다(혹시 거부되면 이례적인 상황으로 로그만 남김).
    try:
        commands_service.dispatch_command(
            device_id,
            burner_id,
            BurnerCommandRequest(type="turn_off"),
            actor="system",
            reason="fall_detected emergency shutoff",
        )
    except commands_service.CommandRejected as exc:
        logger.error("낙상 비상 차단 명령이 거부됨(이례적인 상황): %s", exc.reasons)

    # (b) 안전 이벤트 생성 + 대시보드 실시간 알림
    event = safety_service.emit_event(
        "fall_detected",
        "danger",
        report.room,
        trigger=f"낙상 감지 모델 confidence={report.confidence:.2f}",
        action="인덕션 비상 전원 차단 + 보호자 SMS 발송",
        reasoning=f"modelVersion={report.modelVersion}",
    )
    incident = state_store.update_fall_incident(incident_id, eventId=event.eventId) or incident

    # (c) 보호자 SMS 발송
    guardian = state_store.get_guardian()
    if guardian is not None:
        user = state_store.get_user()
        who = f"{user.name}님 댁 " if user is not None else ""
        message = (
            f"[HomeVIS] {who}{report.room}에서 낙상이 감지되었습니다. "
            f"인덕션은 안전을 위해 자동으로 꺼졌습니다. 아래 링크에서 상황을 확인해주세요: {confirm_url}"
        )
        _send_sms(guardian.phone, message, "fall_alert", incident_id)
    else:
        logger.warning("보호자 연락처가 등록되지 않아 SMS를 보내지 못했습니다 (incidentId=%s)", incident_id)

    # (d) 미응답 시 자동 신고 타이머 예약
    ws_hub.run_coroutine_threadsafe(_auto_report_watchdog(incident_id, policy.autoReportSec))

    ws_hub.broadcast_threadsafe("fall.incident", incident.model_dump())
    logger.info("낙상 사건 접수 (incidentId=%s, room=%s)", incident_id, report.room)
    return incident


async def _auto_report_watchdog(incident_id: str, delay_sec: int) -> None:
    await asyncio.sleep(delay_sec)
    incident = state_store.get_fall_incident(incident_id)
    if incident is None or incident.status != "pending":
        return  # 그 사이에 이미 해결/신고 처리됨

    updated = state_store.update_fall_incident(incident_id, status="auto_reported", reportedAt=_now_iso())
    safety_service.emit_event(
        "fall_auto_reported",
        "danger",
        updated.room,
        trigger="확인 링크 미응답으로 자동 신고 대기 시간 경과",
        action="자동 신고 처리 (실제 119/응급 연동은 추후 구현 예정)",
        reasoning="보호자가 확인 페이지에서 응답하지 않아 정책에 따라 자동으로 신고 처리됨",
    )
    ws_hub.broadcast_threadsafe("fall.incident", updated.model_dump())
    logger.warning("낙상 사건 자동 신고 처리 (incidentId=%s)", incident_id)


def resume_pending_incidents() -> int:
    """서버 시작 시 호출: 재시작 전에 접수되어 아직 응답을 기다리던 낙상 사건의
    자동 신고 타이머를 다시 겁니다. 이미 기한이 지난 사건은 곧바로 자동 신고 처리됩니다.
    (타이머는 메모리에만 있어서 재시작하면 사라지기 때문에 필요합니다)"""
    pending = state_store.list_pending_fall_incidents()
    now = datetime.now(timezone.utc)
    for incident in pending:
        try:
            deadline = datetime.fromisoformat(incident.autoReportAt)
            remaining = max(0, int((deadline - now).total_seconds()))
        except ValueError:
            remaining = 0
        ws_hub.run_coroutine_threadsafe(_auto_report_watchdog(incident.incidentId, remaining))
    if pending:
        logger.info("응답 대기 중이던 낙상 사건 %d건의 자동 신고 타이머를 다시 걸었습니다.", len(pending))
    return len(pending)


# ---------------------------------------------------------------------------
# 보호자의 확인 페이지 응답 ("해결" / "신고")
# ---------------------------------------------------------------------------

def _get_incident_or_404(incident_id: str) -> FallIncident:
    incident = state_store.get_fall_incident(incident_id)
    if incident is None:
        raise FallIncidentError(404, "해당 incidentId를 찾을 수 없습니다.")
    return incident


def _verify_token(incident_id: str, token: str) -> None:
    expected = state_store.get_fall_token(incident_id)
    if expected is None or not secrets.compare_digest(expected, token):
        raise FallIncidentError(403, "유효하지 않은 확인 링크입니다.")


def resolve_fall_incident(incident_id: str, token: str) -> FallIncident:
    incident = _get_incident_or_404(incident_id)
    _verify_token(incident_id, token)
    if incident.status != "pending":
        raise FallIncidentError(409, f"이미 '{incident.status}' 상태라 처리할 수 없습니다.")

    updated = state_store.update_fall_incident(incident_id, status="resolved", resolvedAt=_now_iso())
    safety_service.emit_event(
        "fall_resolved",
        "info",
        updated.room,
        trigger="보호자가 확인 페이지에서 '해결' 선택",
        action="낙상 사건 종료 처리",
    )
    ws_hub.broadcast_threadsafe("fall.incident", updated.model_dump())
    return updated


def report_fall_incident(incident_id: str, token: str) -> FallIncident:
    incident = _get_incident_or_404(incident_id)
    _verify_token(incident_id, token)
    if incident.status != "pending":
        raise FallIncidentError(409, f"이미 '{incident.status}' 상태라 처리할 수 없습니다.")

    updated = state_store.update_fall_incident(incident_id, status="reported", reportedAt=_now_iso())
    safety_service.emit_event(
        "fall_reported",
        "danger",
        updated.room,
        trigger="보호자가 확인 페이지에서 '신고' 선택",
        action="신고 처리 (실제 119/응급 연동은 추후 구현 예정)",
    )
    ws_hub.broadcast_threadsafe("fall.incident", updated.model_dump())
    return updated


# ---------------------------------------------------------------------------
# 보호자 연락처 등록/변경
# ---------------------------------------------------------------------------

def update_guardian(contact: GuardianContact) -> GuardianContactUpdateResult:
    """연락처를 저장하고, 바로 확인 문자를 보내 번호가 유효한지 검증합니다."""
    state_store.set_guardian(contact)

    verification_text = (
        f"[HomeVIS] {contact.name}님, 이 번호가 HomeVIS 보호자 연락처로 등록되었습니다. "
        "이 문자가 보인다면 정상적으로 연결된 것입니다."
    )
    sent = _send_sms(contact.phone, verification_text, "guardian_verification")

    message = (
        "연락처를 저장하고 확인 문자를 발송했습니다."
        if sent
        else "연락처는 저장했지만 확인 문자 발송에 실패했습니다. SMS 설정(.env의 SOLAPI_*)을 확인해주세요."
    )
    return GuardianContactUpdateResult(guardian=contact, verificationSent=sent, message=message)


def get_guardian() -> Optional[GuardianContact]:
    return state_store.get_guardian()


# ---------------------------------------------------------------------------
# 사용자(거주자 본인) 연락처 등록/변경
# ---------------------------------------------------------------------------

def update_user(contact: UserContact) -> UserContactUpdateResult:
    """사용자 연락처를 저장하고, 보호자와 마찬가지로 확인 문자를 보내 번호를 검증합니다.
    낙상 발생 시 문자는 보호자에게만 가며(팀 결정), 사용자 이름은 그 문자 문구에 들어갑니다."""
    state_store.set_user(contact)

    verification_text = (
        f"[HomeVIS] {contact.name}님, 이 번호가 HomeVIS 사용자 연락처로 등록되었습니다. "
        "이 문자가 보인다면 정상적으로 연결된 것입니다."
    )
    sent = _send_sms(contact.phone, verification_text, "user_verification")

    message = (
        "연락처를 저장하고 확인 문자를 발송했습니다."
        if sent
        else "연락처는 저장했지만 확인 문자 발송에 실패했습니다. SMS 설정(.env의 SOLAPI_*)을 확인해주세요."
    )
    return UserContactUpdateResult(user=contact, verificationSent=sent, message=message)


def get_user() -> Optional[UserContact]:
    return state_store.get_user()
