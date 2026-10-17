"""
엣지 노드 메시지 합치기(v0.4.2 형식)와 최종 재실 판단 결과 저장·조회(v0.4)를 검증하는 테스트입니다.
실제 MQTT 브로커 없이, 메시지 처리 함수를 직접 호출합니다.
"""

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, edge_service, state_store
from app.config import settings

PREFIX = settings.API_PREFIX


def _node(room: str, node: str, message, kind: str = "features") -> bool:
    raw = message if isinstance(message, bytes) else json.dumps(message).encode("utf-8")
    return edge_service.handle_node_message(room, node, kind, raw)


def _features(node: str = "r2", t_end: int = 1792215837, status: str = "ok", base: float = -2.0) -> dict:
    """영진님 노드가 보내는 메시지 형식 (지우님이 요청한 형식의 node 칸과 같음)"""
    return {
        "v": 1,
        "node": node,
        "t_end": t_end,
        "status": status,
        "features": [base] * 19,
        "quality": {"rate_hz": 26.4, "rssi": -49.8, "proc_ms": 121.6},
        "cfg": "67a75326",
    }


def _result(result_id: str | None = "res-1", observed: str = "2026-10-17T12:00:02+00:00", **extra) -> bytes:
    body = {"observedAt": observed, "room": "kitchen", "present": True, "confidence": 0.91, **extra}
    if result_id is not None:
        body["resultId"] = result_id
    return json.dumps(body).encode("utf-8")


# ---------------------------------------------------------------------------
# 토픽 해석
# ---------------------------------------------------------------------------

def test_parse_node_topic():
    assert edge_service.parse_node_topic("home/kitchen/edge/r2/features") == ("kitchen", "r2", "features")
    assert edge_service.parse_node_topic("home/room/edge/r3/features") == ("room", "r3", "features")
    # 규칙에 안 맞는 토픽
    assert edge_service.parse_node_topic("home/kitchen/light/light-01/state") is None
    assert edge_service.parse_node_topic("home/kitchen/edge/r2") is None
    assert edge_service.parse_node_topic(settings.EDGE_COMBINED_TOPIC) is None
    assert edge_service.parse_node_topic(settings.EDGE_RESULT_TOPIC) is None


# ---------------------------------------------------------------------------
# 합치기 (지우님 요청 형식: locations.{구역}.node)
# ---------------------------------------------------------------------------

def test_combined_format_matches_request():
    combined = edge_service.build_combined()
    assert set(combined) == {"seq", "publishedAt", "locations"}
    assert combined["locations"] == {"room": {"node": None}, "kitchen": {"node": None}, "toilet": {"node": None}}


def test_combined_keeps_latest_original_message():
    _node("kitchen", "r2", _features("r2", t_end=100, base=-4.0))
    _node("kitchen", "r2", _features("r2", t_end=101, base=-1.0))
    _node("room", "r3", _features("r3", t_end=100))

    locations = edge_service.build_combined()["locations"]
    assert locations["kitchen"] == {"node": _features("r2", t_end=101, base=-1.0)}  # 원본 그대로, 최신값
    assert locations["room"]["node"]["node"] == "r3"
    assert locations["toilet"] == {"node": None}


def test_combined_seq_increases():
    first = edge_service.build_combined()["seq"]
    assert edge_service.build_combined()["seq"] == first + 1


def test_duplicate_and_old_messages_are_dropped():
    assert _node("kitchen", "r2", _features("r2", t_end=200, base=-1.0)) is True
    assert _node("kitchen", "r2", _features("r2", t_end=200, base=-1.0)) is False  # QoS 1 중복
    assert _node("kitchen", "r2", _features("r2", t_end=199, base=-9.0)) is False  # 늦게 도착한 옛 메시지
    assert edge_service.build_combined()["locations"]["kitchen"]["node"]["t_end"] == 200
    # t_end가 없는 메시지는 거르지 않는다
    no_time = {"v": 1, "node": "r2", "status": "ok"}
    assert _node("kitchen", "r2", no_time) is True
    assert _node("kitchen", "r2", no_time) is True


