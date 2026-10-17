"""
가짜 엣지 노드(라즈베리파이) 시뮬레이터입니다.

영진님의 실제 노드 없이, docs/EDGE-MQTT.md 명세대로 재실(occupancy)·행동(activity)·상태(status)
메시지를 MQTT로 보내 봅니다. 영진님이 메시지 형식을 확인하는 참고 코드로도 쓸 수 있습니다.

사용 방법 (맥, 저장소 폴더에서):
    source venv/bin/activate
    python tests/simulate_edge_nodes.py                    # 같은 PC의 브로커(localhost)로 전송
    python tests/simulate_edge_nodes.py --host 192.168.0.10 # 다른 PC의 브로커로 전송
    python tests/simulate_edge_nodes.py --room kitchen      # 사람이 있는 구역 (기본 kitchen)

동작:
- 노드 edge-01(방) / edge-02(부엌) / edge-03(화장실) 3개를 흉내 냅니다.
- 토픽: home/{구역}/edge/{노드ID}/{occupancy|activity|status}
- --room으로 정한 구역은 재실 확률이 높고, 나머지는 낮게 보냅니다.
- occupancy 2초, activity 4초, status 5초마다 보냅니다.
- Ctrl+C로 끄면 status에 online:false를 보내고 끝납니다.
  (비정상 종료 테스트: 터미널 창을 그냥 닫으면 약 45초 안에 브로커가 Last Will(online:false)을 대신 보냅니다)
"""

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

NODES = {"edge-01": "room", "edge-02": "kitchen", "edge-03": "toilet"}
ACTIVITIES = ("standing", "walking", "sitting", "lying")
VALID_SEC = 5


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def now() -> datetime:
    return datetime.now(timezone.utc)


def topic(room: str, node: str, kind: str) -> str:
    return f"home/{room}/edge/{node}/{kind}"


def new_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)  # paho-mqtt 2.x
    except AttributeError:
        return mqtt.Client(client_id=client_id)  # paho-mqtt 1.x


class FakeNode:
    def __init__(self, node: str, room: str, host: str, port: int):
        self.node = node
        self.room = room
        self.boot_id = uuid.uuid4().hex[:8]
        self.seq = {"occupancy": 0, "activity": 0}
        self.client = new_client(f"{node}-sim")
        self.client.will_set(
            topic(room, node, "status"),
            json.dumps({"node": node, "room": room, "online": False}),
            qos=1,
            retain=True,
        )
        self.client.connect(host, port, keepalive=30)
        self.client.loop_start()
        self.last_csi = now()
        self.last_analysis = now()

    def _common(self) -> dict:
        return {"node": self.node, "room": self.room, "bootId": self.boot_id, "sentAt": iso(now())}

    def _publish(self, kind: str, payload: dict, retain: bool = False) -> None:
        self.client.publish(topic(self.room, self.node, kind), json.dumps(payload, ensure_ascii=False), qos=1, retain=retain)

    def send_occupancy(self, occupied: bool) -> None:
        self.seq["occupancy"] += 1
        end = now()
        self.last_csi = self.last_analysis = end
        p = random.uniform(0.80, 0.97) if occupied else random.uniform(0.02, 0.15)
        self._publish(
            "occupancy",
            {
                **self._common(),
                "seq": self.seq["occupancy"],
                "windowStart": iso(end - timedelta(seconds=2)),
                "windowEnd": iso(end),
                "pOccupied": round(p, 3),
                "quality": round(random.uniform(0.85, 0.99), 3),
                "modelVersion": "occ-sim",
                "validSec": VALID_SEC,
            },
        )

    def send_activity(self, occupied: bool) -> None:
        self.seq["activity"] += 1
        end = now()
        if occupied:
            main = random.choice(ACTIVITIES)
            raw = {a: (random.uniform(0.6, 0.8) if a == main else random.uniform(0.0, 0.15)) for a in ACTIVITIES}
        else:
            raw = {a: random.uniform(0.0, 0.3) for a in ACTIVITIES}
        total = sum(raw.values())
        probs = {a: round(v / total, 3) for a, v in raw.items()}
        self._publish(
            "activity",
            {
                **self._common(),
                "seq": self.seq["activity"],
                "windowStart": iso(end - timedelta(seconds=4)),
                "windowEnd": iso(end),
                "probs": probs,
                "quality": round(random.uniform(0.80, 0.97), 3),
                "modelVersion": "act-sim",
                "validSec": VALID_SEC,
            },
        )

    def send_status(self, online: bool = True) -> None:
        self._publish(
            "status",
            {
                **self._common(),
                "online": online,
                "lastCsiAt": iso(self.last_csi),
                "lastAnalysisAt": iso(self.last_analysis),
                "skippedWindows": 0,
            },
            retain=True,
        )

    def stop(self) -> None:
        self.send_status(online=False)
        time.sleep(0.3)
        self.client.loop_stop()
        self.client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="가짜 엣지 노드 (docs/EDGE-MQTT.md)")
    parser.add_argument("--host", default="localhost", help="MQTT 브로커 주소 (기본 localhost)")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--room", default="kitchen", choices=sorted(set(NODES.values())), help="사람이 있는 구역")
    args = parser.parse_args()

    nodes = [FakeNode(node, room, args.host, args.port) for node, room in NODES.items()]
    print(f"[가짜 엣지 노드] {args.host}:{args.port} 에 연결. 사람이 있는 구역: {args.room} (Ctrl+C로 종료)")
    for n in nodes:
        n.send_status()

    tick = 0
    try:
        while True:
            time.sleep(1)
            tick += 1
            for n in nodes:
                occupied = n.room == args.room
                if tick % 2 == 0:
                    n.send_occupancy(occupied)
                if tick % 4 == 0:
                    n.send_activity(occupied)
                if tick % 5 == 0:
                    n.send_status()
            if tick % 10 == 0:
                print(f"[가짜 엣지 노드] {tick}초 경과, 전송 중...")
    except KeyboardInterrupt:
        pass
    finally:
        for n in nodes:
            n.stop()
        print("[가짜 엣지 노드] 종료 (status online:false 전송)")


if __name__ == "__main__":
    main()
