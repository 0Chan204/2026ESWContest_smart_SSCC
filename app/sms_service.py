"""
보호자에게 SMS를 보내는 모듈입니다. (팀 결정: 네이버 클라우드 플랫폼 SENS 사용)

NCP 콘솔(https://console.ncloud.com)에서 SENS > SMS 서비스를 생성하면
서비스 ID / 접근 키(Access Key) / 비밀 키(Secret Key) / 발신번호(사전 등록 필요)를
받을 수 있습니다. 이 4개 값을 .env의 NAVER_SENS_* 에 채워 넣으면 바로 동작합니다.

아직 NCP 계정/키를 발급받기 전이라도(.env가 비어있어도) 서버가 죽지 않도록,
그럴 땐 실제 발송 대신 로그만 남기고 성공/실패를 False로 돌려줍니다.
"""

import base64
import hashlib
import hmac
import logging
import time

import requests

from app.config import settings

logger = logging.getLogger("induction.sms")

SENS_BASE_URL = "https://sens.apigw.ntruss.com"

# 한글 기준 45자(바이트로는 넉넉히 2000byte 이하) 넘어가면 LMS로 자동 전환.
# SMS 단문 제한(90byte)을 넘기면 SENS가 아예 거부하기 때문.
_SMS_BYTE_LIMIT = 80


def is_configured() -> bool:
    return bool(
        settings.NAVER_SENS_SERVICE_ID
        and settings.NAVER_SENS_ACCESS_KEY
        and settings.NAVER_SENS_SECRET_KEY
        and settings.NAVER_SENS_SENDER_PHONE
    )


def _make_signature(method: str, url_path: str, timestamp: str) -> str:
    message = f"{method} {url_path}\n{timestamp}\n{settings.NAVER_SENS_ACCESS_KEY}"
    digest = hmac.new(
        settings.NAVER_SENS_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_sms(to_phone: str, content: str) -> bool:
    """SMS(길면 LMS로 자동 전환)를 발송합니다. 성공 여부(bool)를 반환합니다.

    NAVER_SENS_* 설정이 비어있으면 실제로 보내지 않고 로그만 남깁니다.
    (NCP 콘솔에서 키 발급 전에도 나머지 낙상 감지 흐름은 테스트할 수 있도록)
    """
    if not is_configured():
        logger.warning(
            "NAVER_SENS 설정이 비어있어 SMS를 실제로 보내지 않습니다 (.env 확인 필요). to=%s, content=%s",
            to_phone,
            content,
        )
        return False

    url_path = f"/sms/v2/services/{settings.NAVER_SENS_SERVICE_ID}/messages"
    timestamp = str(int(time.time() * 1000))
    signature = _make_signature("POST", url_path, timestamp)

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "x-ncp-apigw-timestamp": timestamp,
        "x-ncp-iam-access-key": settings.NAVER_SENS_ACCESS_KEY,
        "x-ncp-apigw-signature-v2": signature,
    }
    body = {
        "type": "LMS" if len(content.encode("utf-8")) > _SMS_BYTE_LIMIT else "SMS",
        "contentType": "COMM",
        "countryCode": "82",
        "from": settings.NAVER_SENS_SENDER_PHONE,
        "content": content,
        "messages": [{"to": to_phone}],
    }

    try:
        response = requests.post(SENS_BASE_URL + url_path, headers=headers, json=body, timeout=5)
        response.raise_for_status()
        logger.info("SMS 발송 성공 (to=%s, requestId=%s)", to_phone, response.json().get("requestId"))
        return True
    except Exception:
        logger.exception("SMS 발송 실패 (to=%s)", to_phone)
        return False