def test_server_does_not_judge_messages():
    """status가 ok가 아니거나 품질이 나빠도 판단 없이 그대로 전달한다."""
    bad = {**_features("r4", t_end=300, status="sensor_error"), "quality": {"rate_hz": 0.0, "rssi": -99.0}}
    _node("toilet", "r4", bad)
    assert edge_service.build_combined()["locations"]["toilet"] == {"node": bad}


def test_other_topic_kinds_and_invalid_messages_are_ignored():
    assert _node("kitchen", "r2", _features("r2"), kind="status") is False
    assert _node("kitchen", "r2", b"not json") is False
    assert _node("kitchen", "r2", [1, 2, 3]) is False
    assert edge_service.build_combined()["locations"]["kitchen"] == {"node": None}


def test_new_room_appears_in_combined():
    _node("living", "r9", _features("r9"))
    assert edge_service.build_combined()["locations"]["living"]["node"]["node"] == "r9"


def test_publish_combined_sends_to_combined_topic(published_json):
    _node("kitchen", "r2", _features("r2"))
    edge_service.publish_combined()
    topic, payload = published_json[-1]
    assert topic == settings.EDGE_COMBINED_TOPIC
    assert payload["locations"]["kitchen"]["node"]["features"] == [-2.0] * 19


def test_combined_loop_runs_with_server(monkeypatch, published_json):
    from app.main import app

    monkeypatch.setattr(settings, "EDGE_COMBINED_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EDGE_COMBINED_INTERVAL_SEC", 0.05, raising=False)
    import time

    with TestClient(app):
        time.sleep(0.3)
    assert len([t for t, _ in published_json if t == settings.EDGE_COMBINED_TOPIC]) >= 2


# ---------------------------------------------------------------------------
# MQTT 수신 경로
# ---------------------------------------------------------------------------

class _Msg:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def test_mqtt_routes_edge_and_result_messages(published):
    from app import mqtt_client

    mqtt_client._on_message(None, None, _Msg("home/kitchen/edge/r2/features", json.dumps(_features("r2")).encode()))
    mqtt_client._on_message(None, None, _Msg(settings.EDGE_RESULT_TOPIC, _result("res-mqtt")))

    assert edge_service.build_combined()["locations"]["kitchen"]["node"]["node"] == "r2"
    assert state_store.get_latest_sensing_result().resultId == "res-mqtt"


# ---------------------------------------------------------------------------
# 최종 판단 결과 저장·조회
# ---------------------------------------------------------------------------

def test_result_is_saved_as_is(client):
    assert client.get(f"{PREFIX}/sensing/results/latest").status_code == 404

    saved = edge_service.handle_result(_result("res-1", activity="standing", extraField={"a": 1}))
    assert saved is not None

    body = client.get(f"{PREFIX}/sensing/results/latest").json()
    assert body["resultId"] == "res-1"
    assert (body["room"], body["present"], body["confidence"], body["activity"]) == ("kitchen", True, 0.91, "standing")
    assert body["extraField"] == {"a": 1}  # 정해지지 않은 필드도 그대로 보관
    assert "savedAt" in body
    assert "stale" not in body  # 서버는 판단하지 않는다


def test_result_without_id_gets_one():
    saved = edge_service.handle_result(_result(None))
    assert saved.resultId.startswith("res-")


def test_duplicate_result_is_saved_once():
    assert edge_service.handle_result(_result("res-dup")) is not None
    assert edge_service.handle_result(_result("res-dup")) is None
    assert len(state_store.list_sensing_results()) == 1


