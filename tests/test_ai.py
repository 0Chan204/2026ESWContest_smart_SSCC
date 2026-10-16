"""
v0.3: AI 중앙 판정 엔진 연동과 전등·정수기 제어 테스트입니다.

판정 엔진이 POST /ai/decisions 로 판단을 보내면 서버가 그대로 가전을 제어하는지,
판단 기록·피드백·기기 상태가 판정 엔진에 맞는 형태로 나오는지 확인합니다.
"""

from app import home_device_service, state_store
from app.config import settings
from app.schemas import BurnerTelemetry, LastControl, TelemetryReport

PREFIX = settings.API_PREFIX
STOVE = settings.INDUCTION_DEVICE_ID
BURNER = settings.BURNER_ID
LIGHT = "light-01"
WATER = "water-01"


def _decision(decision_id: str, scenario: str, actions: list[dict], **extra) -> dict:
    return {
        "decisionId": decision_id,
        "scenario": scenario,
        "confidence": 0.9,
        "reason": "테스트",
        "timestamp": "2026-10-16T23:00:00+09:00",
        "actions": actions,
        **extra,
    }


def _stove_on(level: int, command_id=None, publisher: str = "user") -> None:
    state_store.save_telemetry(
        STOVE,
        TelemetryReport(
            reportedAt="2026-10-16T12:00:00+00:00",
            burners=[BurnerTelemetry(burnerId=BURNER, deviceState="on", level=level, temperature=120.0)],
            lastControl=LastControl(publisher=publisher, commandId=command_id),
            alarm="off",
        ),
    )


# ---------------------------------------------------------------------------
# 기기 상태
# ---------------------------------------------------------------------------

def test_device_states_list_every_device(client):
    items = client.get(f"{PREFIX}/ai/device-states").json()["items"]
    assert [(d["device"], d["deviceId"]) for d in items] == [
        ("stove", STOVE),
        ("light", LIGHT),
        ("water_purifier", WATER),
    ]
    assert all(d["online"] is False and d["is_on"] is False for d in items)


def test_light_state_and_ack_from_mqtt(client, published):
    command_id = client.post(f"{PREFIX}/devices/{LIGHT}/commands", json={"type": "on"}).json()["commandId"]
    home_device_service.handle_ack(
        LIGHT,
        "light",
        {
            "commandId": command_id,
            "result": "applied",
            "appliedAt": "2026-10-16T12:00:01+00:00",
            "state": {
                "reportedAt": "2026-10-16T12:00:01+00:00",
                "power": "on",
                "mode": "steady",
                "lastControl": {"publisher": "api", "commandId": command_id},
            },
        },
    )

    light = client.get(f"{PREFIX}/devices/{LIGHT}").json()
    assert light["online"] is True
    assert light["is_on"] is True
    assert light["current_state"]["power"] == "on"
    assert light["control_state"] == "user"  # 대시보드에서 사용자가 켰음
    assert client.get(f"{PREFIX}/commands/{command_id}").json()["status"] == "acked"


def test_control_state_is_homevis_after_ai_command(client, published):
    _stove_on(5)
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-cs", "stove_absence", [{"device": "stove", "action": "turn_off"}]),
    )
    command_id = res.json()["actions"][0]["commandId"]
    _stove_on(0, command_id=command_id, publisher="api")  # 기기가 명령을 반영해 보고했다고 가정

    stove = client.get(f"{PREFIX}/ai/device-states").json()["items"][0]
    assert stove["control_state"] == "homevis"


# ---------------------------------------------------------------------------
# 판단 결과 실행
# ---------------------------------------------------------------------------

def test_bedtime_light_off(client, published):
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-1", "bedtime_light_off", [{"device": "light", "action": "off"}], room="room"),
    )
    assert res.status_code == 202
    body = res.json()
    assert body["duplicate"] is False
    assert body["actions"][0]["status"] == "sent"
    assert body["actions"][0]["deviceId"] == LIGHT
    assert published[-1] == {
        "deviceId": LIGHT,
        "commandId": body["actions"][0]["commandId"],
        "issuedAt": published[-1]["issuedAt"],
        "type": "off",
    }

    event = client.get(f"{PREFIX}/safety-events/{body['eventId']}").json()
    assert event["type"] == "ai_control"
    assert event["decisionId"] == "d-1"
    assert client.get(f"{PREFIX}/ai/decisions/d-1").json()["scenario"] == "bedtime_light_off"


def test_same_decision_id_is_not_executed_twice(client, published):
    payload = _decision("d-dup", "bedtime_light_off", [{"device": "light", "action": "off"}])
    assert client.post(f"{PREFIX}/ai/decisions", json=payload).status_code == 202
    again = client.post(f"{PREFIX}/ai/decisions", json=payload)
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert len(published) == 1
    assert client.get(f"{PREFIX}/ai/decisions").json()["total"] == 1


def test_stove_off_then_restore_previous_level(client, published):
    _stove_on(6)
    off = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-off", "stove_absence", [{"device": "stove", "action": "turn_off"}]),
    ).json()
    assert off["actions"][0]["status"] == "sent"
    assert published[-1]["type"] == "turn_off"

    restore = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-restore", "stove_absence", [{"device": "stove", "action": "restore_power"}]),
    ).json()
    assert restore["actions"][0]["status"] == "sent"
    assert published[-1]["type"] == "turn_on"
    assert published[-1]["level"] == 6

    # 한 번 복구하면 저장된 화력이 지워지므로 다시 복구할 수 없다
    again = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-restore-2", "stove_absence", [{"device": "stove", "action": "restore_power"}]),
    ).json()
    assert again["actions"][0]["status"] == "rejected"


