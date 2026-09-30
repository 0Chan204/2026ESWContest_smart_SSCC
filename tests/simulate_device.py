"""
실제 인덕션 하드웨어(ESP32 + Pico W)가 아직 준비되지 않았을 때,
그 자리를 대신해서 MQTT로 telemetry를 publish하고 command를 subscribe하는
"가짜 인덕션" 스크립트입니다. (v0.2: 화구 1개, camelCase, ack 토픽 반영)

실행 방법:
    python tests/simulate_device.py

내부적으로 아주 단순한 온도 시뮬레이션을 합니다:
- 화구가 on 이고 level > 0 이면 시간이 지날수록 온도가 올라갑니다.
- 온도가 overheatEnterC(기본 150도)를 넘으면 overheated 상태(안전 잠금)가 되고 level은 0이 됩니다.
- overheated 상태에서 온도가 overheatExitC(기본 60도) 밑으로 내려오면 자동으로 off로 복귀합니다.
- turn_off 명령을 받았을 때 아직 많이 뜨거우면(실온+5도 초과) 곧바로 off가 아니라
  "cooling"(식는 중) 상태를 거쳐 실온 근처에서 off로 바뀝니다.
- 명령을 적용한 뒤에는 MQTT ack 토픽으로 처리 결과(applied/rejected)를 보고합니다.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

DEVICE_ID = settings.INDUCTION_DEVICE_ID
BURNER_ID = settings.BURNER_ID
STATE_TOPIC = settings.state_topic(DEVICE_ID)
COMMAND_TOPIC = settings.command_topic(DEVICE_ID)
ACK_TOPIC = settings.ack_topic(DEVICE_ID)

TICK_SECONDS = 3

ROOM_TEMP = 25.0
OVERHEAT_ENTER_C = settings.DEFAULT_POLICY["overheatEnterC"]
OVERHEAT_EXIT_C = settings.DEFAULT_POLICY["overheatExitC"]

# 이 가짜 가전이 기억하는 자기 자신의 현재 상태 (화구 1개)
burner = {
    "burnerId": BURNER_ID,
    "deviceState": "off",
    "level": 0,
    "temperature": ROOM_TEMP,
    "activeSec": 0,
}
last_control = {"publisher": "system", "commandId": None}
alarm = "off"
last_processed_command_id: str | None = None

_client: mqtt.Client | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def step_physics() -> None:
    """1틱(=이 스크립트의 publish 주기)이 지날 때마다 온도/누적시간을 갱신합니다."""
    if burner["deviceState"] == "on" and burner["level"] > 0:
        burner["temperature"] += burner["level"] * 1.5
        burner["activeSec"] += TICK_SECONDS
        if burner["temperature"] >= OVERHEAT_ENTER_C:
            burner["deviceState"] = "overheated"
            burner["level"] = 0
            print(f"  !! 과열 감지 -> overheated 상태로 전환 (temp={burner['temperature']:.1f}℃)")
    elif burner["deviceState"] == "overheated":
        burner["temperature"] -= 3.0
        if burner["temperature"] <= OVERHEAT_EXIT_C:
            burner["deviceState"] = "off"
            burner["activeSec"] = 0
            print(f"  -- 온도 안정화 -> overheated에서 off로 자동 복귀 (temp={burner['temperature']:.1f}℃)")
    elif burner["deviceState"] == "cooling":
        burner["temperature"] = max(ROOM_TEMP, burner["temperature"] - 2.0)
        if burner["temperature"] <= ROOM_TEMP + 1:
            burner["deviceState"] = "off"
            print("  -- 냉각 완료 -> off")
    else:  # off
        if burner["temperature"] > ROOM_TEMP:
            burner["temperature"] = max(ROOM_TEMP, burner["temperature"] - 2.0)


def publish_ack(command_id: str | None, result: str) -> None:
    if _client is None or command_id is None:
        return
    payload = {
        "commandId": command_id,
        "result": result,
        "appliedAt": now_iso(),
        "burnerState": dict(burner),
    }
    _client.publish(ACK_TOPIC, json.dumps(payload, ensure_ascii=False), qos=1)
    print(f"  -> ack 발행 (commandId={command_id}, result={result})")


def apply_control(payload: dict) -> None:
    """서버에서 받은 제어 명령(payload)을 이 가짜 가전의 상태에 반영하고 ack를 보고합니다."""
    global last_control, alarm, last_processed_command_id

    command_id = payload.get("commandId")

    if command_id is not None and command_id == last_processed_command_id:
        print(f"  (중복 명령 무시: {command_id})")
        return

    if payload.get("burnerId") not in (None, BURNER_ID):
        print(f"  (알 수 없는 burnerId 무시: {payload.get('burnerId')})")
        return

    cmd_type = payload.get("type")
    result = "applied"

    if burner["deviceState"] == "overheated" and cmd_type in ("turn_on", "set_level"):
        print(f"  !! overheated 상태라 {cmd_type} 명령을 거부합니다.")
        result = "rejected"
    elif cmd_type == "turn_on":
        burner["deviceState"] = "on"
        if burner["level"] == 0:
            burner["level"] = 5
    elif cmd_type == "turn_off":
        burner["deviceState"] = "cooling" if burner["temperature"] > ROOM_TEMP + 5 else "off"
        burner["level"] = 0
        burner["activeSec"] = 0
    elif cmd_type == "set_level":
        level = payload.get("level") or 0
        burner["level"] = level
        if level > 0:
            burner["deviceState"] = "on"
    else:
        result = "failed"

    last_control = {"publisher": "api", "commandId": command_id}
    last_processed_command_id = command_id
    print(f"  -> 명령 적용 결과={result} (commandId={command_id}, type={cmd_type})")

    publish_ack(command_id, result)
    if result == "applied" and _client is not None:
        # 상태가 바뀐 직후 telemetry도 즉시 한 번 더 보내서 대시보드가 빠르게 반영되도록 함
        _client.publish(STATE_TOPIC, json.dumps(build_state_payload(), ensure_ascii=False), qos=1)


def on_connect(client: mqtt.Client, userdata, flags, rc: int) -> None:
    print(f"[가짜 인덕션] 브로커 연결 성공, device_id={DEVICE_ID}")
    client.subscribe(COMMAND_TOPIC, qos=1)
    print(f"[가짜 인덕션] 제어 토픽 구독: {COMMAND_TOPIC}")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    print(f"[가짜 인덕션] 제어 명령 수신: {msg.payload.decode('utf-8')}")
    payload = json.loads(msg.payload.decode("utf-8"))
    apply_control(payload)


def build_state_payload() -> dict:
    return {
        "reportedAt": now_iso(),
        "burners": [dict(burner)],
        "lastControl": last_control,
        "alarm": alarm,
    }


def main() -> None:
    global _client
    _client = mqtt.Client(client_id=f"induction-simulator-{DEVICE_ID}")
    _client.on_connect = on_connect
    _client.on_message = on_message
    _client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    _client.loop_start()

    print(f"[가짜 인덕션] {STATE_TOPIC} 로 {TICK_SECONDS}초마다 telemetry를 publish합니다. (Ctrl+C로 종료)")
    try:
        while True:
            step_physics()
            payload = build_state_payload()
            _client.publish(STATE_TOPIC, json.dumps(payload, ensure_ascii=False), qos=1)
            print(f"[가짜 인덕션] telemetry 발행: {burner} alarm={alarm}")
            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\n[가짜 인덕션] 종료합니다.")
    finally:
        _client.loop_stop()
        _client.disconnect()


if __name__ == "__main__":
    main()
