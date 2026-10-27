"""
실제 전등·정수기·환풍기가 준비되지 않았을 때 그 자리를 대신하는 "가짜 가전" 스크립트입니다. (v0.3, v0.5: 환풍기·밝기)

실행 방법:
    python tests/simulate_home_devices.py

app/device_registry.py의 가전 목록(기본: light-01, light-00, light-02, water-01, fan-01, fan-02, air-01)을 그대로 사용합니다.
- 각 기기는 5초마다, 그리고 상태가 바뀔 때마다 state 토픽으로 상태를 보냅니다.
- command 토픽으로 명령을 받으면 적용하고 ack 토픽으로 결과를 보냅니다.
  전등: on(100%) / off / blink(durationSec 동안 깜빡인 뒤 원래 상태로)
        fadeout(brightness까지 durationSec 동안 서서히 낮춤. power는 on, 다 낮추면 mode는 steady)
  정수기: dispense(amountMl만큼, 초당 50ml로 출수한 뒤 idle)
  환풍기: on(지난 풍량, 처음이면 mid) / off / set_speed(low·mid·high)
  공기청정기: on / off / set_mode(auto·manual). 미세먼지 값이 조금씩 바뀌고, auto 모드에서 나쁨(bad)이면
              스스로 켜고(publisher: system) 좋음(good)으로 돌아오면 스스로 끕니다.
"""

import json
import random
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app import device_registry  # noqa: E402
from app.config import settings  # noqa: E402

TICK_SECONDS = 5
DISPENSE_ML_PER_SEC = 50

DEVICES = [d for d in device_registry.list_devices() if d.type in device_registry.HOME_DEVICE_TYPES]
_lock = threading.Lock()
_states: dict[str, dict] = {}
_client: mqtt.Client | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initial_state(device) -> dict:
    no_control = {"publisher": "user", "commandId": None}
    if device.type == device_registry.LIGHT:
        return {"power": "off", "brightness": 0, "mode": "steady", "lastControl": no_control}
    if device.type == device_registry.FAN:
        return {"power": "off", "speed": "mid", "lastControl": no_control}
    if device.type == device_registry.AIR_PURIFIER:
        return {"power": "off", "mode": "auto", "airQuality": air_quality(20.0), "lastControl": no_control}
    return {"status": "idle", "lastDispensedMl": None, "lastControl": no_control}


def air_quality(pm25: float) -> dict:
    level = "good" if pm25 <= 15 else ("normal" if pm25 <= 35 else "bad")
    return {"pm25": round(pm25, 1), "pm10": round(pm25 * 1.6, 1), "level": level}


def drift_air(device) -> None:
    """미세먼지 값을 조금씩 바꾸고, auto 모드면 공기질에 따라 스스로 켜고 끕니다."""
    with _lock:
        state = _states[device.deviceId]
        pm25 = state["airQuality"]["pm25"]
        pm25 = pm25 - random.uniform(1, 4) if state["power"] == "on" else pm25 + random.uniform(-2, 3)
        state["airQuality"] = air_quality(max(pm25, 3.0))
        level = state["airQuality"]["level"]
        if state["mode"] == "auto" and level == "bad" and state["power"] == "off":
            state.update(power="on", lastControl={"publisher": "system", "commandId": None})
            print(f"[가짜 {device.deviceId}] 공기질 나쁨 -> 자동으로 켬")
        elif state["mode"] == "auto" and level == "good" and state["power"] == "on" and state["lastControl"]["publisher"] == "system":
            state.update(power="off", lastControl={"publisher": "system", "commandId": None})
            print(f"[가짜 {device.deviceId}] 공기질 좋음 -> 자동으로 끔")


def state_payload(device_id: str) -> dict:
    with _lock:
        return {"reportedAt": now_iso(), **_states[device_id]}


def publish_state(device) -> None:
    payload = state_payload(device.deviceId)
    _client.publish(device_registry.topic(device, "state"), json.dumps(payload, ensure_ascii=False), qos=1)


def send_ack(device, command_id: str, result: str) -> None:
    ack = {"commandId": command_id, "result": result, "appliedAt": now_iso(), "state": state_payload(device.deviceId)}
    _client.publish(device_registry.topic(device, "ack"), json.dumps(ack, ensure_ascii=False), qos=1)
    print(f"[가짜 {device.deviceId}] ack 전송: {result}")