def test_user_control_cancels_restore(client, published):
    _stove_on(4)
    client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-off-2", "stove_absence", [{"device": "stove", "action": "turn_off"}]),
    )
    # 그 사이 사용자가 직접 조작하면 예전 화력으로 되돌릴 근거가 사라진다
    client.post(f"{PREFIX}/appliances/{STOVE}/burners/{BURNER}/commands", json={"type": "set_level", "level": 2})
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-restore-3", "stove_absence", [{"device": "stove", "action": "restore_power"}]),
    ).json()
    assert res["actions"][0]["status"] == "rejected"


def test_restore_is_rejected_when_overheated(client, published):
    _stove_on(5)
    client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-off-3", "stove_absence", [{"device": "stove", "action": "turn_off"}]),
    )
    state_store.save_telemetry(
        STOVE,
        TelemetryReport(
            reportedAt="2026-10-16T12:00:00+00:00",
            burners=[BurnerTelemetry(burnerId=BURNER, deviceState="overheated", level=0, temperature=160.0)],
            lastControl=LastControl(publisher="system"),
            alarm="on",
        ),
    )
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-restore-4", "stove_absence", [{"device": "stove", "action": "restore_power"}]),
    ).json()
    assert res["actions"][0]["status"] == "rejected"


def test_water_dispense_needs_amount_from_engine(client, published):
    missing = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-w1", "water_dispense", [{"device": "water_purifier", "action": "dispense"}]),
    ).json()
    assert missing["actions"][0]["status"] == "rejected"
    assert published == []

    ok = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision(
            "d-w2",
            "water_dispense",
            [{"device": "water_purifier", "action": "dispense", "amountMl": 250}],
            weatherBriefing=True,
        ),
    ).json()
    assert ok["actions"][0]["status"] == "sent"
    assert ok["weatherBriefing"] is True
    assert published[-1]["type"] == "dispense"
    assert published[-1]["amountMl"] == 250


def test_wrong_action_or_unknown_device_is_rejected_but_others_run(client, published):
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision(
            "d-mix",
            "custom",
            [
                {"device": "light", "action": "turn_on"},
                {"device": "light", "deviceId": "light-99", "action": "off"},
                {"device": "light", "action": "blink"},
            ],
        ),
    ).json()
    assert [a["status"] for a in res["actions"]] == ["rejected", "rejected", "sent"]
    assert published[-1]["type"] == "blink"
    assert published[-1]["durationSec"] == 10  # 기본 깜빡임 시간
    event = client.get(f"{PREFIX}/safety-events/{res['eventId']}").json()
    assert event["severity"] == "warning"


def test_fall_decision_runs_fall_flow(client, published):
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-fall", "fall_detected", [], room="toilet"),
    ).json()
    assert res["fallIncidentId"] is not None
    assert res["actions"][0]["action"] == "turn_off"
    assert published[-1]["type"] == "turn_off"
    incident = client.get(f"{PREFIX}/fall-incidents/{res['fallIncidentId']}").json()
    assert incident["room"] == "toilet"


def test_feedback_is_linked_to_decision(client, published):
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json=_decision("d-fb", "bedtime_light_off", [{"device": "light", "action": "off"}]),
    ).json()
    client.post(
        f"{PREFIX}/safety-events/{res['eventId']}/feedback",
        json={"verdict": "rejected", "comment": "아직 안 잤어요"},
    )
    decision = client.get(f"{PREFIX}/ai/decisions/d-fb").json()
    assert decision["feedback"]["verdict"] == "rejected"
    assert decision["feedback"]["comment"] == "아직 안 잤어요"


# ---------------------------------------------------------------------------
# 대시보드 직접 제어
# ---------------------------------------------------------------------------

def test_dashboard_device_commands(client, published):
    blink = client.post(f"{PREFIX}/devices/{LIGHT}/commands", json={"type": "blink", "durationSec": 5})
    assert blink.status_code == 202
    assert published[-1]["durationSec"] == 5

    assert client.post(f"{PREFIX}/devices/{WATER}/commands", json={"type": "on"}).status_code == 409
    assert client.post(f"{PREFIX}/devices/{STOVE}/commands", json={"type": "on"}).status_code == 400
    assert client.post(f"{PREFIX}/devices/nope/commands", json={"type": "on"}).status_code == 404


def test_snapshot_includes_all_devices(client):
    devices = client.get(f"{PREFIX}/snapshot").json()["devices"]
    assert {d["deviceId"] for d in devices} == {STOVE, LIGHT, WATER}


# ---------------------------------------------------------------------------
# MQTT 토픽 라우팅
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, topic: str, payload: dict):
        import json

        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


def test_mqtt_messages_are_routed_by_topic(client):
    from app import mqtt_client

    mqtt_client._on_message(
        None,
        None,
        _FakeMessage(
            "home/kitchen/water_purifier/water-01/state",
            {"reportedAt": "2026-10-16T12:00:00+00:00", "status": "dispensing"},
        ),
    )
    mqtt_client._on_message(
        None,
        None,
        _FakeMessage(
            f"home/kitchen/induction/{STOVE}/state",
            {
                "reportedAt": "2026-10-16T12:00:00+00:00",
                "burners": [{"burnerId": BURNER, "deviceState": "on", "level": 3, "temperature": 90.0}],
                "lastControl": {"publisher": "user"},
                "alarm": "off",
            },
        ),
    )
    items = {d["deviceId"]: d for d in client.get(f"{PREFIX}/ai/device-states").json()["items"]}
    assert items[WATER]["is_on"] is True
    assert items[STOVE]["is_on"] is True
    assert items[STOVE]["current_state"]["level"] == 3
