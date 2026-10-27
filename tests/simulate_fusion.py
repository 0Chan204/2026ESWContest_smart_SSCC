"""
가짜 최종 재실 판단(지우님 역할) 시뮬레이터입니다.

서버가 1초마다 보내는 합친 엣지 메시지(home/edge/combined)를 받아, 아주 단순한 규칙으로
최종 결과를 만들어 home/edge/result로 보냅니다. 실제 판단 모델이 준비되기 전에
"노드 -> 서버 -> 판단 -> 서버 저장 -> 조회" 전체 흐름을 확인하는 용도입니다.

단순 규칙 (실제 모델 아님):
- 구역마다 특징값(features)의 평균을 구해, 가장 높은 구역이 THRESHOLD 이상이면 그 구역에 있다고 봄
- 노드 status가 "ok"가 아닌 구역은 제외. ok인 노드가 하나도 없으면 present=null + presenceReason(노드 상태)
- (v0.10) 행동: 그 구역 노드의 행동 특성(behavior.features) 평균으로 standing / sitting / lying
  행동 쪽 상태가 ok가 아니거나 사람이 없으면 activity="unknown" + activityReason

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
THRESHOLD = -3.0


def new_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)  # paho-mqtt 2.x
    except AttributeError:
        return mqtt.Client(client_id=client_id)  # paho-mqtt 1.x


def _activity(node: dict) -> tuple[str, float | None, str | None]:
    """(행동, 정확도, 판단 불가 이유)"""
    behavior = node.get("behavior") or {}
    features = behavior.get("features") or []
    if behavior.get("status") != "ok" or not features:
        return "unknown", None, behavior.get("status") or "no_behavior"
    mean = sum(features) / len(features)
    if mean >= 0.5:
        return "standing", 0.8, None
    if mean >= -0.5:
        return "sitting", 0.7, None
    return "lying", 0.75, None


def decide(combined: dict) -> dict:
    best_room, best_score, best_node = None, None, None
    statuses = []
    for room, entry in combined.get("locations", {}).items():
        node = (entry or {}).get("node") or {}
        statuses.append(node.get("status") or "no_csi")
        features = node.get("features") or []
        if node.get("status") != "ok" or not features:
            continue
        score = sum(features) / len(features)
        if best_score is None or score > best_score:
            best_room, best_score, best_node = room, score, node

    result = {
        "resultId": f"sim-{uuid.uuid4().hex[:12]}",
        "observedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "modelVersion": "fusion-sim",
        "validSec": 5,
        "combinedSeq": combined.get("seq"),
    }
    if best_score is None:
        # 판단할 노드가 없음: 재실 · 행동 모두 unknown
        reason = next((s for s in statuses if s != "ok"), "no_csi")
        return {**result, "room": None, "present": None, "confidence": None, "presenceReason": reason,
                "activity": "unknown", "activityConfidence": None, "activityReason": reason}

    present = best_score >= THRESHOLD
    if present:
        activity, activity_conf, activity_reason = _activity(best_node)
    else:
        activity, activity_conf, activity_reason = "unknown", None, "not_present"
    return {**result, "room": best_room if present else None, "present": present, "confidence": 0.9,
            "presenceReason": None, "activity": activity, "activityConfidence": activity_conf,
            "activityReason": activity_reason}


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
        where = result["room"] or ("판단 불가" if result["present"] is None else "없음")
        print(f"[가짜 최종 판단] seq={combined.get('seq')} 위치={where} 행동={result['activity']}")

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
