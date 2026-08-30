"""
MQTT 통신을 담당하는 모듈입니다.

먼저 MQTT를 처음 접한다면 이렇게 이해하면 됩니다:
- MQTT는 REST API처럼 "요청-응답"이 아니라 "발행(publish)-구독(subscribe)" 방식입니다.
- 중간에 "브로커"(여기서는 Mosquitto)라는 우체국 같은 서버가 있고,
  누구나 특정 "토픽"(우편함 주소 같은 것)에 메시지를 던져놓거나(publish),
  특정 토픽을 미리 구독(subscribe)해두면 그 토픽에 메시지가 올 때마다 자동으로 받습니다.
- 우리 구조에서는:
    가전(인덕션) --publish(상태)--> [Mosquitto 브로커] --전달--> 우리 FastAPI 서버(subscribe)
    우리 FastAPI 서버 --publish(제어명령)--> [Mosquitto 브로커] --전달--> 가전(subscribe)
  즉 우리 서버는 상태 토픽은 "구독자", 제어 토픽은 "발행자" 역할을 동시에 합니다.

paho-mqtt는 콜백(사건이 벌어지면 자동으로 불려지는 함수) 기반입니다.
- on_connect: 브로커에 연결이 성공했을 때 1번 호출됨 -> 여기서 구독을 시작합니다.
- on_message: 구독 중인 토픽으로 메시지가 도착할 때마다 호출됨 -> 여기서 상태를 저장합니다.
"""

import json
import logging

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from app.config import settings
from app.schemas import InductionStateReport
from app.state_store import save_latest_state

logger = logging.getLogger("induction.mqtt")

# 이 파이썬 프로세스 전체에서 공유할 MQTT 클라이언트 인스턴트 1개.
# main.py의 startup/shutdown 이벤트에서 connect/disconnect 합니다.
_client = mqtt.Client(client_id="induction-backend")


def _extract_device_id(topic: str) -> str | None:
    """
    "home/kitchen/induction/induction-01/state" 형태의 토픽 문자열에서
    "induction-01" 부분(device_id)만 뽑아냅니다.
    """
    parts = topic.split("/")
    # settings.STATE_TOPIC_TEMPLATE 기준으로 device_id는 뒤에서 두 번째 조각입니다.
    if len(parts) < 2:
        return None
    return parts[-2]


def _on_connect(client: mqtt.Client, userdata, flags, rc: int) -> None:
    if rc != 0:
        logger.error("MQTT 브로커 연결 실패 (rc=%s)", rc)
        return

    logger.info("MQTT 브로커 연결 성공: %s:%s", settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT)

    # 가전이 여러 대가 되어도 전부 받을 수 있도록 와일드카드(+)로 구독합니다.
    topic = settings.state_topic_wildcard()
    client.subscribe(topic, qos=1)
    logger.info("상태 토픽 구독 시작: %s", topic)


def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    device_id = _extract_device_id(msg.topic)
    if device_id is None:
        logger.warning("device_id를 알 수 없는 토픽에서 메시지 수신: %s", msg.topic)
        return

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        state = InductionStateReport.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        # 명세서와 다른 형식의 메시지가 오면 서버가 죽지 않고 로그만 남기고 무시합니다.
        logger.error("잘못된 형식의 상태 메시지 무시 (device=%s): %s", device_id, exc)
        return

    save_latest_state(device_id, state)
    logger.info(
        "상태 갱신 (device=%s) element_1=%s(%.1f℃) element_2=%s(%.1f℃) alarm=%s",
        device_id,
        state.element_1.state,
        state.element_1.temp,
        state.element_2.state,
        state.element_2.temp,
        state.alarm,
    )


_client.on_connect = _on_connect
_client.on_message = _on_message


def start() -> None:
    """FastAPI 앱 시작 시 1번 호출: 브로커에 연결하고, 백그라운드 스레드에서
    네트워크 루프를 계속 돌립니다. (loop_start는 별도 스레드를 만들어주므로
    FastAPI의 요청 처리를 막지 않습니다.)"""
    if settings.MQTT_USERNAME:
        _client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

    _client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    _client.loop_start()


def stop() -> None:
    """FastAPI 앱 종료 시 1번 호출: 연결을 깔끔하게 정리합니다."""
    _client.loop_stop()
    _client.disconnect()


def publish_command(device_id: str, payload: dict) -> None:
    """제어 명령을 해당 가전의 command 토픽으로 발행합니다."""
    topic = settings.command_topic(device_id)
    message = json.dumps(payload, ensure_ascii=False)
    result = _client.publish(topic, message, qos=1)
    logger.info("제어 명령 발행 (topic=%s): %s", topic, message)
    result.wait_for_publish(timeout=5)
