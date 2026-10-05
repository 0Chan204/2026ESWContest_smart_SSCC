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
    """낙상 감지를 접수하고 비상 조치를 수행합니다.

    비상 상황이므로 각 단계는 서로 독립적입니다. 한 단계가 실패해도(인덕션 통신 끊김,
    보호자 미등록, 문자 발송 실패 등) 나머지 단계는 반드시 계속 진행합니다.
    실제로 수행된 조치는 사건의 shutoffSent / guardianNotified 에 기록됩니다.
    """
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

    # (a) 인덕션 비상 전원 차단: 연락처 등록 여부와 무관하게 가장 먼저 수행합니다.
    #     재실 기반 정책(watch/reduce/off)과 달리 단계를 거치지 않고 바로 turn_off.
    #     rules.py상 turn_off는 overheated 상태에서도 항상 허용됩니다.
    shutoff_sent = False
    try:
        commands_service.dispatch_command(
            device_id,
            burner_id,
            BurnerCommandRequest(type="turn_off"),
            actor="system",
            reason="fall_detected emergency shutoff",
        )
        shutoff_sent = True
    except commands_service.CommandRejected as exc:
        logger.error("낙상 비상 차단 명령이 거부됨(이례적인 상황): %s", exc.reasons)
    except Exception:
        logger.exception("낙상 비상 차단 명령 전송 실패 (인덕션 통신 상태 확인 필요). 알림은 계속 진행합니다.")
    shutoff_text = "인덕션 비상 전원 차단 명령 전송" if shutoff_sent else "인덕션 차단 명령 전송 실패"

    # (b) 안전 이벤트 생성 + 대시보드 실시간 알림 (문자 발송을 기다리지 않고 먼저 알립니다)
    event_id: Optional[str] = None
    try:
        event = safety_service.emit_event(
            "fall_detected",
            "danger",
            report.room,
            trigger=f"낙상 감지 모델 confidence={report.confidence:.2f}",
            action=shutoff_text,
            reasoning=f"modelVersion={report.modelVersion}",
        )
        event_id = event.eventId
    except Exception:
        logger.exception("낙상 안전 이벤트 생성 실패 (incidentId=%s)", incident_id)

    # (c) 보호자 문자 발송
    guardian_notified = False
    notify_text = "보호자 미등록으로 문자 미발송"
    try:
        guardian = state_store.get_guardian()
        if guardian is None:
            logger.warning("보호자 연락처가 등록되지 않아 문자를 보내지 못했습니다 (incidentId=%s)", incident_id)
        else:
            user = state_store.get_user()
            who = f"{user.name}님 댁 " if user is not None else ""
            induction_text = (
                "인덕션에는 자동 차단 명령을 보냈습니다."
                if shutoff_sent
                else "인덕션 차단 명령을 보내지 못했으니 인덕션 상태를 꼭 확인해주세요."
            )
            message = (
                f"[HomeVIS] {who}{report.room}에서 낙상이 감지되었습니다. "
                f"{induction_text} 아래 링크에서 상황을 확인해주세요: {confirm_url}"
            )
            guardian_notified = _send_sms(guardian.phone, message, "fall_alert", incident_id)
            notify_text = "보호자 문자 발송" if guardian_notified else "보호자 문자 발송 실패"
    except Exception:
        notify_text = "보호자 문자 발송 실패"
        logger.exception("보호자 문자 발송 중 오류 (incidentId=%s)", incident_id)

    # 실제로 수행된 조치를 사건과 이벤트 기록에 반영
    incident = (
        state_store.update_fall_incident(
            incident_id, eventId=event_id, shutoffSent=shutoff_sent, guardianNotified=guardian_notified
        )
        or incident
    )
    if event_id is not None:
        state_store.update_safety_event(event_id, action=f"{shutoff_text} + {notify_text}")

    # (d) 미응답 시 자동 신고 타이머 예약
    try:
        ws_hub.run_coroutine_threadsafe(_auto_report_watchdog(incident_id, policy.autoReportSec))
    except Exception:
        logger.exception("자동 신고 타이머 예약 실패 (incidentId=%s)", incident_id)

    ws_hub.broadcast_threadsafe("fall.incident", incident.model_dump())
    logger.info(
        "낙상 사건 접수 (incidentId=%s, room=%s, shutoffSent=%s, guardianNotified=%s)",
        incident_id,
        report.room,
        shutoff_sent,
        guardian_notified,
    )
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
