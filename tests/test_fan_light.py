"""
v0.5: 환풍기(fan) 추가, 전등 밝기, 절전(power_saving / power_saving_end) 테스트입니다.

- 환풍기: on / off / set_speed(low·mid·high = 약·중·강)
- 전등: on = 100%, off, fadeout = 절전 밝기(20%)로 서서히 낮춤(power는 on 유지)
- 절전: 판정 엔진이 power_saving(room)을 보내면 그 구역의 켜진 전등을 20%로 낮추고,
        power_saving_end(room)를 보내면 절전으로 낮췄던 전등만 100%로 되돌림
"""

from fastapi.testclient import TestClient

from app import db, home_device_service, state_store
from app.config import settings

PREFIX = settings.API_PREFIX
ROOM_LIGHT = "light-01"  # room
TOILET_LIGHT = "light-00"  # toilet
KITCHEN_FAN = "fan-01"
TOILET_FAN = "fan-02"


def _light_state(device_id: str, power: str, brightness=None, mode: str = "steady") -> None:
    state = {"reportedAt": "2026-10-17T12:00:00+00:00", "power": power, "mode": mode}
    if brightness is not None:
        state["brightness"] = brightness
    home_device_service.handle_state(device_id, "light", state)


def _decision(decision_id: str, scenario: str, room=None, actions=None) -> dict:
    body = {
        "decisionId": decision_id,
        "scenario": scenario,
        "confidence": 0.9,
        "timestamp": "2026-10-17T21:00:00+09:00",
        "actions": actions or [],
    }
    if room is not None:
        body["room"] = room
    return body


# ---------------------------------------------------------------------------
# 환풍기
# ---------------------------------------------------------------------------

def test_fans_are_registered_with_topics(client):
    from app import device_registry

    fan = device_registry.get_device(KITCHEN_FAN)
    assert (fan.type, fan.room) == ("fan", "kitchen")
    assert device_registry.topic(fan, "command") == "home/kitchen/fan/fan-01/command"
    assert device_registry.get_device(TOILET_FAN).room == "toilet"
    assert "home/+/fan/+/state" in device_registry.home_device_subscriptions()
    assert device_registry.parse_topic("home/toilet/fan/fan-02/ack") == ("fan", "fan-02", "ack")


def test_fan_commands(client, published):
    res = client.post(f"{PREFIX}/devices/{KITCHEN_FAN}/commands", json={"type": "set_speed", "speed": "high"})
    assert res.status_code == 202
    assert published[-1] == {
        "deviceId": KITCHEN_FAN,
        "commandId": res.json()["commandId"],
        "issuedAt": published[-1]["issuedAt"],
        "type": "set_speed",
        "speed": "high",
    }
    record = client.get(f"{PREFIX}/commands/{res.json()['commandId']}").json()
    assert (record["deviceType"], record["speed"]) == ("fan", "high")

    assert client.post(f"{PREFIX}/devices/{KITCHEN_FAN}/commands", json={"type": "on"}).status_code == 202
    assert client.post(f"{PREFIX}/devices/{KITCHEN_FAN}/commands", json={"type": "off"}).status_code == 202
    # 풍량 없이 set_speed, 환풍기에 없는 명령, 없는 풍량
    assert client.post(f"{PREFIX}/devices/{KITCHEN_FAN}/commands", json={"type": "set_speed"}).status_code == 409
    assert client.post(f"{PREFIX}/devices/{KITCHEN_FAN}/commands", json={"type": "blink"}).status_code == 409
    assert client.post(f"{PREFIX}/devices/{KITCHEN_FAN}/commands", json={"type": "set_speed", "speed": "turbo"}).status_code == 422


def test_fan_state_and_ack(client, published):
    command_id = client.post(
        f"{PREFIX}/devices/{TOILET_FAN}/commands", json={"type": "set_speed", "speed": "low"}
    ).json()["commandId"]
    home_device_service.handle_ack(
        TOILET_FAN,
        "fan",
        {
            "commandId": command_id,
            "result": "applied",
            "appliedAt": "2026-10-17T12:00:01+00:00",
            "state": {
                "reportedAt": "2026-10-17T12:00:01+00:00",
                "power": "on",
                "speed": "low",
                "lastControl": {"publisher": "api", "commandId": command_id},
            },
        },
    )
    fan = client.get(f"{PREFIX}/devices/{TOILET_FAN}").json()
    assert (fan["online"], fan["is_on"]) == (True, True)
    assert fan["current_state"]["speed"] == "low"
    assert client.get(f"{PREFIX}/commands/{command_id}").json()["status"] == "acked"


def test_fan_control_from_ai_decision(client, published):
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision(
            "d-fan", "cooking_ventilation", room="kitchen",
            actions=[{"device": "fan", "action": "set_speed", "speed": "mid"}],
        ),
    ).json()
    assert res["actions"][0]["status"] == "sent"
    assert res["actions"][0]["deviceId"] == KITCHEN_FAN
    assert (published[-1]["type"], published[-1]["speed"]) == ("set_speed", "mid")

    missing_speed = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-fan-2", "cooking_ventilation", room="kitchen", actions=[{"device": "fan", "action": "set_speed"}]),
    ).json()
    assert missing_speed["actions"][0]["status"] == "rejected"


# ---------------------------------------------------------------------------
# 전등 밝기
# ---------------------------------------------------------------------------

