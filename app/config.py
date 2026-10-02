"""
프로젝트 전역 설정값을 한 곳에서 관리하는 모듈입니다.

v0.2 변경사항 (프론트/임베디드 팀과 API 명세 확정 반영):
- 화구 개수를 2개(element_1/2) -> 1개(burners[0])로 축소
- MQTT ack 토픽 추가 (가전이 명령 처리 결과를 별도로 보고)
- 부재중 안전 정책 기본값(과열 150°C 진입 / 60°C 해제 등) 추가
- "오프라인 판정"은 별도 heartbeat 메시지 없이, 상태(telemetry) 토픽이
  일정 시간(HEARTBEAT_TIMEOUT_SEC) 이상 안 오면 offline으로 봄 (팀 결정)

v0.2.1 추가 (낙상 사고 안전 기능):
- 보호자 SMS 발송: 네이버 클라우드 플랫폼 SENS 사용 (팀 결정)
- 낙상 감지는 재실 판단 모델과 같은 패턴으로, 별도 AI 모델이 서버로 이벤트를 보냄
- SMS 링크로 들어가는 "해결/신고" 확인 페이지는 프론트가 만들고, 백엔드는 API만 제공
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- MQTT 브로커 접속 정보 ---
    MQTT_BROKER_HOST: str = os.getenv("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    MQTT_USERNAME: str | None = os.getenv("MQTT_USERNAME") or None
    MQTT_PASSWORD: str | None = os.getenv("MQTT_PASSWORD") or None

    # --- 가전 / 화구 식별자 (화구 1개로 확정) ---
    INDUCTION_DEVICE_ID: str = os.getenv("INDUCTION_DEVICE_ID", "induction-01")
    BURNER_ID: str = os.getenv("BURNER_ID", "burner-1")
    KITCHEN_ROOM: str = os.getenv("KITCHEN_ROOM", "kitchen")

    # --- MQTT 토픽 규칙 ---
    # 토픽명은 기존 그대로 유지하기로 팀에서 확정함 (변경 없음)
    STATE_TOPIC_TEMPLATE: str = "home/kitchen/induction/{device_id}/state"       # = telemetry
    COMMAND_TOPIC_TEMPLATE: str = "home/kitchen/induction/{device_id}/command"
    ACK_TOPIC_TEMPLATE: str = "home/kitchen/induction/{device_id}/ack"           # 신규: 명령 처리 결과 보고

    def state_topic(self, device_id: str | None = None) -> str:
        return self.STATE_TOPIC_TEMPLATE.format(device_id=device_id or self.INDUCTION_DEVICE_ID)

    def command_topic(self, device_id: str | None = None) -> str:
        return self.COMMAND_TOPIC_TEMPLATE.format(device_id=device_id or self.INDUCTION_DEVICE_ID)

    def ack_topic(self, device_id: str | None = None) -> str:
        return self.ACK_TOPIC_TEMPLATE.format(device_id=device_id or self.INDUCTION_DEVICE_ID)

    def state_topic_wildcard(self) -> str:
        return self.STATE_TOPIC_TEMPLATE.format(device_id="+")

    def ack_topic_wildcard(self) -> str:
        return self.ACK_TOPIC_TEMPLATE.format(device_id="+")

    # --- 부재중 안전 정책 기본값 (GET/PUT /policies/kitchen-absence 초기값) ---
    # 과열 진입 150°C / 해제 60°C 는 팀 논의로 확정된 값.
    DEFAULT_POLICY: dict = {
        "watchAfterSec": 60,
        "reduceAfterSec": 180,
        "offAfterSec": 600,
        "reduceToLevel": 1,
        "minConfidence": 0.7,
        "nearZoneMultiplier": 2.0,
        "overheatEnterC": 150.0,
        "overheatExitC": 60.0,
        "heartbeatTimeoutSec": 15,
    }

    # --- 낙상 사고 안전 정책 기본값 (GET/PUT /policies/fall-safety 초기값) ---
    # autoReportSec: 확인 링크를 누르지 않았을 때 자동으로 "신고" 처리하기까지의 대기 시간.
    # 테스트 중에는 1분(60초)으로 짧게 두고, 실제 운영 값은 팀 논의 후 늘릴 예정.
    DEFAULT_FALL_POLICY: dict = {
        "autoReportSec": 60,
    }

    # --- 보호자 SMS 발송 (네이버 클라우드 플랫폼 SENS) ---
    # NCP 콘솔에서 발급받기 전까지는 비워둬도 서버는 정상 동작하고,
    # 실제 발송 대신 로그만 남깁니다 (app/sms_service.py 참고).
    NAVER_SENS_SERVICE_ID: str = os.getenv("NAVER_SENS_SERVICE_ID", "")
    NAVER_SENS_ACCESS_KEY: str = os.getenv("NAVER_SENS_ACCESS_KEY", "")
    NAVER_SENS_SECRET_KEY: str = os.getenv("NAVER_SENS_SECRET_KEY", "")
    NAVER_SENS_SENDER_PHONE: str = os.getenv("NAVER_SENS_SENDER_PHONE", "")

    # --- SMS에 담을 확인 링크의 기준 URL (프론트가 만드는 모바일 확인 페이지) ---
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

    API_PREFIX: str = "/api/v1"


settings = Settings()
