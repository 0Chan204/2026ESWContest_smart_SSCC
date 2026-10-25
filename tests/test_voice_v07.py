"""Reuse the existing voice coordinator/MockLLM against the expanded contract."""
from copy import deepcopy

import pytest

from tests.test_voice_interaction import voice, submit, message, intent, pump, BASE
from tests.test_home_automation import purifier
from src.integration.schemas import iso_time, ContractError
from src.interaction.contracts import request_message, action_payload, decision_payload


def add_air(env, **kwargs):
    env.backend.devices.append(purifier(env.clock(), **kwargs))


@pytest.mark.parametrize("wake", [True, False])
def test_backend_text_only_and_wake_fields_preserved(voice, wake):
    add_air(voice)
    text = "공기청정기 켜줘"
    voice.llm.responses.append(intent(text, device="air_purifier", room="room"))
    raw = message(text, rawText="홈비스, 인덕션 9단으로 켜줘", wakeWord=wake)
    assert voice.runtime.receive_voice_request(raw)
    row = pump(voice)
    assert row["request"]["rawText"] == raw["rawText"] and row["request"]["wakeWord"] is wake
    assert "인덕션" not in voice.llm.calls[0][1]
    assert row["payload"]["voiceId"] == raw["voiceId"]
    assert row["payload"]["actions"][0]["device"] == "air_purifier"
    assert row["status"] == "awaiting_confirmation"


@pytest.mark.parametrize("extra", [{"wakeWord": "true"}, {"rawText": 1}, {"rawText": ""}])
def test_invalid_wake_metadata_rejected(extra):
    with pytest.raises(ContractError): request_message(message(**extra), BASE)


def test_ai_does_not_strip_wake_word_again(voice):
    text = "홈비스, 불 켜줘"
    voice.llm.responses.append(intent(text))
    voice.runtime.receive_voice_request(message(text, rawText=text, wakeWord=False))
    pump(voice)
    assert text in voice.llm.calls[0][1]


@pytest.mark.parametrize("action,parameters,text", [("on", {}, "공기청정기 켜줘"), ("off", {}, "공청기 꺼줘"),
    ("set_mode", {"mode": "auto"}, "공기청정기 자동 모드로 바꿔줘"),
    ("set_mode", {"mode": "manual"}, "공기청정기 수동 모드로 해줘")])
def test_air_voice_commands_confirmed_and_whitelisted(voice, action, parameters, text):
    add_air(voice)
    row = submit(voice, text, device="air_purifier", room="room", action=action, parameters=parameters)
    assert row["status"] == "awaiting_confirmation" and row["payload"]["requiresConfirmation"]
    assert row["payload"]["actions"] == [{"device": "air_purifier", "deviceId": "air-01", "action": action, **parameters}]
    assert voice.runtime.outbox.get_metadata("purifier_manual_intent")


def test_air_status_not_feedback_and_no_pm_reclassification(voice):
    add_air(voice, level="normal")
    before = deepcopy(voice.runtime.controller.weight_manager.get_weights("default", "light_auto_off"))
    row = submit(voice, "지금 공기질 어때?", labels=("status_question",), device="air_purifier", room="room", action=None)
    assert "보통" in row["payload"]["announcement"] and "12.3" in row["payload"]["announcement"]
    assert not row["payload"]["actions"] and voice.runtime.controller.feedback_storage.list_records() == []
    assert voice.runtime.controller.weight_manager.get_weights("default", "light_auto_off") == before


@pytest.mark.parametrize("publisher,phrase", [("system", "자체 자동 제어"), ("user", "사용자 직접 조작"), (None, "출처는 확인되지")])
def test_air_explanation_never_invents_ai_ownership(voice, publisher, phrase):
    add_air(voice, on=True, control={"publisher": publisher} if publisher else None)
    row = submit(voice, "왜 공기청정기가 켜졌어?", labels=("explanation_question",), device="air_purifier", room="room", action="on")
    assert phrase in row["payload"]["announcement"]
    assert not row["payload"]["actions"] and not voice.runtime.controller.feedback_storage.list_records()


def safe_kitchen(env, *, temperature=50):
    for second in (0, 6):
        env.clock.now = BASE + second
        for item in env.backend.devices:
            item["updatedAt"] = iso_time(env.clock())
        env.backend.devices[0].update(is_on=False, current_state={"state": "off", "level": 0, "temperature": temperature})
        env.runtime.ingest_device_states({"items": deepcopy(env.backend.devices)})
        env.runtime.ingest_location({"time": iso_time(env.clock()), "location": "kitchen", "location_confidence": .95,
                                     "valid_until": iso_time(env.clock() + 10)})
        env.runtime.advance()


def test_explicit_stove_on_waits_for_backend_confirmation(voice):
    safe_kitchen(voice)
    row = submit(voice, "인덕션 3단으로 켜줘", device="stove", room="kitchen", action="turn_on", parameters={"level": 3})
    assert row["payload"]["actions"] == [{"device": "stove", "deviceId": "induction-01", "action": "turn_on", "level": 3}]
    assert row["status"] == "awaiting_confirmation" and row["payload"]["requiresConfirmation"]
    assert not voice.backend.devices[0]["is_on"]  # pending != physical execution


def test_stove_off_is_immediate_contract_not_physical_confirmation(voice):
    row = submit(voice, "인덕션 꺼줘", device="stove", room="kitchen", action="turn_off")
    assert row["payload"]["actions"][0]["action"] == "turn_off"
    assert row["payload"]["requiresConfirmation"] is False and row["response"]["status"] == "executed"
    assert voice.backend.devices[0]["is_on"]  # mock sent without telemetry update


@pytest.mark.parametrize("level", [0, 10, True, 2.5, None])
def test_stove_on_invalid_level_rejected(level):
    with pytest.raises(ContractError): action_payload({"device": "stove", "deviceId": "induction-01", "action": "turn_on", "level": level})


def test_stove_on_without_confirmation_rejected():
    with pytest.raises(ContractError): decision_payload({"decisionId": "d", "voiceId": "v", "scenario": "voice_command",
        "confidence": .9, "timestamp": iso_time(BASE), "room": "kitchen", "announcement": "test", "requiresConfirmation": False,
        "actions": [{"device": "stove", "deviceId": "induction-01", "action": "turn_on", "level": 3}]})


@pytest.mark.parametrize("problem", ["overheat", "no_kitchen", "fall", "away"])
def test_stove_on_cannot_bypass_safety(voice, problem):
    if problem != "no_kitchen": safe_kitchen(voice, temperature=220 if problem == "overheat" else 50)
    if problem == "fall": voice.runtime.outbox.latch_fall(voice.clock(), "fall-1")
    if problem == "away": voice.runtime.home_automation.away = {"id": "away-1", "requested_at": voice.clock()}
    row = submit(voice, "인덕션 3단으로 켜줘", device="stove", room="kitchen", action="turn_on", parameters={"level": 3})
    assert not row["payload"]["actions"]
