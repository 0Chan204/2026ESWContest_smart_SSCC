"""
v0.7: 공기청정기, 시작어 음성 명령, 외출 시 전체 가전 끄기 테스트입니다.

- 공기청정기: 상태(공기질 포함) 수신·전달, on / off / set_mode 명령, AI 판단 제어
- 시작어: "홈비스"를 떼고 wakeWord=true로 판정 엔진에 전달, 음성으로 인덕션을 켜면 항상 확인
- away_all_off: 켜져 있는 인덕션·전등·환풍기·공기청정기를 모두 끔 (정수기 제외, 인덕션 화력 저장)
"""

import pytest

from app import device_registry, home_device_service, state_store
from app.config import settings
from app.schemas import BurnerTelemetry, LastControl, TelemetryReport

PREFIX = settings.API_PREFIX
STOVE = settings.INDUCTION_DEVICE_ID
BURNER = settings.BURNER_ID
AIR = "air-01"


@pytest.fixture()
def broadcasts(monkeypatch):
    from app import ws_hub

    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(ws_hub, "broadcast_threadsafe", lambda event, data: sent.append((event, data)))
    return sent


def _stove_on(level: int = 5) -> None:
    state_store.save_telemetry(
        STOVE,
        TelemetryReport(
            reportedAt="2026-10-25T12:00:00+00:00",
            burners=[BurnerTelemetry(burnerId=BURNER, deviceState="on", level=level, temperature=120.0)],
            lastControl=LastControl(publisher="user"),
            alarm="off",
        ),
    )


def _state(device_id: str, device_type: str, **state) -> None:
    home_device_service.handle_state(device_id, device_type, {"reportedAt": "2026-10-25T12:00:00+00:00", **state})


def _decision(decision_id: str, scenario: str, actions=None, **extra) -> dict:
    return {
        "decisionId": decision_id,
        "scenario": scenario,
        "confidence": 0.9,
        "timestamp": "2026-10-25T21:00:00+09:00",
        "actions": actions or [],
        **extra,
    }


# ---------------------------------------------------------------------------
# 공기청정기
# ---------------------------------------------------------------------------

def test_air_purifier_registered():
    air = device_registry.get_device(AIR)
    assert (air.type, air.room) == ("air_purifier", "room")
    assert device_registry.topic(air, "state") == "home/room/air_purifier/air-01/state"
    assert "home/+/air_purifier/+/ack" in device_registry.home_device_subscriptions()
    assert device_registry.parse_topic("home/room/air_purifier/air-01/state") == ("air_purifier", AIR, "state")


def test_auto_on_by_air_quality_is_reported_to_dashboard(client, broadcasts):
    """공기질이 나빠 기기가 스스로 켜면(publisher: system) 서버가 저장하고 대시보드에 그대로 전달한다."""
    _state(
        AIR, "air_purifier", power="on", mode="auto",
        airQuality={"pm25": 42, "pm10": 60, "level": "bad"}, lastControl={"publisher": "system"},
    )
    event = next(d for e, d in broadcasts if e == "device.state" and d["deviceId"] == AIR)
    assert event["state"]["power"] == "on"
    assert event["state"]["airQuality"]["level"] == "bad"
    assert event["state"]["lastControl"]["publisher"] == "system"

    info = client.get(f"{PREFIX}/devices/{AIR}").json()
    assert (info["is_on"], info["online"]) == (True, True)
    assert info["current_state"]["airQuality"]["pm25"] == 42
    assert info["control_state"] == "homevis"  # 기기가 스스로 켬 (사용자 조작 아님)


def test_air_quality_extra_fields_are_kept(client):
    _state(AIR, "air_purifier", power="off", airQuality={"pm25": 10, "level": "good", "co2": 600})
    assert client.get(f"{PREFIX}/devices/{AIR}").json()["current_state"]["airQuality"]["co2"] == 600


def test_air_purifier_commands(client, published):
    assert client.post(f"{PREFIX}/devices/{AIR}/commands", json={"type": "on"}).status_code == 202
    assert (published[-1]["deviceId"], published[-1]["type"]) == (AIR, "on")
    assert "brightness" not in published[-1]  # 전등이 아니므로 밝기 없음

    res = client.post(f"{PREFIX}/devices/{AIR}/commands", json={"type": "set_mode", "mode": "manual"})
    assert res.status_code == 202
    assert (published[-1]["type"], published[-1]["mode"]) == ("set_mode", "manual")
    assert client.get(f"{PREFIX}/commands/{res.json()['commandId']}").json()["mode"] == "manual"

    assert client.post(f"{PREFIX}/devices/{AIR}/commands", json={"type": "set_mode"}).status_code == 409
    assert client.post(f"{PREFIX}/devices/{AIR}/commands", json={"type": "set_speed", "speed": "high"}).status_code == 409
    assert client.post(f"{PREFIX}/devices/{AIR}/commands", json={"type": "set_mode", "mode": "turbo"}).status_code == 422


def test_ai_turns_on_air_purifier_when_cooking(client, published):
    """인덕션이 켜진 걸 보고 판정 엔진이 공기청정기를 켜는 판단을 보내면 서버가 실행한다."""
    _stove_on(5)
    assert client.get(f"{PREFIX}/ai/device-states").json()["items"][0]["is_on"] is True
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-air", "cooking_air_clean", [{"device": "air_purifier", "action": "on"}], room="room"),
    ).json()
    assert (res["actions"][0]["deviceId"], res["actions"][0]["status"]) == (AIR, "sent")
    assert (published[-1]["deviceId"], published[-1]["type"]) == (AIR, "on")


