"""
v0.6: 음성 명령 테스트입니다.

대시보드가 문장을 보내면 서버가 저장하고 판정 엔진에 MQTT로 전달하는지,
판정 엔진의 판단(voiceId)을 연결해 답변·실행·확인·취소·시간 초과가 맞게 처리되는지 확인합니다.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, mqtt_client, state_store, voice_service
from app.config import settings

PREFIX = settings.API_PREFIX
TOILET_LIGHT = "light-00"
KITCHEN_FAN = "fan-01"


@pytest.fixture()
def broadcasts(monkeypatch):
    from app import ws_hub

    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(ws_hub, "broadcast_threadsafe", lambda event, data: sent.append((event, data)))
    return sent


def _voice_events(broadcasts, voice_id):
    return [data for event, data in broadcasts if event == "voice.status" and data["voiceId"] == voice_id]


def _send_voice(client, text="욕실 조명 켜줘") -> str:
    res = client.post(
        f"{PREFIX}/voice/commands",
        json={"text": text, "lang": "ko-KR", "confidence": 0.92, "source": "voice", "recognizedAt": "2026-10-24T21:00:00+09:00"},
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "received"
    return body["voiceId"]


def _decide(client, voice_id, decision_id="dec-voice-1", actions=None, confirm=False, answer="욕실 조명을 켤게요.", room="toilet"):
    return client.post(
        f"{PREFIX}/ai/decisions",
        json={
            "decisionId": decision_id,
            "voiceId": voice_id,
            "scenario": "voice_command",
            "confidence": 0.9,
            "timestamp": "2026-10-24T21:00:02+09:00",
            "room": room,
            "announcement": answer,
            "requiresConfirmation": confirm,
            "actions": actions or [],
        },
    )


LIGHT_ON = [{"device": "light", "deviceId": TOILET_LIGHT, "action": "on"}]


# ---------------------------------------------------------------------------
# 문장 받기 -> 판정 엔진에 전달
# ---------------------------------------------------------------------------

def test_voice_command_is_saved_and_sent_to_ai(client, published_json, broadcasts):
    voice_id = _send_voice(client)

    topic, message = published_json[-1]
    assert topic == settings.VOICE_REQUEST_TOPIC == "home/voice/request"
    assert message["voiceId"] == voice_id
    assert message["text"] == "욕실 조명 켜줘"
    assert message["confidence"] == 0.92
    assert message["expiresAt"] > message["receivedAt"]

    stored = client.get(f"{PREFIX}/voice/commands/{voice_id}").json()
    assert stored["status"] == "thinking"
    assert [e["status"] for e in _voice_events(broadcasts, voice_id)] == ["thinking"]
    assert "pendingActions" not in _voice_events(broadcasts, voice_id)[0]


def test_empty_text_is_rejected(client):
    assert client.post(f"{PREFIX}/voice/commands", json={"text": "   "}).status_code == 422


def test_ai_unreachable_returns_503(client, monkeypatch, broadcasts):
    def broken(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(mqtt_client, "publish_json", broken)
    res = client.post(f"{PREFIX}/voice/commands", json={"text": "환풍기 켜줘"})
    assert res.status_code == 503
    voice_id = res.json()["detail"]["voiceId"]
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["status"] == "failed"
    assert [e["status"] for e in _voice_events(broadcasts, voice_id)] == ["failed"]


# ---------------------------------------------------------------------------
# 판정 엔진의 판단 연결
# ---------------------------------------------------------------------------

def test_answer_only(client, published, broadcasts):
    voice_id = _send_voice(client, "주방은 지금 어때?")
    res = _decide(client, voice_id, answer="주방은 지금 조리 중이에요.", room="kitchen")
    assert res.status_code == 202
    assert res.json()["voiceId"] == voice_id

    voice = client.get(f"{PREFIX}/voice/commands/{voice_id}").json()
    assert (voice["status"], voice["answer"], voice["decisionId"]) == ("answered", "주방은 지금 조리 중이에요.", "dec-voice-1")
    assert published == []
    assert _voice_events(broadcasts, voice_id)[-1]["status"] == "answered"
    # 같은 답변이 ai.announcement로도 가지만 voiceId가 있어 대시보드가 중복 재생을 거를 수 있다
    announcement = next(d for e, d in broadcasts if e == "ai.announcement")
    assert announcement["voiceId"] == voice_id


def test_refusal_is_answer_without_actions(client, published):
    voice_id = _send_voice(client, "인덕션 켜줘")
    _decide(client, voice_id, answer="안전을 위해 인덕션은 음성으로 켤 수 없어요.", room="kitchen")
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["status"] == "answered"
    assert published == []


def test_executes_right_away_without_confirmation(client, published, broadcasts):
    voice_id = _send_voice(client)
    res = _decide(client, voice_id, actions=LIGHT_ON, confirm=False).json()
    assert res["status"] == "executed"
    assert (published[-1]["deviceId"], published[-1]["type"]) == (TOILET_LIGHT, "on")

    voice = client.get(f"{PREFIX}/voice/commands/{voice_id}").json()
    assert voice["status"] == "executed"
    assert voice["actions"][0]["status"] == "sent"
    last = _voice_events(broadcasts, voice_id)[-1]
    assert (last["status"], last["answer"]) == ("executed", "욕실 조명을 켤게요.")


def test_confirmation_then_execute(client, published, broadcasts):
    voice_id = _send_voice(client)
    res = _decide(client, voice_id, actions=LIGHT_ON, confirm=True).json()
    assert res["status"] == "awaiting_confirmation"
    assert [(a["deviceId"], a["status"]) for a in res["actions"]] == [(TOILET_LIGHT, "pending")]
    assert published == []  # 확인 전에는 기기를 움직이지 않음

    voice = client.get(f"{PREFIX}/voice/commands/{voice_id}").json()
    assert voice["status"] == "confirm_required"
    assert voice["confirmText"] == "욕실 조명을 켤까요?"
    assert voice["confirmDeadline"] is not None
    assert _voice_events(broadcasts, voice_id)[-1]["confirmText"] == "욕실 조명을 켤까요?"

    confirmed = client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True})
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "executed"
    assert body["confirmedAt"] is not None
    assert body["actions"][0]["status"] == "sent"
    assert (published[-1]["deviceId"], published[-1]["type"], published[-1]["brightness"]) == (TOILET_LIGHT, "on", 100)

    decision = client.get(f"{PREFIX}/ai/decisions/dec-voice-1").json()
    assert decision["status"] == "executed"
    assert decision["actions"][0]["status"] == "sent"
    assert decision["eventId"] is not None
    assert _voice_events(broadcasts, voice_id)[-1]["status"] == "executed"

    # 이미 끝난 명령에 다시 확인하면 409
    assert client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True}).status_code == 409


def test_confirmation_cancelled(client, published, broadcasts):
    voice_id = _send_voice(client)
    _decide(client, voice_id, actions=LIGHT_ON, confirm=True)
    body = client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": False}).json()
    assert body["status"] == "cancelled"
    assert published == []
    decision = client.get(f"{PREFIX}/ai/decisions/dec-voice-1").json()
    assert decision["status"] == "cancelled"
    assert decision["actions"][0]["status"] == "cancelled"


def test_confirmation_times_out(client, published, broadcasts):
    voice_id = _send_voice(client)
    _decide(client, voice_id, actions=LIGHT_ON, confirm=True)
    voice_service.cancel_if_unconfirmed(voice_id)
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["status"] == "cancelled"
    assert _voice_events(broadcasts, voice_id)[-1]["status"] == "cancelled"
    assert client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True}).status_code == 409
    assert published == []


def test_ai_timeout_then_late_decision_is_not_executed(client, published, broadcasts):
    voice_id = _send_voice(client)
    voice_service.expire_if_waiting(voice_id)
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["status"] == "timeout"
    assert _voice_events(broadcasts, voice_id)[-1]["status"] == "timeout"

    late = _decide(client, voice_id, actions=LIGHT_ON).json()
    assert late["status"] == "expired"
    assert published == []
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["status"] == "timeout"


def test_second_decision_for_same_voice_is_ignored(client, published):
    voice_id = _send_voice(client)
    _decide(client, voice_id, decision_id="dec-a", actions=LIGHT_ON)
    second = _decide(client, voice_id, decision_id="dec-b", actions=LIGHT_ON).json()
    assert second["status"] == "expired"
    assert len(published) == 1
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["decisionId"] == "dec-a"


def test_same_decision_resent_is_duplicate(client, published):
    voice_id = _send_voice(client)
    assert _decide(client, voice_id, actions=LIGHT_ON).status_code == 202
    again = _decide(client, voice_id, actions=LIGHT_ON)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert len(published) == 1


def test_unknown_voice_id(client):
    assert _decide(client, "voice-nope").status_code == 404
    assert client.get(f"{PREFIX}/voice/commands/voice-nope").status_code == 404
    assert client.post(f"{PREFIX}/voice/commands/voice-nope/confirm", json={"approved": True}).status_code == 404


# ---------------------------------------------------------------------------
# 확인 문구 / 기록
# ---------------------------------------------------------------------------

def test_confirm_text_variants():
    from app.schemas import AiAction

    def text(actions, room=None):
        return voice_service.build_confirm_text([AiAction(**a) for a in actions], room)

    assert text([{"device": "light", "deviceId": "light-01", "action": "off"}]) == "방 조명을 끌까요?"
    assert text([{"device": "fan", "action": "set_speed", "speed": "high"}], "kitchen") == "주방 환풍기 풍량을 강으로 바꿀까요?"
    assert text([{"device": "fan", "action": "on"}], "toilet") == "욕실 환풍기를 켤까요?"
    assert (
        text([{"device": "light", "deviceId": TOILET_LIGHT, "action": "on"}, {"device": "fan", "deviceId": KITCHEN_FAN, "action": "off"}])
        == "욕실 조명 켜기, 주방 환풍기 끄기를 실행할까요?"
    )


def test_list_is_newest_first_and_filters_status(client):
    first = _send_voice(client, "첫 번째")
    second = _send_voice(client, "두 번째")
    voice_service.expire_if_waiting(first)

    body = client.get(f"{PREFIX}/voice/commands").json()
    assert [c["voiceId"] for c in body["items"]] == [second, first]
    assert body["total"] == 2
    waiting = client.get(f"{PREFIX}/voice/commands", params={"status": "thinking"}).json()
    assert [c["voiceId"] for c in waiting["items"]] == [second]


def test_confirmation_survives_restart(mongo, published):
    from app.main import app

    with TestClient(app) as client:
        voice_id = _send_voice(client)
        _decide(client, voice_id, actions=LIGHT_ON, confirm=True)

    db.flush()
    state_store.reset_memory()
    with TestClient(app) as client:
        voice = client.get(f"{PREFIX}/voice/commands/{voice_id}").json()
        assert voice["status"] == "confirm_required"
        assert voice["pendingActions"][0]["deviceId"] == TOILET_LIGHT
        body = client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True}).json()
        assert body["status"] == "executed"
        assert published[-1]["deviceId"] == TOILET_LIGHT
