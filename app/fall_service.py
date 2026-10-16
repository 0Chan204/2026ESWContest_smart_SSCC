"""
낙상 사고 안전 기능의 핵심 서비스입니다.

흐름 (v0.3.1 단계화):
1) report_fall(): 낙상 감지(POST /safety/fall-events 또는 AI 판단 fall_detected)가 들어오면
   즉시  (a) 인덕션 비상 전원 차단(재실 기반 점진적 저감과 달리 바로 turn_off)
         (b) 전등 깜빡임(LIGHT_BLINK_SEC초) - 주변에 위급 상황을 알림
         (c) 안전 이벤트 생성 + 대시보드 실시간 알림(WebSocket)
   1차   (d) 사용자 본인에게 확인 링크 문자 (+ (c)의 대시보드 알림)
   2차   (e) userAlertWaitSec 안에 응답이 없으면 보호자에게 확인 링크 문자
             (userAlertWaitSec=0이면 사용자와 보호자에게 동시에)
   3차   (f) 보호자 알림 뒤 autoReportSec 안에도 응답이 없으면 자동 "신고" 처리
   2차·3차는 _escalation_watchdog 타이머 하나가 순서대로 처리합니다.
2) resolve_fall_incident() / report_fall_incident(): 사용자나 보호자가 문자 링크(프론트가
   만드는 모바일 확인 페이지)에서 "해결"(괜찮음)/"신고" 버튼을 누르면 그 페이지가 호출합니다.
   confirmUrl에 들어있는 token으로 본인 확인을 하며, 이미 처리된 사건이면 거부합니다.
   처리된 사건은 다음 단계로 넘어가지 않습니다.
3) update_guardian() / update_user(): 대시보드에서 연락처를 등록/변경하면, 그 번호로 바로
   확인 문자를 보내 "연락처가 잘 오는지" 검증합니다 (팀 요구사항).
"""