def apply_command(device, payload: dict) -> None:
    command_id = payload.get("commandId")
    cmd_type = payload.get("type")
    control = {"publisher": "api", "commandId": command_id}
    result = "applied"

    with _lock:
        state = _states[device.deviceId]
        if device.type == device_registry.LIGHT and cmd_type in ("on", "off"):
            state.update(power=cmd_type, brightness=100 if cmd_type == "on" else 0, mode="steady", lastControl=control)
        elif device.type == device_registry.LIGHT and cmd_type == "fadeout" and state["power"] == "on":
            target = payload.get("brightness", 20)
            state.update(mode="fadeout", lastControl=control)
            threading.Timer(payload.get("durationSec") or 3, end_fadeout, args=(device, target)).start()
        elif device.type == device_registry.FAN and cmd_type in ("on", "off"):
            state.update(power=cmd_type, lastControl=control)
        elif device.type == device_registry.FAN and cmd_type == "set_speed" and payload.get("speed"):
            state.update(power="on", speed=payload["speed"], lastControl=control)
        elif device.type == device_registry.AIR_PURIFIER and cmd_type in ("on", "off"):
            state.update(power=cmd_type, lastControl=control)
        elif device.type == device_registry.AIR_PURIFIER and cmd_type == "set_mode" and payload.get("mode"):
            state.update(mode=payload["mode"], lastControl=control)
        elif device.type == device_registry.LIGHT and cmd_type == "blink":
            previous_power = state["power"]
            state.update(mode="blink", lastControl=control)
            seconds = payload.get("durationSec") or settings.LIGHT_BLINK_SEC
            threading.Timer(seconds, end_blink, args=(device, previous_power)).start()
        elif device.type == device_registry.WATER_PURIFIER and cmd_type == "dispense" and payload.get("amountMl"):
            amount = payload["amountMl"]
            state.update(status="dispensing", lastControl=control)
            threading.Timer(amount / DISPENSE_ML_PER_SEC, end_dispense, args=(device, amount)).start()
        else:
            result = "rejected"

    send_ack(device, command_id, result)
    if result == "applied":
        publish_state(device)


def end_blink(device, previous_power: str) -> None:
    with _lock:
        _states[device.deviceId].update(mode="steady", power=previous_power)
    print(f"[가짜 {device.deviceId}] 깜빡임 끝 -> {previous_power}")
    publish_state(device)


def end_fadeout(device, target: int) -> None:
    with _lock:
        _states[device.deviceId].update(brightness=target, mode="steady")
    print(f"[가짜 {device.deviceId}] 절전 밝기 {target}%로 낮춤")
    publish_state(device)


def end_dispense(device, amount: int) -> None:
    with _lock:
        _states[device.deviceId].update(status="idle", lastDispensedMl=amount)
    print(f"[가짜 {device.deviceId}] 출수 완료 {amount}ml")
    publish_state(device)


def on_connect(client: mqtt.Client, userdata, flags, rc: int) -> None:
    print(f"[가짜 가전] 브로커 연결 성공: {[d.deviceId for d in DEVICES]}")
    for device in DEVICES:
        client.subscribe(device_registry.topic(device, "command"), qos=1)
        publish_state(device)


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    parsed = device_registry.parse_topic(msg.topic)
    device = device_registry.get_device(parsed[1]) if parsed else None
    if device is None:
        return
    payload = json.loads(msg.payload.decode("utf-8"))
    print(f"[가짜 {device.deviceId}] 명령 수신: {payload}")
    apply_command(device, payload)


def main() -> None:
    global _client
    for device in DEVICES:
        _states[device.deviceId] = initial_state(device)

    _client = mqtt.Client(client_id="home-devices-simulator")
    _client.on_connect = on_connect
    _client.on_message = on_message
    if settings.MQTT_USERNAME:
        _client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
    _client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    _client.loop_start()

    try:
        while True:
            time.sleep(TICK_SECONDS)
            for device in DEVICES:
                if device.type == device_registry.AIR_PURIFIER:
                    drift_air(device)
                publish_state(device)
    except KeyboardInterrupt:
        print("\n[가짜 가전] 종료합니다.")
    finally:
        _client.loop_stop()
        _client.disconnect()


if __name__ == "__main__":
    main()