def test_invalid_result_is_not_saved():
    assert edge_service.handle_result(b"not json") is None
    assert edge_service.handle_result(json.dumps({"room": "kitchen"}).encode()) is None  # observedAt 없음
    assert edge_service.handle_result(json.dumps({"observedAt": "어제"}).encode()) is None
    assert edge_service.handle_result(_result("res-x", confidence=1.5)) is None
    assert state_store.list_sensing_results() == []


def test_results_by_period(client):
    for i, minute in enumerate((0, 10, 20, 30)):
        edge_service.handle_result(_result(f"res-{i}", observed=f"2026-10-17T12:{minute:02d}:00+00:00"))

    body = client.get(f"{PREFIX}/sensing/results", params={"since": "2026-10-17T12:10:00+00:00"}).json()
    assert [r["resultId"] for r in body["items"]] == ["res-1", "res-2", "res-3"]
    assert body["total"] == 3

    # 시간대가 달라도 같은 시각으로 비교 (21:20 KST = 12:20 UTC)
    body = client.get(
        f"{PREFIX}/sensing/results",
        params={"since": "2026-10-17T21:10:00+09:00", "until": "2026-10-17T21:20:00+09:00"},
    ).json()
    assert [r["resultId"] for r in body["items"]] == ["res-1", "res-2"]

    body = client.get(f"{PREFIX}/sensing/results", params={"limit": 2}).json()
    assert [r["resultId"] for r in body["items"]] == ["res-2", "res-3"]
    assert body["total"] == 4

    assert client.get(f"{PREFIX}/sensing/results", params={"since": "어제"}).status_code == 422


def test_combined_preview_api(client):
    _node("kitchen", "r2", _features("r2"))
    published_seq = edge_service.build_combined()["seq"]
    body = client.get(f"{PREFIX}/sensing/combined").json()
    assert body["locations"]["kitchen"]["node"]["node"] == "r2"
    # 미리보기는 발행 순번을 건드리지 않는다
    assert body["seq"] == published_seq
    assert edge_service.build_combined()["seq"] == published_seq + 1


def test_results_survive_restart(mongo, published):
    from app.main import app

    edge_service.handle_result(_result("res-a", observed="2026-10-17T12:00:00+00:00"))
    edge_service.handle_result(_result("res-b", observed="2026-10-17T12:00:01+00:00"))
    db.flush()
    assert mongo[db.SENSING_RESULTS].count_documents({}) == 2
    indexes = mongo[db.SENSING_RESULTS].index_information()
    ttl = [i for i in indexes.values() if "expireAfterSeconds" in i]
    assert ttl and ttl[0]["expireAfterSeconds"] == settings.SENSING_RESULT_TTL_DAYS * 24 * 3600

    state_store.reset_memory()
    with TestClient(app) as client:
        assert client.get(f"{PREFIX}/sensing/results/latest").json()["resultId"] == "res-b"
        assert client.get(f"{PREFIX}/sensing/results").json()["total"] == 2
    # 다시 켠 뒤에도 같은 resultId는 한 번만 저장
    assert edge_service.handle_result(_result("res-a")) is None


# ---------------------------------------------------------------------------
# 가짜 최종 판단 시뮬레이터의 규칙
# ---------------------------------------------------------------------------

def test_fusion_simulator_rule():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import simulate_fusion

    _node("kitchen", "r2", _features("r2", base=-1.5))
    _node("room", "r3", _features("r3", base=-4.3))
    _node("toilet", "r4", _features("r4", base=-4.4))
    result = simulate_fusion.decide(edge_service.build_combined())
    assert (result["room"], result["present"]) == ("kitchen", True)

    # status가 ok가 아닌 노드는 제외, 모두 낮으면 아무도 없음
    edge_service.reset()
    _node("kitchen", "r2", _features("r2", base=-1.5, status="sensor_error"))
    _node("room", "r3", _features("r3", base=-4.3))
    empty = simulate_fusion.decide(edge_service.build_combined())
    assert (empty["room"], empty["present"]) == (None, False)
