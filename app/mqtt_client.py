"""
MQTT 통신을 담당하는 모듈입니다.

- 가전(인덕션) --publish(telemetry)--> [Mosquitto] --전달--> 서버(subscribe)
- 가전(인덕션) --publish(ack)-------->  [Mosquitto] --전달--> 서버(subscribe)   (v0.2 신규)
- 서버 --publish(제어명령)-----------> [Mosquitto] --전달--> 가전(subscribe)

즉 서버는 telemetry/ack 토픽에는 "구독자", command 토픽에는 "발행자" 역할을 합니다.
"""

import json
import logging

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from app.config import settings
from app.schemas import AckReport, TelemetryReport

logger = logging.getLogger("induction.mqtt")

_client = mqtt.Client(client_id="induction-backend")


def _extract_device_id(topic: str) -> str | None:
    """"home/kitchen/induction/induction-01/state" 형태에서 "induction-01"만 뽑아냅니다."""
    parts = topic.split("/")
    if len(parts) < 2:
        return None
    return parts[-2]


def _on_connect(client: mqtt.Client, userdata, flags, rc: int) -> None:
    if rc != 0:
        logger.error("MQTT 브로커 연결 실패 (rc=%s)", rc)
        return

    logger.info("MQTT 브로커 연결 성공: %s:%s", settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT)

    state_topic = settings.state_topic_wildcard()
    client.subscribe(state_topic, qos=1)
    logger.info("상태(telemetry) 토픽 구독 시작: %s", state_topic)

    ack_topic = settings.ack_topic_wildcard()
    client.subscribe(ack_topic, qos=1)
    logger.info("ack 토픽 구독 시작: %s", ack_topic)


def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    # 지연 import: device_service가 commands_service/safety_service를 거쳐
    # 다시 mqtt_client를 참조할 수 있으므로, 순환 참조를 피하기 위해 호출 시점에 import합니다.
    from app import device_service

    device_id = _extract_device_id(msg.topic)
    if device_id is None:
        logger.warning("device_id를 알 수 없는 토픽에서 메시지 수신: %s", msg.topic)
        return

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("JSON 파싱 실패 (topic=%s): %s", msg.topic, exc)
        return

    if msg.topic.endswith("/ack"):
        try:
            ack = AckReport.model_validate(payload)
        except ValidationError as exc:
            logger.error("잘못된 형식의 ack 메시지 무시 (device=%s): %s", device_id, exc)
            return
        logger.info("ack 수신 (device=%s) commandId=%s result=%s", device_id, ack.commandId, ack.result)
        device_service.handle_ack(device_id, ack)
        return

    if msg.topic.endswith("/state"):
        try:
            report = TelemetryReport.model_validate(payload)
        except ValidationError as exc:
            logger.error("잘못된 형식의 telemetry 메시지 무시 (device=%s): %s", device_id, exc)
            return
        burners_desc = ", ".join(f"{b.burnerId}={b.deviceState}({b.temperature:.1f}℃)" for b in report.burners)
        logger.info("telemetry 갱신 (device=%s) %s alarm=%s", device_id, burners_desc, report.alarm)
        device_service.handle_telemetry(device_id, report)
        return

    logger.warning("처리 규칙이 없는 토픽 수신: %s", msg.topic)


_client.on_connect = _on_connect
_client.on_message = _on_message


def start() -> None:
    if settings.MQTT_USERNAME:
        _client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

    _client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    _client.loop_start()


def stop() -> None:
    _client.loop_stop()
    _client.disconnect()


def publish_command(device_id: str, payload: dict) -> None:
    """제어 명령을 해당 가전의 command 토픽으로 발행합니다."""
    topic = settings.command_topic(device_id)
    message = json.dumps(payload, ensure_ascii=False)
    result = _client.publish(topic, message, qos=1)
    logger.info("제어 명령 발행 (topic=%s): %s", topic, message)
    result.wait_for_publish(timeout=5)
