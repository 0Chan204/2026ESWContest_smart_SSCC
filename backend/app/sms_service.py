"""
문자(SMS/LMS)를 보내는 모듈입니다. 솔라피(SOLAPI, 구 쿨SMS)를 사용합니다.

원래는 네이버 클라우드 SENS를 쓰려고 했지만, SENS는 사업자 계정만 이용할 수 있어서
개인 명의 번호도 본인인증만으로 발신번호 등록이 되는 솔라피로 바꿨습니다.

솔라피 콘솔(https://console.solapi.com)에서
  1) 발신번호 등록 (본인 휴대폰 번호, 본인인증)
  2) API Key 생성 (허용 IP에 이 서버의 외부 IP를 넣어야 합니다)
을 하고, .env의 SOLAPI_API_KEY / SOLAPI_API_SECRET / SOLAPI_SENDER_PHONE 을 채우면 동작합니다.

.env가 비어있어도 서버가 죽지 않도록, 그럴 땐 실제 발송 대신 로그만 남기고 False를 돌려줍니다.
"""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timezone

import requests

from app.config import settings

logger = logging.getLogger("induction.sms")

SOLAPI_SEND_URL = "https://api.solapi.com/messages/v4/send"


def is_configured() -> bool:
    return bool(settings.SOLAPI_API_KEY and settings.SOLAPI_API_SECRET and settings.SOLAPI_SENDER_PHONE)


def _auth_header() -> str:
    """솔라피 API Key 인증 헤더: 현재 시각(date) + 임의 문자열(salt)을 API Secret으로 서명합니다."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    salt = secrets.token_hex(16)
    signature = hmac.new(
        settings.SOLAPI_API_SECRET.encode("utf-8"),
        (date + salt).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"HMAC-SHA256 apiKey={settings.SOLAPI_API_KEY}, date={date}, salt={salt}, signature={signature}"


def send_sms(to_phone: str, content: str) -> bool:
    """문자를 발송하고 성공 여부(bool)를 반환합니다.

    단문(SMS)/장문(LMS) 구분은 내용 길이에 따라 솔라피가 자동으로 정합니다.
    SOLAPI_* 설정이 비어있으면 실제로 보내지 않고 로그만 남깁니다.
    """
    if not is_configured():
        logger.warning(
            "SOLAPI 설정이 비어있어 문자를 실제로 보내지 않습니다 (.env 확인 필요). to=%s, content=%s",
            to_phone,
            content,
        )
        return False

    body = {
        "message": {
            "to": re.sub(r"\D", "", to_phone),
            "from": re.sub(r"\D", "", settings.SOLAPI_SENDER_PHONE),
            "text": content,
        }
    }
    try:
        headers = {"Authorization": _auth_header(), "Content-Type": "application/json; charset=utf-8"}
        response = requests.post(SOLAPI_SEND_URL, headers=headers, json=body, timeout=5)
    except Exception:
        # 네트워크 오류뿐 아니라 설정값이 잘못된 경우(예: 키에 한글이 섞임)도 여기서 잡습니다.
        # 문자 한 건이 실패했다고 연락처 등록이나 낙상 처리 전체가 오류로 끝나면 안 되기 때문입니다.
        logger.exception("문자 발송 요청 실패 (to=%s)", to_phone)
        return False

    if response.status_code >= 400:
        # 실패 사유(허용되지 않은 IP, 미등록 발신번호, 잔액 부족 등)가 응답 본문에 들어있습니다.
        logger.error("문자 발송 실패 (to=%s, status=%s): %s", to_phone, response.status_code, response.text)
        return False

    logger.info("문자 발송 접수 (to=%s): %s", to_phone, response.text)
    return True