# ---------------------------------------------------------------------------
# 시작어 음성 명령
# ---------------------------------------------------------------------------

def test_wake_word_is_stripped_before_sending_to_ai(client, published_json):
    res = client.post(f"{PREFIX}/voice/commands", json={"text": "홈비스, 욕실 조명 켜줘"})
    assert res.status_code == 202
    topic, message = published_json[-1]
    assert topic == "home/voice/request"
    assert (message["text"], message["rawText"], message["wakeWord"]) == ("욕실 조명 켜줘", "홈비스, 욕실 조명 켜줘", True)

    stored = client.get(f"{PREFIX}/voice/commands/{res.json()['voiceId']}").json()
    assert (stored["text"], stored["wakeWord"]) == ("욕실 조명 켜줘", True)


@pytest.mark.parametrize(
    "spoken, command",
    [
        ("홈 비스 불 꺼줘", "불 꺼줘"),
        ("홈비즈야 환풍기 틀어줘", "환풍기 틀어줘"),
        ("HomeVIS 공기청정기 켜줘", "공기청정기 켜줘"),
    ],
)
def test_wake_word_variants(client, published_json, spoken, command):
    client.post(f"{PREFIX}/voice/commands", json={"text": spoken})
    assert published_json[-1][1]["text"] == command
    assert published_json[-1][1]["wakeWord"] is True


def test_without_wake_word_and_wake_word_only(client, published_json):
    client.post(f"{PREFIX}/voice/commands", json={"text": "욕실 조명 켜줘"})
    assert published_json[-1][1]["wakeWord"] is False
    count = len(published_json)
    assert client.post(f"{PREFIX}/voice/commands", json={"text": "홈비스"}).status_code == 422
    assert len(published_json) == count  # 판정 엔진에 보내지 않음


def _voice_decision(client, voice_id, actions, confirm=False):
    return client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-voice-stove", "voice_command", actions, voiceId=voice_id, room="kitchen",
                       announcement="인덕션을 3단으로 켤게요.", requiresConfirmation=confirm),
    ).json()


def test_voice_stove_on_always_needs_confirmation(client, published):
    voice_id = client.post(f"{PREFIX}/voice/commands", json={"text": "홈비스 인덕션 3단으로 켜줘"}).json()["voiceId"]
    res = _voice_decision(client, voice_id, [{"device": "stove", "action": "turn_on", "level": 3}], confirm=False)
    assert res["status"] == "awaiting_confirmation"  # 확인 없이 보냈지만 서버가 확인을 받음
    assert published == []

    voice = client.get(f"{PREFIX}/voice/commands/{voice_id}").json()
    assert voice["confirmText"] == "주방 인덕션을 3단으로 켤까요?"
    body = client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True}).json()
    assert body["status"] == "executed"
    assert (published[-1]["type"], published[-1]["level"]) == ("turn_on", 3)


def test_voice_stove_off_runs_right_away(client, published):
    _stove_on(5)
    voice_id = client.post(f"{PREFIX}/voice/commands", json={"text": "홈비스 인덕션 꺼줘"}).json()["voiceId"]
    res = _voice_decision(client, voice_id, [{"device": "stove", "action": "turn_off"}])
    assert res["status"] == "executed"
    assert published[-1]["type"] == "turn_off"


# ---------------------------------------------------------------------------
# 외출 시 전체 가전 끄기
# ---------------------------------------------------------------------------

def test_away_all_off_turns_off_everything_that_is_on(client, published, broadcasts):
    _stove_on(5)
    _state("light-01", "light", power="on", brightness=100)
    _state("light-00", "light", power="off")
    _state("fan-01", "fan", power="on", speed="mid")
    _state(AIR, "air_purifier", power="on", mode="auto")
    _state("water-01", "water_purifier", status="dispensing")

    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-away", "away_all_off")).json()
    assert [(a["deviceId"], a["action"], a["status"]) for a in res["actions"]] == [
        (STOVE, "turn_off", "sent"),
        ("light-01", "off", "sent"),
        ("fan-01", "off", "sent"),
        (AIR, "off", "sent"),
    ]
    assert {c["deviceId"] for c in published} == {STOVE, "light-01", "fan-01", AIR}  # 꺼진 전등·정수기는 건드리지 않음
    assert state_store.get_restore_level(STOVE) == 5  # 돌아오면 restore_power로 복구 가능
    assert res["announcement"] == "외출하신 것 같아 켜져 있던 가전 4개를 껐어요."
    announcement = next(d for e, d in broadcasts if e == "ai.announcement")
    assert announcement["text"] == res["announcement"]
    assert client.get(f"{PREFIX}/safety-events/{res['eventId']}").json()["type"] == "ai_control"


def test_away_all_off_when_nothing_is_on(client, published, broadcasts):
    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-away-0", "away_all_off")).json()
    assert res["actions"] == [] and published == []
    assert res["announcement"] is None
    assert not [d for e, d in broadcasts if e == "ai.announcement"]


def test_away_all_off_keeps_engine_announcement_and_skips_duplicate_offs(client, published):
    _state("light-01", "light", power="on")
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision(
            "d-away-2", "away_all_off", [{"device": "light", "deviceId": "light-01", "action": "off"}],
            announcement="다녀오세요. 불을 껐어요.",
        ),
    ).json()
    assert len(published) == 1  # 같은 전등을 두 번 끄지 않음
    assert res["announcement"] == "다녀오세요. 불을 껐어요."
