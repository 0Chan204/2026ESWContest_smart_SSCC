"""
가짜 최종 재실 판단(지우님 역할) 시뮬레이터입니다.

서버가 1초마다 보내는 합친 엣지 메시지(home/edge/combined)를 받아, 아주 단순한 규칙으로
최종 결과를 만들어 home/edge/result로 보냅니다. 실제 판단 모델이 준비되기 전에
"노드 -> 서버 -> 판단 -> 서버 저장 -> 조회" 전체 흐름을 확인하는 용도입니다.

단순 규칙 (실제 모델 아님):
- 재실 확률(pOccupied)이 가장 높은 구역이 0.5 이상이면 그 구역에 있다고 봄, 아니면 아무도 없음
- 그 구역의 행동 확률(probs)에서 가장 높은 행동을 고름

사용 방법 (맥, 저장소 폴더에서):
    source venv/bin/activate
    python tests/simulate_edge_nodes.py      # 터미널 1: 가짜 엣지 노드
    python tests/simulate_fusion.py          # 터미널 2: 가짜 최종 판단
    curl localhost:8000/api/v1/sensing/results/latest
"""

import argparse
import json
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

COMBINED_TOPIC = "home/edge/combined"
RESULT_TOPIC = "home/edge/result"
THRESHOLD = 0.5


def new_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)  # paho-mqtt 2.x
    except AttributeError:
        return mqtt.Client(client_id=client_id)  # paho-mqtt 1.x


def _message(entry: dict, kind: str) -> dict:
    cell = (entry or {}).get(kind) or {}
    return cell.get("message") or {}


def decide(combined: dict) -> dict:
    best_room, best_p = None, 0.0
    for room, entry in combined.get("rooms", {}).items():
        p = _message(entry, "occupancy").get("pOccupied")
        if isinstance(p, (int, float)) and p > best_p:
            best_room, best_p = room, float(p)

    present = best_p >= THRESHOLD
    activity, activity_p = None, None
    if present:
        probs = _message(combined["rooms"][best_room], "activity").get("probs") or {}
        if probs:
            activity = max(probs, key=probs.get)
            activity_p = round(float(probs[activity]), 3)

    return {
        "resultId": f"sim-{uuid.uuid4().hex[:12]}",
        "observedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "room": best_room if present else None,
        "present": present,
        "confidence": round(best_p if present else 1.0 - best_p, 3),
        "activity": activity,
        "activityConfidence": activity_p,
        "modelVersion": "fusion-sim",
        "validSec": 5,
        "combinedSeq": combined.get("seq"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="가짜 최종 재실 판단 (docs/EDGE-MQTT.md)")
    parser.add_argument("--host", default="localhost", help="MQTT 브로커 주소 (기본 localhost)")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()

    client = new_client("fusion-sim")

    def on_connect(c, userdata, flags, rc, properties=None):
        c.subscribe(COMBINED_TOPIC, qos=1)
        print(f"[가짜 최종 판단] {args.host}:{args.port} 연결, {COMBINED_TOPIC} 구독 시작 (Ctrl+C로 종료)")

    def on_message(c, userdata, msg):
        try:
            combined = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            return
        result = decide(combined)
        c.publish(RESULT_TOPIC, json.dumps(result, ensure_ascii=False), qos=1)
        where = result["room"] or "없음"
        print(f"[가짜 최종 판단] seq={combined.get('seq')} 위치={where} 행동={result['activity']} 신뢰도={result['confidence']}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()
        print("[가짜 최종 판단] 종료")


if __name__ == "__main__":
    main()
