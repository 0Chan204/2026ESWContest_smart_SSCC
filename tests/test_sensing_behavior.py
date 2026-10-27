"""
v0.10: 재실 + 행동추론 테스트입니다.

- 노드 메시지에 행동 특성(behavior)이 붙어도 서버는 그대로 합쳐 재실 판단 담당에게 넘기는지
- 최종 결과의 재실 · 행동 결과와 판단 불가 이유(presenceReason, activityReason)를 저장 · 조회하는지
- 행동 필드가 없는 예전 형식도 그대로 받는지
"""

import json

from app import edge_service
from app.config import settings
from tests.simulate_edge_nodes import NODES, make_message
from tests.simulate_fusion import decide

PREFIX = settings.API_PREFIX

NODE_WITH_BEHAVIOR = {
    "v": 1,
    "node": "r3",
    "t_end": 1793083741,
    "status": "ok",
    "features": [-2.34767] * 19,
    "quality": {"rate_hz": 14.7, "rssi": -60.6, "proc_ms": 188.4},
    "cfg": "67a75326",
    "behavior": {"status": "ok", "features": [-2.22972] * 31, "rate_hz": 14.7, "cfg": "f6ef98a2"},
}


def _result(**body) -> bytes:
    return json.dumps({"observedAt": "2026-10-27T21:00:02+09:00", **body}).encode("utf-8")


def test_node_behavior_is_forwarded_as_is():
    assert edge_service.handle_node_message("room", "r3", "features", json.dumps(NODE_WITH_BEHAVIOR).encode())
    node = edge_service.build_combined()["locations"]["room"]["node"]
    assert node == NODE_WITH_BEHAVIOR
    assert len(node["behavior"]["features"]) == 31


def test_presence_and_activity_saved_and_read(client):
    saved = edge_service.handle_result(_result(
        resultId="res-b-1", room="kitchen", present=True, confidence=0.91, presenceReason=None,
        activity="standing", activityConfidence=0.8, activityReason=None, modelVersion="fusion-0.2", validSec=5,
    ))
    assert saved is not None
    body = client.get(f"{PREFIX}/sensing/results/latest").json()
    assert (body["room"], body["present"], body["confidence"]) == ("kitchen", True, 0.91)
    assert (body["activity"], body["activityConfidence"]) == ("standing", 0.8)
    assert body["presenceReason"] is None and body["activityReason"] is None


def test_unknown_with_reasons(client):
    edge_service.handle_result(_result(
        resultId="res-b-2", room=None, present=None, confidence=None, presenceReason="warming_up",
        activity="unknown", activityConfidence=None, activityReason="gap",
    ))
    items = client.get(f"{PREFIX}/sensing/results").json()["items"]
    last = items[-1]
    assert (last["present"], last["presenceReason"]) == (None, "warming_up")
    assert (last["activity"], last["activityReason"]) == ("unknown", "gap")


def test_old_format_still_accepted(client):
    assert edge_service.handle_result(_result(resultId="res-b-3", room="room", present=True, confidence=0.7)) is not None
    body = client.get(f"{PREFIX}/sensing/results/latest").json()
    assert body["resultId"] == "res-b-3"
    assert body["activity"] is None and body["presenceReason"] is None and body["activityReason"] is None


def test_out_of_range_activity_confidence_rejected():
    assert edge_service.handle_result(_result(resultId="res-b-4", activity="lying", activityConfidence=1.5)) is None


def test_simulators_produce_new_format():
    # 노드 번호: r3 방 / r2 부엌 / r4 화장실 (v0.10)
    assert NODES == {"r3": "room", "r2": "kitchen", "r4": "toilet"}
    combined = {"seq": 1, "locations": {
        room: {"node": make_message(node, occupied=(room == "kitchen"), activity="lying")} for node, room in NODES.items()
    }}
    result = decide(combined)
    assert (result["room"], result["present"], result["activity"]) == ("kitchen", True, "lying")
    assert result["presenceReason"] is None and result["activityReason"] is None

    warming = {"seq": 2, "locations": {
        room: {"node": make_message(node, occupied=False, status="warming_up")} for node, room in NODES.items()
    }}
    result = decide(warming)
    assert (result["present"], result["presenceReason"]) == (None, "warming_up")
    assert (result["activity"], result["activityReason"]) == ("unknown", "warming_up")