import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import commands_service, device_registry, home_device_service, safety_service, sms_service, state_store, ws_hub
from app.config import settings
from app.schemas import (
    BurnerCommandRequest,
    FallDetectedReport,
    FallIncident,
    GuardianContact,
    GuardianContactUpdateResult,
    HomeDeviceCommandRequest,
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _seconds_until(iso_time: Optional[str]) -> float:
    """기한까지 남은 초. 기한이 지났거나 읽을 수 없으면 0"""
    if not iso_time:
        return 0
    try:
        return max(0.0, (datetime.fromisoformat(iso_time) - _now()).total_seconds())
    except ValueError:
        return 0


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
    """낙상 감지를 접수하고 즉시 조치 + 1차 알림을 수행한 뒤, 2차·3차 타이머를 겁니다.

    비상 상황이므로 각 단계는 서로 독립적입니다. 한 단계가 실패해도(인덕션 통신 끊김,
    전등 미등록, 연락처 미등록, 문자 발송 실패 등) 나머지 단계는 반드시 계속 진행합니다.
    실제로 수행된 조치는 사건의 shutoffSent / lightBlinkSent / userNotified / guardianNotified 에 기록됩니다.
    """
    policy = state_store.get_fall_policy()

    incident_id = _new_incident_id()
    token = secrets.token_urlsafe(16)
    confirm_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/fall/{incident_id}?token={token}"
    detected = _now()

    incident = FallIncident(
        incidentId=incident_id,
        room=report.room,
        status="pending",
        detectedAt=report.observedAt,
        confidence=report.confidence,
        confirmUrl=confirm_url,
        autoReportAt=_iso(detected + timedelta(seconds=policy.autoReportSec)),
    )
    state_store.save_fall_incident(incident, token)

    # (a) 인덕션 비상 전원 차단: 연락처 등록 여부와 무관하게 가장 먼저 수행합니다.
    shutoff_sent = _shut_off_stove()
    shutoff_text = "인덕션 비상 전원 차단 명령 전송" if shutoff_sent else "인덕션 차단 명령 전송 실패"

    # (b) 전등 깜빡임
    light_id, blink_sent = _blink_light(report.room, incident_id)
    if light_id is None:
        blink_text = "등록된 전등 없음"
    else:
        blink_text = "전등 깜빡임 명령 전송" if blink_sent else "전등 깜빡임 명령 전송 실패"
    state_store.update_fall_incident(
        incident_id, shutoffSent=shutoff_sent, lightBlinkSent=blink_sent, lightDeviceId=light_id
    )

    # (c) 안전 이벤트 생성 + 대시보드 실시간 알림 (문자 발송을 기다리지 않고 먼저 알립니다)
    event_id: Optional[str] = None
    try:
        event = safety_service.emit_event(
            "fall_detected",
            "danger",
            report.room,
            trigger=f"낙상 감지 confidence={report.confidence:.2f}",
            action=f"{shutoff_text} + {blink_text}",
            reasoning=f"modelVersion={report.modelVersion}",
        )
        event_id = event.eventId
    except Exception:
        logger.exception("낙상 안전 이벤트 생성 실패 (incidentId=%s)", incident_id)

    # (d) 1차: 사용자 본인에게 문자. 대시보드 알림(c)도 1차 알림이므로, 문자를 못 보내도
    #     (미등록, 대회장 인터넷 불안정 등) 사용자 응답 대기 단계는 그대로 진행합니다.
    user_notified, user_text = _notify_user(report.room, confirm_url, shutoff_sent, policy.userAlertWaitSec, incident_id)
    if user_text is None:
        user_text = "사용자 미등록으로 문자 미발송"

    if policy.userAlertWaitSec > 0:
        guardian_alert_at = detected + timedelta(seconds=policy.userAlertWaitSec)
        incident = state_store.update_fall_incident(
            incident_id,
            eventId=event_id,
            userNotified=user_notified,
            stage="user",
            guardianAlertAt=_iso(guardian_alert_at),
            autoReportAt=_iso(guardian_alert_at + timedelta(seconds=policy.autoReportSec)),
        ) or incident
        notify_text = f"{user_text} ({policy.userAlertWaitSec}초 안에 응답 없으면 보호자 알림)"
    else:
        # (e) 대기 시간이 0이면 사용자와 보호자에게 동시에 알립니다.
        guardian_notified, guardian_text = _notify_guardian(incident_id, after_user=False)
        incident = state_store.update_fall_incident(
            incident_id,
            eventId=event_id,
            userNotified=user_notified,
            stage="guardian",
            guardianAlertAt=_now_iso(),
            guardianAlertedAt=_now_iso(),
            guardianNotified=guardian_notified,
            autoReportAt=_iso(_now() + timedelta(seconds=policy.autoReportSec)),
        ) or incident
        notify_text = f"{user_text} + {guardian_text}"

    if event_id is not None:
        state_store.update_safety_event(event_id, action=f"{shutoff_text} + {blink_text} + {notify_text}")

    # (e)(f) 2차 보호자 알림 / 3차 자동 신고 타이머 예약
    try:
        ws_hub.run_coroutine_threadsafe(_escalation_watchdog(incident_id))
    except Exception:
        logger.exception("낙상 단계 진행 타이머 예약 실패 (incidentId=%s)", incident_id)

    ws_hub.broadcast_threadsafe("fall.incident", incident.model_dump())
    logger.info(
        "낙상 사건 접수 (incidentId=%s, room=%s, stage=%s, shutoffSent=%s, lightBlinkSent=%s, userNotified=%s, guardianNotified=%s)",
        incident_id,
        report.room,
        incident.stage,
        incident.shutoffSent,
        incident.lightBlinkSent,
        incident.userNotified,
        incident.guardianNotified,
    )
    return incident


def _shut_off_stove() -> bool:
    """재실 기반 정책과 달리 단계를 거치지 않고 바로 turn_off. (rules.py상 과열 중에도 항상 허용)"""
    try:
        commands_service.dispatch_command(
            settings.INDUCTION_DEVICE_ID,
            settings.BURNER_ID,
            BurnerCommandRequest(type="turn_off"),
            actor="system",
            reason="fall_detected emergency shutoff",
        )
        return True
    except commands_service.CommandRejected as exc:
        logger.error("낙상 비상 차단 명령이 거부됨(이례적인 상황): %s", exc.reasons)
    except Exception:
        logger.exception("낙상 비상 차단 명령 전송 실패 (인덕션 통신 상태 확인 필요). 알림은 계속 진행합니다.")
    return False


def _blink_light(room: str, incident_id: str) -> tuple[Optional[str], bool]:
    """낙상이 난 구역의 전등(없으면 첫 번째 전등)을 깜빡입니다. (전등 ID, 전송 성공 여부)"""
    light = device_registry.find_device(device_registry.LIGHT, room)
    if light is None:
        logger.warning("등록된 전등이 없어 깜빡임을 건너뜁니다 (incidentId=%s)", incident_id)
        return None, False
    try:
        home_device_service.dispatch(
            light.deviceId,
            HomeDeviceCommandRequest(type="blink"),
            actor="system",
            reason=f"fall_detected alert ({incident_id})",
        )
        return light.deviceId, True
    except Exception:
        logger.exception("낙상 전등 깜빡임 명령 전송 실패 (incidentId=%s)", incident_id)
        return light.deviceId, False


def _induction_text(shutoff_sent: bool) -> str:
    return (
        "인덕션에는 자동 차단 명령을 보냈습니다."
        if shutoff_sent
        else "인덕션 차단 명령을 보내지 못했으니 인덕션 상태를 꼭 확인해주세요."
    )


def _notify_user(
    room: str, confirm_url: str, shutoff_sent: bool, wait_sec: int, incident_id: str
) -> tuple[bool, Optional[str]]:
    """1차 알림. (발송 성공 여부, 이벤트 기록 문구). 사용자 미등록이면 문구는 None"""
    try:
        user = state_store.get_user()
        if user is None:
            return False, None
        wait_text = f"{wait_sec}초 안에 응답이 없으면 보호자에게 알립니다. " if wait_sec > 0 else ""
        message = (
            f"[HomeVIS] {user.name}님, {room}에서 낙상이 감지되었습니다. {_induction_text(shutoff_sent)} "
            f"괜찮으시면 아래 링크에서 '괜찮음'을 눌러주세요. {wait_text}{confirm_url}"
        )
        sent = _send_sms(user.phone, message, "fall_user_alert", incident_id)
        return sent, "사용자 문자 발송" if sent else "사용자 문자 발송 실패"
    except Exception:
        logger.exception("사용자 문자 발송 중 오류 (incidentId=%s)", incident_id)
        return False, "사용자 문자 발송 실패"


def _notify_guardian(incident_id: str, after_user: bool) -> tuple[bool, str]:
    """2차 알림. (발송 성공 여부, 이벤트 기록 문구)"""
    try:
        guardian = state_store.get_guardian()
        if guardian is None:
            logger.warning("보호자 연락처가 등록되지 않아 문자를 보내지 못했습니다 (incidentId=%s)", incident_id)
            return False, "보호자 미등록으로 문자 미발송"
        incident = state_store.get_fall_incident(incident_id)
        user = state_store.get_user()
        who = f"{user.name}님 댁 " if user is not None else ""
        no_answer = "본인이 응답하지 않아 보호자님께 알립니다. " if after_user else ""
        message = (
            f"[HomeVIS] {who}{incident.room}에서 낙상이 감지되었습니다. {no_answer}"
            f"{_induction_text(incident.shutoffSent)} 아래 링크에서 상황을 확인해주세요: {incident.confirmUrl}"
        )
        sent = _send_sms(guardian.phone, message, "fall_alert", incident_id)
        return sent, "보호자 문자 발송" if sent else "보호자 문자 발송 실패"
    except Exception:
        logger.exception("보호자 문자 발송 중 오류 (incidentId=%s)", incident_id)
        return False, "보호자 문자 발송 실패"


def escalate_to_guardian(incident_id: str) -> Optional[FallIncident]:
    """2차: 사용자가 기한 안에 응답하지 않았을 때 보호자에게 알립니다.
    이미 처리됐거나 이미 보호자 단계면 아무것도 하지 않습니다."""
    incident = state_store.get_fall_incident(incident_id)
    if incident is None or incident.status != "pending" or incident.stage != "user":
        return None

    # 문자 발송 전에 단계를 먼저 바꿔 두 번 보내지 않게 합니다.
    state_store.update_fall_incident(incident_id, stage="guardian", guardianAlertedAt=_now_iso())
    notified, notify_text = _notify_guardian(incident_id, after_user=True)
    updated = state_store.update_fall_incident(incident_id, guardianNotified=notified)

    policy = state_store.get_fall_policy()
    try:
        safety_service.emit_event(
            "fall_escalated",
            "danger",
            updated.room,
            trigger=f"사용자가 {policy.userAlertWaitSec}초 안에 응답하지 않음",
            action=notify_text,
            reasoning=f"incidentId={incident_id}, 자동 신고 예정 {updated.autoReportAt}",
        )
    except Exception:
        logger.exception("낙상 단계 이벤트 생성 실패 (incidentId=%s)", incident_id)
    ws_hub.broadcast_threadsafe("fall.incident", updated.model_dump())
    logger.warning("낙상 사건 보호자 단계로 전환 (incidentId=%s, guardianNotified=%s)", incident_id, notified)
    return updated


def auto_report(incident_id: str) -> Optional[FallIncident]:
    """3차: 보호자도 응답하지 않았을 때 자동 신고 처리"""
    incident = state_store.get_fall_incident(incident_id)
    if incident is None or incident.status != "pending":
        return None  # 그 사이에 이미 해결/신고 처리됨

    updated = state_store.update_fall_incident(incident_id, status="auto_reported", reportedAt=_now_iso())
    safety_service.emit_event(
        "fall_auto_reported",
        "danger",
        updated.room,
        trigger="확인 링크 미응답으로 자동 신고 대기 시간 경과",
        action="자동 신고 처리 (실제 119/응급 연동은 추후 구현 예정)",
        reasoning="사용자와 보호자가 확인 페이지에서 응답하지 않아 정책에 따라 자동으로 신고 처리됨",
    )
    ws_hub.broadcast_threadsafe("fall.incident", updated.model_dump())
    logger.warning("낙상 사건 자동 신고 처리 (incidentId=%s)", incident_id)
    return updated


async def _escalation_watchdog(incident_id: str) -> None:
    """사건에 저장된 시각(guardianAlertAt, autoReportAt)을 기준으로 2차·3차를 순서대로 진행합니다.
    시각을 사건에 저장해 두기 때문에 서버를 다시 켜도 같은 함수로 이어서 진행할 수 있습니다."""
    incident = state_store.get_fall_incident(incident_id)
    if incident is None or incident.status != "pending":
        return

    if incident.stage == "user":
        await asyncio.sleep(_seconds_until(incident.guardianAlertAt))
        # 문자 발송(HTTP 요청)이 이벤트 루프를 막지 않도록 별도 스레드에서 실행
        await asyncio.to_thread(escalate_to_guardian, incident_id)
        incident = state_store.get_fall_incident(incident_id)
        if incident is None or incident.status != "pending":
            return

    await asyncio.sleep(_seconds_until(incident.autoReportAt))
    auto_report(incident_id)


def resume_pending_incidents() -> int:
    """서버 시작 시 호출: 재시작 전에 접수되어 아직 응답을 기다리던 낙상 사건의
    단계 진행 타이머를 다시 겁니다. 이미 기한이 지난 단계는 곧바로 진행됩니다.
    (타이머는 메모리에만 있어서 재시작하면 사라지기 때문에 필요합니다)"""
    pending = state_store.list_pending_fall_incidents()
    for incident in pending:
        ws_hub.run_coroutine_threadsafe(_escalation_watchdog(incident.incidentId))
    if pending:
        logger.info("응답 대기 중이던 낙상 사건 %d건의 단계 진행 타이머를 다시 걸었습니다.", len(pending))
    return len(pending)


# ---------------------------------------------------------------------------
# 사용자·보호자의 확인 페이지 응답 ("해결"(괜찮음) / "신고")
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


def _responder(incident: FallIncident) -> str:
    """같은 링크를 사용자와 보호자가 함께 쓰므로, 응답 시점의 단계로 누가 눌렀을지 표시합니다."""
    return "사용자" if incident.stage == "user" else "사용자 또는 보호자"


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
        trigger=f"{_responder(incident)}가 확인 페이지에서 '해결'(괜찮음) 선택",
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
        trigger=f"{_responder(incident)}가 확인 페이지에서 '신고' 선택",
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
    낙상 발생 시 이 번호로 1차 확인 문자가 가고, 응답이 없으면 보호자에게 넘어갑니다."""
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
