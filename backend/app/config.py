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

    # --- 인덕션 외 가전 목록 (v0.3: 전등·정수기, v0.5: 환풍기) ---
    # .env에 JSON 배열로 넣습니다. 비우면 기본 구성(app/device_registry.py DEFAULT_HOME_DEVICES)을 씁니다. 값을 넣으면 기본 구성 전체를 대신합니다.
    # HOMEVIS_DEVICES=[{"deviceId":"light-01","type":"light","room":"room"},{"deviceId":"fan-01","type":"fan","room":"kitchen"}]
    HOMEVIS_DEVICES: str = os.getenv("HOMEVIS_DEVICES", "")
    # 전등 깜빡임(blink) 명령에 시간이 없을 때 쓰는 기본 깜빡임 시간(초)
    LIGHT_BLINK_SEC: int = int(os.getenv("LIGHT_BLINK_SEC", "10"))
    # v0.5: 사람이 없을 때(power_saving) 전등을 낮출 절전 밝기(%)와, 그 밝기까지 서서히 낮추는 시간(초)
    LIGHT_SAVING_BRIGHTNESS: int = 20
    LIGHT_FADE_SEC: int = int(os.getenv("LIGHT_FADE_SEC", "3"))

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

    # --- 엣지 노드 · 최종 재실 판단 결과 (v0.4, docs/EDGE-MQTT.md) ---
    # 노드(라즈베리파이)가 보내는 토픽: home/{구역}/edge/{노드ID}/features (v0.4.2)
    # 서버는 구역별 최신 메시지를 하나로 합쳐 EDGE_COMBINED_TOPIC으로 주기적으로 보내고(재실 판단 담당 입력),
    # 재실 판단 담당이 EDGE_RESULT_TOPIC으로 보낸 최종 결과를 저장합니다. 서버는 판단하지 않습니다.
    EDGE_NODE_TOPIC: str = "home/+/edge/+/+"
    # 합칠 노드 메시지 종류 (토픽 마지막 칸). 이 외의 종류는 무시합니다.
    EDGE_NODE_KIND: str = os.getenv("EDGE_NODE_KIND", "features")
    EDGE_COMBINED_TOPIC: str = os.getenv("EDGE_COMBINED_TOPIC", "home/edge/combined")
    EDGE_RESULT_TOPIC: str = os.getenv("EDGE_RESULT_TOPIC", "home/edge/result")
    EDGE_COMBINED_ENABLED: bool = os.getenv("EDGE_COMBINED_ENABLED", "true").lower() in ("1", "true", "yes")
    EDGE_COMBINED_INTERVAL_SEC: float = float(os.getenv("EDGE_COMBINED_INTERVAL_SEC", "1"))
    # 합친 메시지에 항상 들어가는 구역 (아직 메시지가 없으면 null로 표시)
    EDGE_ROOMS: str = os.getenv("EDGE_ROOMS", "room,kitchen,toilet")
    # 최종 판단 결과 보관 기간(일). 지나면 MongoDB가 자동으로 지웁니다.
    SENSING_RESULT_TTL_DAYS: int = int(os.getenv("SENSING_RESULT_TTL_DAYS", "7"))

    # --- 음성 명령 (v0.6, docs/VOICE.md) ---
    # 대시보드가 보낸 문장을 이 토픽으로 AI 판정 엔진에 전달합니다.
    VOICE_REQUEST_TOPIC: str = os.getenv("VOICE_REQUEST_TOPIC", "home/voice/request")
    # 이 시간(초) 안에 판정 엔진의 판단이 없으면 timeout, 확인 창은 이 시간(초) 안에 답이 없으면 자동 취소
    VOICE_AI_TIMEOUT_SEC: int = int(os.getenv("VOICE_AI_TIMEOUT_SEC", "10"))
    VOICE_CONFIRM_TIMEOUT_SEC: int = int(os.getenv("VOICE_CONFIRM_TIMEOUT_SEC", "30"))
    # (v0.12) true면 음성 명령의 확인 창을 띄우지 않고 서버가 바로 승인해 실행합니다 (판정 엔진이 확인을 요청해도).
    # 인덕션 켜기·화력 조절은 안전 때문에 이 설정과 상관없이 항상 사용자 확인을 받습니다.
    VOICE_AUTO_CONFIRM: bool = os.getenv("VOICE_AUTO_CONFIRM", "false").lower() in ("1", "true", "yes")
    # 음성 문장은 개인정보라 이 기간(일)이 지나면 DB에서 자동 삭제합니다.
    VOICE_COMMAND_TTL_DAYS: int = int(os.getenv("VOICE_COMMAND_TTL_DAYS", "30"))

    # --- 보드 마이크 음성 명령 (v0.9, docs/VOICE.md 5장) ---
    # 보드에는 브라우저 음성 인식이 없어서, 서버가 보드 마이크로 녹음하고 음성 인식(STT)·음성 안내(TTS)를 합니다.
    # VOICE_LISTEN_ENABLED=false면 POST /voice/listen이 503입니다 (마이크가 없는 개발 PC 등).
    VOICE_LISTEN_ENABLED: bool = os.getenv("VOICE_LISTEN_ENABLED", "true").lower() in ("1", "true", "yes")
    # 녹음 명령(pulseaudio의 parecord). 컨테이너에서는 PULSE_SERVER=unix:/run/pulse/native 로 보드 소리 장치에 붙습니다.
    VOICE_RECORD_CMD: str = os.getenv("VOICE_RECORD_CMD", "parecord")
    # 마이크 장치 이름 (pactl list short sources). 비우면 기본 입력 장치
    VOICE_MIC_DEVICE: str = os.getenv("VOICE_MIC_DEVICE", "")
    # 버튼을 누른 뒤 이 시간(초) 안에 말소리가 없으면 no_speech
    VOICE_LISTEN_START_SEC: float = float(os.getenv("VOICE_LISTEN_START_SEC", "5"))
    # 말이 끝나고 이 시간(초) 동안 조용하면 녹음을 끝냅니다
    VOICE_LISTEN_SILENCE_SEC: float = float(os.getenv("VOICE_LISTEN_SILENCE_SEC", "1.0"))
    # 한 번에 녹음하는 최대 시간(초). 대시보드는 20초 동안 소식이 없으면 닫으므로 너무 길게 두지 않습니다.
    VOICE_LISTEN_MAX_SEC: float = float(os.getenv("VOICE_LISTEN_MAX_SEC", "8"))
    # 이 음량(RMS, 16비트 기준) 이상이면 말소리로 봅니다. 마이크·방 소음에 맞춰 조절
    VOICE_SPEECH_RMS: int = int(os.getenv("VOICE_SPEECH_RMS", "500"))

    # OpenAI 음성 인식·음성 합성 (키는 .env로만. 코드·이미지에 넣지 않음)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_STT_MODEL: str = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    OPENAI_STT_TIMEOUT_SEC: float = float(os.getenv("OPENAI_STT_TIMEOUT_SEC", "8"))
    # 인식 결과에 신뢰도 정보(logprobs)가 없을 때 쓰는 값. 판정 엔진은 0.6 미만이면 제어하지 않습니다.
    VOICE_STT_FALLBACK_CONFIDENCE: float = float(os.getenv("VOICE_STT_FALLBACK_CONFIDENCE", "0.8"))
    VOICE_TTS_ENABLED: bool = os.getenv("VOICE_TTS_ENABLED", "true").lower() in ("1", "true", "yes")
    OPENAI_TTS_MODEL: str = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    OPENAI_TTS_VOICE: str = os.getenv("OPENAI_TTS_VOICE", "alloy")
    OPENAI_TTS_TIMEOUT_SEC: float = float(os.getenv("OPENAI_TTS_TIMEOUT_SEC", "10"))
    # 재생 명령(pulseaudio의 paplay)과 스피커 장치 이름 (비우면 기본 출력 장치)
    VOICE_PLAY_CMD: str = os.getenv("VOICE_PLAY_CMD", "paplay")
    VOICE_SPEAKER_DEVICE: str = os.getenv("VOICE_SPEAKER_DEVICE", "")

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
    # 시간대별 예보를 지금 시간부터 몇 시간치 줄지 (v0.4.3)
    WEATHER_HOURLY_HOURS: int = int(os.getenv("WEATHER_HOURLY_HOURS", "12"))

    # --- SMS에 담을 확인 링크의 기준 URL (프론트가 만드는 모바일 확인 페이지) ---
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

    API_PREFIX: str = "/api/v1"


settings = Settings()
