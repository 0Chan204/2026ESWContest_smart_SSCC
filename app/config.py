"""
프로젝트 전역 설정값을 한 곳에서 관리하는 모듈입니다.

v0.2 변경사항 (프론트/임베디드 팀과 API 명세 확정 반영):
- 화구 개수를 2개(element_1/2) -> 1개(burners[0])로 축소
- MQTT ack 토픽 추가 (가전이 명령 처리 결과를 별도로 보고)
- 부재중 안전 정책 기본값(과열 150°C 진입 / 60°C 해제 등) 추가
- "오프라인 판정"은 별도 heartbeat 메시지 없이, 상태(telemetry) 토픽이
  일정 시간(HEARTBEAT_TIMEOUT_SEC) 이상 안 오면 offline으로 봄 (팀 결정)

v0.2.1 추가 (낙상 사고 안전 기능):
- 보호자 SMS 발송: 솔라피(SOLAPI) 사용 (네이버 SENS는 사업자 계정 전용이라 변경)
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

    # --- 인덕션 외 가전 목록 (v0.3: 전등·정수기 추가) ---
    # 비워 두면 기본값(시연용 전등 1개 + 정수기 1개, app/device_registry.py)을 씁니다.
    # 바꾸려면 .env에 JSON 배열로 넣습니다. 예)
    # HOMEVIS_DEVICES=[{"deviceId":"light-01","type":"light","room":"room"},{"deviceId":"water-01","type":"water_purifier","room":"kitchen"}]
    HOMEVIS_DEVICES: str = os.getenv("HOMEVIS_DEVICES", "")
    # 전등 깜빡임(blink) 명령에 시간이 없을 때 쓰는 기본 깜빡임 시간(초)
    LIGHT_BLINK_SEC: int = int(os.getenv("LIGHT_BLINK_SEC", "10"))

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
    # userAlertWaitSec: 사용자 본인(1차)이 응답하지 않을 때 보호자(2차)에게 넘기기까지의 대기 시간.
    # autoReportSec: 보호자 알림 뒤에도 응답이 없을 때 자동으로 "신고"(3차) 처리하기까지의 대기 시간.
    # 테스트 중에는 짧게 두고, 실제 운영 값은 팀 논의 후 늘릴 예정.
    DEFAULT_FALL_POLICY: dict = {
        "userAlertWaitSec": 30,
        "autoReportSec": 60,
    }

    # --- 문자 발송 (솔라피 SOLAPI) ---
    # 네이버 SENS는 사업자 계정 전용이라 개인도 쓸 수 있는 솔라피로 변경했습니다.
    # 값이 비어 있어도 서버는 정상 동작하고, 실제 발송 대신 로그만 남깁니다 (app/sms_service.py 참고).
    SOLAPI_API_KEY: str = os.getenv("SOLAPI_API_KEY", "")
    SOLAPI_API_SECRET: str = os.getenv("SOLAPI_API_SECRET", "")
    SOLAPI_SENDER_PHONE: str = os.getenv("SOLAPI_SENDER_PHONE", "")

    # --- 데이터베이스 (MongoDB Atlas) ---
    # MONGODB_URI가 비어 있으면 DB 없이 메모리로만 동작합니다 (app/db.py 참고).
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    MONGODB_DB: str = os.getenv("MONGODB_DB", "homevis")
    # 인덕션 상태 로그(3초마다 쌓임) 보관 기간. 지나면 MongoDB가 자동으로 지웁니다.
    TELEMETRY_LOG_TTL_DAYS: int = int(os.getenv("TELEMETRY_LOG_TTL_DAYS", "7"))

    # --- 날씨 안내 (v0.3.2, Open-Meteo: API 키 불필요) ---
    # 대회장 인터넷이 불안정하므로 요청이 올 때 받지 않고, WEATHER_REFRESH_SEC마다 미리 받아 캐시합니다.
    # WEATHER_ENABLED=false면 날씨를 받으러 나가지 않습니다 (마지막으로 저장된 값만 사용).
    WEATHER_ENABLED: bool = os.getenv("WEATHER_ENABLED", "true").lower() in ("1", "true", "yes")
    WEATHER_LOCATION_NAME: str = os.getenv("WEATHER_LOCATION_NAME", "서울")
    WEATHER_LAT: float = float(os.getenv("WEATHER_LAT", "37.5665"))
    WEATHER_LON: float = float(os.getenv("WEATHER_LON", "126.9780"))
    WEATHER_REFRESH_SEC: int = int(os.getenv("WEATHER_REFRESH_SEC", "1800"))
    # 가져오기에 실패했을 때 다시 시도하는 간격(초)
    WEATHER_RETRY_SEC: int = int(os.getenv("WEATHER_RETRY_SEC", "300"))
    # 이 시간(초)보다 오래된 날씨로 안내할 때는 "몇 시 기준"을 문장에 붙입니다.
    WEATHER_STALE_SEC: int = int(os.getenv("WEATHER_STALE_SEC", "3600"))
    WEATHER_TIMEOUT_SEC: float = float(os.getenv("WEATHER_TIMEOUT_SEC", "5"))

    # --- SMS에 담을 확인 링크의 기준 URL (프론트가 만드는 모바일 확인 페이지) ---
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

    API_PREFIX: str = "/api/v1"


settings = Settings()
