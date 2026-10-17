"""
엣지 노드(라즈베리파이) 메시지를 합쳐 전달하고, 최종 재실 판단 결과를 저장하는 서비스입니다. (v0.4)

흐름 (docs/EDGE-MQTT.md):
1) 노드 -> 서버: home/{구역}/edge/{노드ID}/{occupancy|activity|status}
   handle_node_message()가 구역별 최신 메시지를 맵(dict)에 덮어씁니다.
2) 서버 -> 재실 판단 담당: home/edge/combined
   run_combined_loop()가 EDGE_COMBINED_INTERVAL_SEC(기본 1초)마다 맵 전체를 한 메시지로 보냅니다.
3) 재실 판단 담당 -> 서버: home/edge/result
   handle_result()가 형식만 검사하고 DB에 저장한 뒤 대시보드에 알립니다.
4) AI 중앙 판정 엔진은 GET /api/v1/sensing/results/latest 등으로 꺼내 씁니다.

서버는 값을 판단하지 않습니다. 유효기간, 노드 이상, 온라인 여부 판단은 받는 쪽(재실 판단 담당,
AI 중앙 판정 엔진)이 합니다. 서버가 하는 일은 원본 그대로 전달 + 수신 시각(receivedAt) 추가,
그리고 QoS 1 때문에 같은 메시지가 두 번 오는 경우를 거르는 것뿐입니다.
"""

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from app import state_store, ws_hub
from app.config import settings
from app.schemas import SensingResult, SensingResultIn

logger = logging.getLogger("induction.edge")

NODE_KINDS = ("occupancy", "activity", "status")

_lock = threading.Lock()
# 구역 -> {"node": 노드ID, "occupancy": {...}, "activity": {...}, "status": {...}}
_rooms: dict[str, dict] = {}
# (구역, 노드ID, 종류) -> (bootId, seq): 중복 수신 거르기용
_last_seq: dict[tuple[str, str, str], tuple[str, int]] = {}
_combined_seq = 0


def _now_iso(precision: str = "milliseconds") -> str:
    return datetime.now(timezone.utc).isoformat(timespec=precision)


def _known_rooms() -> list[str]:
    return [r.strip() for r in settings.EDGE_ROOMS.split(",") if r.strip()]


def _empty_room() -> dict:
    return {"node": None, **{kind: None for kind in NODE_KINDS}}


def reset() -> None:
    """메모리를 비웁니다 (테스트용)"""
    global _combined_seq
    with _lock:
        _rooms.clear()
        _last_seq.clear()
        _combined_seq = 0


# ---------------------------------------------------------------------------
# 1) 노드 메시지 받기
# ---------------------------------------------------------------------------

def parse_node_topic(topic: str) -> Optional[tuple[str, str, str]]:
    """'home/kitchen/edge/edge-02/occupancy' -> ('kitchen', 'edge-02', 'occupancy'). 규칙에 안 맞으면 None"""
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "home" or parts[2] != "edge" or parts[4] not in NODE_KINDS:
        return None
    if not parts[1] or not parts[3]:
        return None
    return parts[1], parts[3], parts[4]


def _is_duplicate(key: tuple[str, str, str], message: dict) -> bool:
    """같은 bootId 안에서 이미 받은 seq 이하면 중복(또는 늦게 도착한 옛 메시지)으로 봅니다.
    bootId / seq가 없는 메시지(status 등)는 거르지 않습니다."""
    boot_id, seq = message.get("bootId"), message.get("seq")
    if not isinstance(boot_id, str) or not isinstance(seq, int) or isinstance(seq, bool):
        return False
    last = _last_seq.get(key)
    if last is not None and last[0] == boot_id and seq <= last[1]:
        return True
    _last_seq[key] = (boot_id, seq)
    return False


def handle_node_message(room: str, node: str, kind: str, raw_payload: bytes) -> bool:
    """맵에 반영했으면 True. JSON이 아니거나 중복이면 False"""
    try:
        message = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("엣지 노드 메시지가 JSON이 아니라 무시합니다 (%s/%s/%s): %s", room, node, kind, exc)
        return False
    if not isinstance(message, dict):
        logger.warning("엣지 노드 메시지가 JSON 객체가 아니라 무시합니다 (%s/%s/%s)", room, node, kind)
        return False

    with _lock:
        if _is_duplicate((room, node, kind), message):
            return False
        entry = _rooms.setdefault(room, _empty_room())
        entry["node"] = node
        entry[kind] = {"receivedAt": _now_iso(), "message": message}
    return True


# ---------------------------------------------------------------------------
# 2) 합쳐서 보내기
# ---------------------------------------------------------------------------

def build_combined(advance_seq: bool = True) -> dict:
    """구역별 최신 메시지를 하나로 합칩니다. 한 번도 못 받은 칸은 null.
    advance_seq=False면 순번을 올리지 않습니다 (미리보기용: 발행되는 seq가 건너뛰지 않도록)"""
    global _combined_seq
    with _lock:
        if advance_seq:
            _combined_seq += 1
        rooms = {room: _empty_room() for room in _known_rooms()}
        for room, entry in _rooms.items():
            rooms[room] = {key: (dict(value) if isinstance(value, dict) else value) for key, value in entry.items()}
        return {"seq": _combined_seq, "publishedAt": _now_iso(), "rooms": rooms}


def publish_combined() -> dict:
    from app import mqtt_client  # 지연 import: 순환 참조 방지

    combined = build_combined()
    mqtt_client.publish_json(settings.EDGE_COMBINED_TOPIC, combined)
    return combined


async def run_combined_loop() -> None:
    """서버가 켜져 있는 동안 정해진 간격으로 합친 메시지를 보냅니다."""
    while True:
        try:
            publish_combined()
        except Exception:
            logger.exception("합친 엣지 메시지 발행 실패 (다음 주기에 다시 시도)")
        await asyncio.sleep(settings.EDGE_COMBINED_INTERVAL_SEC)


# ---------------------------------------------------------------------------
# 3) 최종 판단 결과 받기
# ---------------------------------------------------------------------------

def handle_result(raw_payload: bytes) -> Optional[SensingResult]:
    """형식이 맞으면 저장하고 돌려줍니다. 형식이 틀리거나 이미 받은 resultId면 None"""
    try:
        body = json.loads(raw_payload.decode("utf-8"))
        incoming = SensingResultIn.model_validate(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("최종 판단 결과 형식이 맞지 않아 저장하지 않습니다: %s", exc)
        return None

    data = incoming.model_dump()
    data["resultId"] = incoming.resultId or f"res-{uuid.uuid4().hex[:12]}"
    data["savedAt"] = _now_iso()
    result = SensingResult.model_validate(data)

    if not state_store.save_sensing_result(result):
        logger.info("이미 받은 최종 판단 결과라 건너뜁니다 (resultId=%s)", result.resultId)
        return None
    ws_hub.broadcast_threadsafe("sensing.result", result.model_dump())
    return result


# ---------------------------------------------------------------------------
# 4) 조회
# ---------------------------------------------------------------------------

def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def query_results(since: Optional[str] = None, until: Optional[str] = None, limit: int = 500) -> tuple[list[SensingResult], int]:
    """observedAt이 [since, until] 안에 드는 결과 중 최근 limit개 (오래된 것부터)와 전체 개수"""
    start = _parse_time(since) if since else None
    end = _parse_time(until) if until else None
    matched = []
    for result in state_store.list_sensing_results():
        observed = _parse_time(result.observedAt)
        if start is not None and observed < start:
            continue
        if end is not None and observed > end:
            continue
        matched.append(result)
    return (matched[-limit:] if limit > 0 else []), len(matched)
