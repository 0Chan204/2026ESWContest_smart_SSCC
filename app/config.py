"""
프로젝트 전역 설정값을 한 곳에서 관리하는 모듈입니다.

FastAPI 프로젝트를 처음 시작할 때 가장 먼저 만들어두면 좋은 파일 중 하나입니다.
"MQTT 브로커 주소가 어디였지?", "토픽 이름이 뭐였지?" 를 코드 여기저기에
하드코딩하면 나중에 값 하나 바꿀 때 모든 파일을 뒤져야 합니다.
그래서 이렇게 한 군데에 모아두고, 다른 파일에서는 이 모듈을 import해서 씁니다.
"""

import os
from dotenv import load_dotenv

# .env 파일이 있으면 그 안의 값을 환경변수로 읽어옵니다.
# (.env 파일이 없어도 에러가 나지 않고, 아래 기본값들이 그대로 사용됩니다.)
load_dotenv()


class Settings:
    # --- MQTT 브로커 접속 정보 ---
    MQTT_BROKER_HOST: str = os.getenv("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    MQTT_USERNAME: str | None = os.getenv("MQTT_USERNAME") or None
    MQTT_PASSWORD: str | None = os.getenv("MQTT_PASSWORD") or None

    # --- 이번에 다루는 인덕션 가전의 식별자 ---
    # 나중에 가전이 여러 대가 되면, 이 값 대신 DB에 등록된 device_id 목록을 순회하게 됩니다.
    INDUCTION_DEVICE_ID: str = os.getenv("INDUCTION_DEVICE_ID", "induction-01")

    # --- MQTT 토픽 규칙 ---
    # {device_id} 자리에 실제 가전 ID가 들어갑니다.
    # 예: home/kitchen/induction/induction-01/state
    STATE_TOPIC_TEMPLATE: str = "home/kitchen/induction/{device_id}/state"
    COMMAND_TOPIC_TEMPLATE: str = "home/kitchen/induction/{device_id}/command"

    def state_topic(self, device_id: str | None = None) -> str:
        return self.STATE_TOPIC_TEMPLATE.format(device_id=device_id or self.INDUCTION_DEVICE_ID)

    def command_topic(self, device_id: str | None = None) -> str:
        return self.COMMAND_TOPIC_TEMPLATE.format(device_id=device_id or self.INDUCTION_DEVICE_ID)

    def state_topic_wildcard(self) -> str:
        # 가전이 여러 대일 때 전부 구독하기 위한 와일드카드 토픽
        return self.STATE_TOPIC_TEMPLATE.format(device_id="+")


# 다른 파일에서는 "from app.config import settings" 로 가져다 씁니다.
settings = Settings()