def test_light_on_and_fadeout_commands(client, published):
    client.post(f"{PREFIX}/devices/{ROOM_LIGHT}/commands", json={"type": "on"})
    assert (published[-1]["type"], published[-1]["brightness"]) == ("on", 100)

    client.post(f"{PREFIX}/devices/{ROOM_LIGHT}/commands", json={"type": "fadeout"})
    assert published[-1]["type"] == "fadeout"
    assert published[-1]["brightness"] == settings.LIGHT_SAVING_BRIGHTNESS == 20
    assert published[-1]["durationSec"] == settings.LIGHT_FADE_SEC

    client.post(f"{PREFIX}/devices/{ROOM_LIGHT}/commands", json={"type": "off"})
    assert "brightness" not in published[-1]


def test_light_brightness_in_device_state(client):
    _light_state(ROOM_LIGHT, "on")  # 밝기를 안 보내는 전등
    _light_state(TOILET_LIGHT, "on", brightness=20, mode="fadeout")
    items = {d["deviceId"]: d for d in client.get(f"{PREFIX}/ai/device-states").json()["items"]}
    assert items[ROOM_LIGHT]["current_state"]["brightness"] == 100
    assert items[TOILET_LIGHT]["current_state"]["brightness"] == 20
    assert items[TOILET_LIGHT]["current_state"]["mode"] == "fadeout"
    assert items[TOILET_LIGHT]["is_on"] is True  # 절전 밝기여도 power는 on

    _light_state(ROOM_LIGHT, "off")
    assert client.get(f"{PREFIX}/devices/{ROOM_LIGHT}").json()["current_state"]["brightness"] == 0


# ---------------------------------------------------------------------------
# 절전 (power_saving / power_saving_end)
# ---------------------------------------------------------------------------

def test_power_saving_dims_lights_on_in_that_room(client, published):
    _light_state(ROOM_LIGHT, "on", brightness=100)
    _light_state(TOILET_LIGHT, "on", brightness=100)  # 다른 구역 전등은 그대로

    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-save", "power_saving", room="room")).json()
    assert [(a["deviceId"], a["action"], a["status"]) for a in res["actions"]] == [(ROOM_LIGHT, "fadeout", "sent")]
    assert [(c["deviceId"], c["type"], c["brightness"]) for c in published] == [(ROOM_LIGHT, "fadeout", 20)]
    assert client.get(f"{PREFIX}/devices/{ROOM_LIGHT}").json()["current_state"]["powerSaving"] is True

    # 같은 구역에서 다시 와도 이미 절전 중이면 또 보내지 않음
    again = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-save-2", "power_saving", room="room")).json()
    assert again["actions"] == []
    assert len(published) == 1


def test_power_saving_skips_lights_off_or_already_dim(client, published):
    _light_state(ROOM_LIGHT, "off")
    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-off", "power_saving", room="room")).json()
    assert res["actions"] == [] and published == []

    _light_state(ROOM_LIGHT, "on", brightness=10)
    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-dim", "power_saving", room="room")).json()
    assert res["actions"] == [] and published == []


def test_power_saving_end_restores_only_dimmed_lights(client, published):
    _light_state(ROOM_LIGHT, "on", brightness=100)
    client.post(f"{PREFIX}/ai/decisions", json=_decision("d-save", "power_saving", room="room"))
    _light_state(ROOM_LIGHT, "on", brightness=20, mode="fadeout")  # 전등이 낮춘 뒤 보고

    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-back", "power_saving_end", room="room")).json()
    assert [(a["deviceId"], a["action"], a["status"]) for a in res["actions"]] == [(ROOM_LIGHT, "on", "sent")]
    assert (published[-1]["type"], published[-1]["brightness"]) == ("on", 100)
    assert state_store.is_power_saving_light(ROOM_LIGHT) is False

    # 절전 중이 아니면 복귀 판단이 와도 아무것도 하지 않음
    again = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-back-2", "power_saving_end", room="room")).json()
    assert again["actions"] == []


def test_user_turned_off_light_is_not_turned_back_on(client, published):
    _light_state(ROOM_LIGHT, "on", brightness=100)
    client.post(f"{PREFIX}/ai/decisions", json=_decision("d-save", "power_saving", room="room"))
    client.post(f"{PREFIX}/devices/{ROOM_LIGHT}/commands", json={"type": "off"})  # 사용자가 직접 끔
    _light_state(ROOM_LIGHT, "off")
    sent = len(published)

    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-back", "power_saving_end", room="room")).json()
    assert res["actions"] == []
    assert len(published) == sent


def test_light_switched_off_at_wall_is_not_turned_back_on(client, published):
    """대시보드가 아니라 벽 스위치 등으로 꺼진 경우(상태만 off로 옴)도 다시 켜지 않는다."""
    _light_state(ROOM_LIGHT, "on", brightness=100)
    client.post(f"{PREFIX}/ai/decisions", json=_decision("d-save", "power_saving", room="room"))
    _light_state(ROOM_LIGHT, "off")
    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-back", "power_saving_end", room="room")).json()
    assert res["actions"] == []
    assert state_store.is_power_saving_light(ROOM_LIGHT) is False


def test_power_saving_needs_room(client, published):
    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-noroom", "power_saving")).json()
    assert res["actions"][0]["status"] == "rejected"
    assert published == []


def test_power_saving_survives_restart(mongo, client, published):
    _light_state(ROOM_LIGHT, "on", brightness=100)
    client.post(f"{PREFIX}/ai/decisions", json=_decision("d-save", "power_saving", room="room"))

    from app.main import app

    db.flush()
    state_store.reset_memory()
    with TestClient(app) as restarted:
        assert state_store.is_power_saving_light(ROOM_LIGHT) is True
        res = restarted.post(f"{PREFIX}/ai/decisions", json=_decision("d-back", "power_saving_end", room="room")).json()
        assert [(a["deviceId"], a["action"]) for a in res["actions"]] == [(ROOM_LIGHT, "on")]
