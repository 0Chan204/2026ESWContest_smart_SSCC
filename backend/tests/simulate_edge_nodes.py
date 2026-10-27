"""
가짜 엣지 노드(라즈베리파이) 시뮬레이터입니다.

영진님의 실제 노드 없이, docs/EDGE-MQTT.md 명세대로 특징값(features) 메시지를 MQTT로 보내 봅니다.
영진님이 메시지 형식을 확인하는 참고 코드로도 쓸 수 있습니다.

사용 방법 (맥, 저장소 폴더에서):
    source venv/bin/activate
    python tests/simulate_edge_nodes.py                    # 같은 PC의 브로커(localhost)로 전송
    python tests/simulate_edge_nodes.py --host 192.168.0.10 # 다른 PC의 브로커로 전송
    python tests/simulate_edge_nodes.py --room kitchen      # 사람이 있는 구역 (기본 kitchen)

동작:
- 노드 r3(방) / r2(부엌) / r4(화장실) 3개를 흉내 냅니다. (v0.10 지우님 문서 기준 번호)
- 재실 특성 19개(features)와 행동 특성 31개(behavior.features)를 함께 보냅니다. (v0.10)
- 토픽: home/{구역}/edge/{노드ID}/features, 1초마다 보냅니다.
- --room으로 정한 구역은 특징값이 높게(사람이 있는 것처럼), 나머지는 낮게 나옵니다.
- --activity로 그 구역의 행동 특성 값을 바꿉니다 (standing 높게 / lying 낮게, 가짜 판단 시뮬레이터용).
  (값 자체는 의미 없는 가짜 숫자입니다)
- Ctrl+C로 끄면 각 노드가 status: "stopped" 메시지를 한 번 보내고 끝납니다.
"""

import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

NODES = {"r3": "room", "r2": "kitchen", "r4": "toilet"}
FEATURE_COUNT = 19
BEHAVIOR_FEATURE_COUNT = 31
CFG = "sim00001"
BEHAVIOR_CFG = "simbeh01"
# 가짜 판단 시뮬레이터(simulate_fusion.py)가 행동 특성 평균으로 구분하는 값
ACTIVITY_CENTER = {"standing": 1.0, "sitting": 0.0, "lying": -1.0}


def topic(room: str, node: str) -> str:
    return f"home/{room}/edge/{node}/features"


def new_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)  # paho-mqtt 2.x
    except AttributeError:
        return mqtt.Client(client_id=client_id)  # paho-mqtt 1.x


def make_message(node: str, occupied: bool, status: str = "ok", activity: str = "standing") -> dict:
    center = -1.5 if occupied else -4.3
    features = [round(center + random.uniform(-1.2, 1.2), 2) for _ in range(FEATURE_COUNT)] if status == "ok" else None
    behavior_center = ACTIVITY_CENTER.get(activity, 0.0) if occupied else -3.0
    behavior_features = (
        [round(behavior_center + random.uniform(-0.3, 0.3), 3) for _ in range(BEHAVIOR_FEATURE_COUNT)] if status == "ok" else None
    )
    return {
        "v": 1,
        "node": node,
        "t_end": int(time.time()),
        "status": status,
        "features": features,
        "quality": {
            "rate_hz": round(random.uniform(25.5, 27.0), 1),
            "rssi": round(random.uniform(-55.0, -48.0), 1),
            "proc_ms": round(random.uniform(30.0, 130.0), 1),
        },
        "cfg": CFG,
        "behavior": {
            "status": status,
            "features": behavior_features,
            "rate_hz": round(random.uniform(14.0, 15.0), 1),
            "cfg": BEHAVIOR_CFG,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="가짜 엣지 노드 (docs/EDGE-MQTT.md)")
    parser.add_argument("--host", default="localhost", help="MQTT 브로커 주소 (기본 localhost)")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--room", default="kitchen", choices=sorted(set(NODES.values())), help="사람이 있는 구역")
    parser.add_argument("--activity", default="standing", choices=sorted(ACTIVITY_CENTER), help="그 구역 사람의 행동 (가짜)")
    args = parser.parse_args()

    client = new_client("edge-nodes-sim")
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()
    print(f"[가짜 엣지 노드] {args.host}:{args.port} 에 연결. 사람이 있는 구역: {args.room} (Ctrl+C로 종료)")

    tick = 0
    try:
        while True:
            for node, room in NODES.items():
                message = make_message(node, occupied=(room == args.room), activity=args.activity)
                client.publish(topic(room, node), json.dumps(message), qos=1)
            tick += 1
            if tick % 10 == 0:
                print(f"[가짜 엣지 노드] {tick}초 경과, 전송 중...")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        time.sleep(1)  # t_end가 직전 메시지와 겹치지 않도록
        for node, room in NODES.items():
            client.publish(topic(room, node), json.dumps(make_message(node, False, status="stopped")), qos=1)
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()
        print("[가짜 엣지 노드] 종료 (status: stopped 전송)")


if __name__ == "__main__":
    main()
