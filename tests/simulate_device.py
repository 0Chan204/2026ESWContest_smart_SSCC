"""
실제 인덕션 하드웨어(ESP32 + Pico W)가 아직 준비되지 않았을 때,
그 자리를 대신해서 MQTT로 상태를 publish하고 명령을 subscribe하는
"가짜 인덕션" 스크립트입니다.

실행 방법:
    python tests/simulate_device.py

이 스크립트를 켜두고, 다른 터미널에서 uvicorn 서버를 띄운 뒤
curl이나 FastAPI 자동 문서(/docs)로 제어 명령을 보내보면
"서버 -> MQTT -> 이 가짜 가전"으로 명령이 전달되고,
"이 가짜 가전 -> MQTT -> 서버"로 상태가 다시 갱신되는 전체 흐름을 눈으로 확인할 수 있습니다.

내부적으로 아주 단순한 온도 시뮬레이션을 합니다:
- 화구가 켜져 있으면(level > 0) 시간이 지날수록 온도가 올라갑니다.
- 화구가 꺼져 있으면 서서히 실온(약 25도)으로 식습니다.
- 온도가 150도를 넘으면 명세서 규칙대로 overheat 상태(안전 잠금)가 되고 level은 0이 됩니다.
- overheat 상태에서 온도가 60도 밑으로 내려오면 자동으로 off로 돌아옵니다. (명세서 4.3 상태 전이도 참고)
"""

import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

# app 패키지를 import하기 위해 프로젝트 루트를 sys.path에 추가합니다.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

DEVICE_ID = settings.INDUCTION_DEVICE_ID
STATE_TOPIC = settings.state_topic(DEVICE_ID)
COMMAND_TOPIC = settings.command_topic(DEVICE_ID)

ROOM_TEMP = 25.0
OVERHEAT_THRESHOLD = 150.0
OVERHEAT_RECOVER_THRESHOLD = 60.0

# 이 가짜 가전이 기억하는 자기 자신의 현재 상태
elements = {
    "element_1": {"state": "off", "temp": ROOM_TEMP, "level": 0},
    "element_2": {"state": "off", "temp": ROOM_TEMP, "level": 0},
}
last_control = {"publisher": "system", "command_id": None}
alarm = "off"
last_processed_command_id: str | None = None


def now_iso() -> str:
    import datetime

    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def step_physics(elem: dict) -> None:
    """1틱(=이 스크립트의 publish 주기)이 지날 때마다 온도를 갱신합니다."""
    if elem["state"] == "on" and elem["level"] > 0:
        elem["temp"] += elem["level"] * 1.5  # 화력이 셀수록 빨리 뜨거워짐
        if elem["temp"] >= OVERHEAT_THRESHOLD:
            elem["state"] = "overheat"
            elem["level"] = 0
            print(f"  !! 과열 감지 -> overheat 상태로 전환 (temp={elem['temp']:.1f}℃)")
    elif elem["state"] == "overheat":
        elem["temp"] -= 3.0  # 전원 꺼진 채로 식는 중
        if elem["temp"] <= OVERHEAT_RECOVER_THRESHOLD:
            elem["state"] = "off"
            print(f"  -- 온도 안정화 -> overheat에서 off로 자동 복귀 (temp={elem['temp']:.1f}℃)")
    else:  # off
        if elem["temp"] > ROOM_TEMP:
            elem["temp"] = max(ROOM_TEMP, elem["temp"] - 2.0)


def apply_control(payload: dict) -> None:
    """서버에서 받은 제어 명령(payload)을 이 가짜 가전의 상태에 반영합니다."""
    global last_control, alarm, last_processed_command_id

    command_id = payload.get("command_id")

    # 명세서 규칙: 가전은 마지막으로 처리한 command_id를 저장해서 중복 실행을 막는다.
    if command_id is not None and command_id == last_processed_command_id:
        print(f"  (중복 명령 무시: {command_id})")
        return

    applied_something = False

    for name in ("element_1", "element_2"):
        control = payload.get(name)
        if not control:
            continue

        elem = elements[name]

        if elem["state"] == "overheat" and control.get("state") == "control_on":
            print(f"  !! {name}는 overheat 상태라 control_on 명령을 무시합니다.")
            continue

        if control.get("state") == "control_on":
            elem["state"] = "on"
            applied_something = True
        elif control.get("state") == "control_off":
            elem["state"] = "off"
            elem["level"] = 0
            applied_something = True

        if control.get("level") is not None and elem["state"] != "overheat":
            elem["level"] = control["level"]
            if elem["state"] == "off":
                elem["state"] = "on"  # 명세서 규칙: control_on + level 조합 대응
            applied_something = True

    if "alarm" in payload:
        alarm = "on" if payload["alarm"] == "control_on" else "off"
        applied_something = True

    if applied_something:
        last_control = {"publisher": "api", "command_id": command_id}
        last_processed_command_id = command_id
        print(f"  -> 명령 적용 완료 (command_id={command_id})")


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
        "timestamp": now_iso(),
        "element_1": elements["element_1"],
        "element_2": elements["element_2"],
        "last_control": last_control,
        "alarm": alarm,
    }


def main() -> None:
    client = mqtt.Client(client_id=f"induction-simulator-{DEVICE_ID}")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    client.loop_start()

    print(f"[가짜 인덕션] {STATE_TOPIC} 로 3초마다 상태를 publish합니다. (Ctrl+C로 종료)")
    try:
        while True:
            for elem in elements.values():
                step_physics(elem)

            payload = build_state_payload()
            client.publish(STATE_TOPIC, json.dumps(payload, ensure_ascii=False), qos=1)
            print(
                f"[가짜 인덕션] state 발행: element_1={elements['element_1']} "
                f"element_2={elements['element_2']} alarm={alarm}"
            )
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n[가짜 인덕션] 종료합니다.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
