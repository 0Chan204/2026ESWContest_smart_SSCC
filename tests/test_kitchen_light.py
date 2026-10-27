"""
v0.8: 주방 전등(light-02, kitchen) 추가 테스트입니다.

- 전등 3개: light-01(방), light-00(화장실), light-02(주방)
- 토픽: home/kitchen/light/light-02/{state|command|ack}
- 주방 절전(power_saving / power_saving_end), 외출 시 전체 끄기, 주방 낙상 깜빡임, 음성 확인 문구에 포함
"""

from app import device_registry, home_device_service, voice_service
from app.config import settings
from app.schemas import AiAction

PREFIX = settings.API_PREFIX
ROOM_LIGHT = "light-01"
TOILET_LIGHT = "light-00"
KITCHEN_LIGHT = "light-02"


def _light_state(device_id: str, power: str, brightness=None, mode: str = "steady") -> None:
    state = {"reportedAt": "2026-10-27T12:00:00+00:00", "power": power, "mode": mode}
    if brightness is not None:
        state["brightness"] = brightness
    home_device_service.handle_state(device_id, "light", state)


def _decision(decision_id: str, scenario: str, room=None, actions=None) -> dict:
    body = {
        "decisionId": decision_id,
        "scenario": scenario,
        "confidence": 0.9,
        "timestamp": "2026-10-27T21:00:00+09:00",
        "actions": actions or [],
    }
    if room is not None:
        body["room"] = room
    return body


def test_kitchen_light_is_registered_with_topics(client):
    light = device_registry.get_device(KITCHEN_LIGHT)
    assert (light.type, light.room) == ("light", "kitchen")
    assert device_registry.topic(light, "command") == "home/kitchen/light/light-02/command"
    assert device_registry.parse_topic("home/kitchen/light/light-02/state") == ("light", KITCHEN_LIGHT, "state")
    assert [d.deviceId for d in device_registry.devices_in_room("light", "kitchen")] == [KITCHEN_LIGHT]

    ids = [d["deviceId"] for d in client.get(f"{PREFIX}/devices").json()["items"]]
    assert {ROOM_LIGHT, TOILET_LIGHT, KITCHEN_LIGHT} <= set(ids)


def test_kitchen_light_commands_and_state(client, published):
    res = client.post(f"{PREFIX}/devices/{KITCHEN_LIGHT}/commands", json={"type": "on"})
    assert res.status_code == 202
    assert (published[-1]["deviceId"], published[-1]["type"], published[-1]["brightness"]) == (KITCHEN_LIGHT, "on", 100)

    _light_state(KITCHEN_LIGHT, "on", brightness=100)
    res = client.post(f"{PREFIX}/devices/{KITCHEN_LIGHT}/commands", json={"type": "fadeout"})
    assert res.status_code == 202
    assert (published[-1]["type"], published[-1]["brightness"]) == ("fadeout", settings.LIGHT_SAVING_BRIGHTNESS)

    _light_state(KITCHEN_LIGHT, "on", brightness=20, mode="fadeout")
    state = client.get(f"{PREFIX}/devices/{KITCHEN_LIGHT}").json()["current_state"]
    assert (state["power"], state["brightness"]) == ("on", 20)


def test_power_saving_in_kitchen_dims_only_kitchen_light(client, published):
    _light_state(ROOM_LIGHT, "on", brightness=100)
    _light_state(KITCHEN_LIGHT, "on", brightness=100)

    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-k-save", "power_saving", room="kitchen")).json()
    assert [(a["deviceId"], a["action"], a["status"]) for a in res["actions"]] == [(KITCHEN_LIGHT, "fadeout", "sent")]
    assert [c["deviceId"] for c in published] == [KITCHEN_LIGHT]

    _light_state(KITCHEN_LIGHT, "on", brightness=20, mode="fadeout")
    back = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-k-back", "power_saving_end", room="kitchen")).json()
    assert [(a["deviceId"], a["action"], a["status"]) for a in back["actions"]] == [(KITCHEN_LIGHT, "on", "sent")]
    assert (published[-1]["type"], published[-1]["brightness"]) == ("on", 100)


def test_away_all_off_includes_kitchen_light(client, published):
    _light_state(ROOM_LIGHT, "off")
    _light_state(KITCHEN_LIGHT, "on", brightness=20, mode="fadeout")  # 절전 밝기여도 켜진 것으로 봄

    res = client.post(f"{PREFIX}/ai/decisions", json=_decision("d-k-away", "away_all_off")).json()
    assert [(a["deviceId"], a["action"], a["status"]) for a in res["actions"]] == [(KITCHEN_LIGHT, "off", "sent")]
    assert [c["deviceId"] for c in published] == [KITCHEN_LIGHT]


def test_kitchen_fall_blinks_kitchen_light(client, published):
    report = {"room": "kitchen", "confidence": 0.95, "observedAt": "2026-10-27T12:00:00+00:00", "modelVersion": "test-model"}
    res = client.post(f"{PREFIX}/safety/fall-events", json=report)
    assert res.status_code == 202
    assert res.json()["lightBlinkSent"] is True
    incident = client.get(f"{PREFIX}/fall-incidents/{res.json()['incidentId']}").json()
    assert incident["lightDeviceId"] == KITCHEN_LIGHT
    assert ("light-02", "blink") in [(c.get("deviceId"), c["type"]) for c in published]


def test_confirm_text_for_kitchen_light():
    def text(actions, room=None):
        return voice_service.build_confirm_text([AiAction(**a) for a in actions], room)

    assert text([{"device": "light", "deviceId": KITCHEN_LIGHT, "action": "on"}]) == "주방 조명을 켤까요?"
    assert text([{"device": "light", "action": "off"}], "kitchen") == "주방 조명을 끌까요?"
