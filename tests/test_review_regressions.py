"""Regressions reproduced during the cross-repository integration review."""
from concurrent.futures import Future
from dataclasses import replace
import json

import pytest

from tests.test_home_automation import home, devices, owned_on, rows, presence, BASE
from tests.test_voice_interaction import voice
from tests.test_voice_v07 import safe_kitchen
from src.integration.backend_client import BackendError
from src.integration.backend_sensing import BackendSensingSource
from src.integration.mqtt_source import InputRouter, Incoming, SensingFault
from src.integration.schemas import iso_time, ContractError
from src.integration.settings import load_settings
from src.interaction.control import validate_safety


@pytest.mark.parametrize("end", ["cooling", "off"])
def test_cooking_end_through_long_cooling_does_not_lose_off_transition(home, end):
    env = home()
    control = owned_on(env)
    def cooling(snapshot):
        snapshot["items"][0]["current_state"]["state"] = "cooling"
    for t in range(1, 31):
        devices(env, t, stove=False, air=True, control=control, mutate=cooling)
    assert len(rows(env)) == 1
    devices(env, 31, stove=False, air=True, control=control, mutate=cooling if end == "cooling" else None)
    env.runtime.dispatch_mock_once()
    assert rows(env)[1]["status"] == "accepted"
    assert rows(env)[1]["source"]["action"] == "off"


@pytest.mark.parametrize("bad_state,is_on", [("overheated", False), ("unknown", False), ("cooling", True)])
def test_abnormal_stove_states_are_not_normal_cooking_end(home, bad_state, is_on):
    env = home()
    control = owned_on(env)
    for t in range(1, 34):
        def mutate(snapshot): snapshot["items"][0]["current_state"]["state"] = bad_state
        devices(env, t, stove=is_on, air=True, control=control, mutate=mutate)
    assert len(rows(env)) == 1


def raw_presence(at, confidence=.95):
    return {"observedAt": iso_time(at), "room": None, "present": False,
            "confidence": confidence, "validSec": 5}


@pytest.mark.parametrize("failure", ["invalid", "future", "network", "old_wifi_contract", "bad_list"])
def test_http_fault_breaks_away_evidence_and_recovers_on_new_measurements(home, failure):
    env = home(whole_home_presence_verified=True, away_confirm_seconds=2)
    settings = load_settings(environ={}, mode="mock", data_dir=env.runtime.config.data_dir)
    settings = replace(settings, integration=env.runtime.config, mqtt=replace(settings.mqtt, join_wait_seconds=0))
    source = BackendSensingSource(settings, env.runtime.client, clock=env.clock)
    router = InputRouter(settings.mqtt, env.runtime)
    try:
        for t in range(5):
            env.clock.now = BASE + t
            source.future = Future()
            raw = raw_presence(env.clock())
            if t == 1:
                if failure == "invalid": raw["confidence"] = 1.5
                if failure == "future": raw["observedAt"] = iso_time(env.clock() + .5)
                if failure == "old_wifi_contract": raw = {"time": iso_time(env.clock()), "location": "empty", "location_confidence": .95}
            if t == 1 and failure == "network":
                source.future.set_exception(BackendError("test timeout", retryable=True))
            else:
                source.future.set_result({} if t == 1 and failure == "bad_list" else [raw])
            for message in source.drain(): router.accept(message)
            router.flush(env.clock())
            env.runtime.advance()
            if t == 1:
                assert env.runtime.home_automation.away is None
                assert env.runtime.controller.realtime_engine.sensing_invalid
            if t < 4: assert not rows(env, "away_all_off")
        assert len(rows(env, "away_all_off")) == 1
        assert env.runtime.home_automation.away["started_at"] == BASE + 2
    finally:
        source.close()


def test_transport_fault_discards_join_and_event_buffers_and_repeated_old_sample(home):
    env = home(whole_home_presence_verified=True, away_confirm_seconds=2)
    settings = load_settings(environ={})
    router = InputRouter(settings.mqtt, env.runtime)
    message = Incoming(settings.mqtt.location_topic, json.dumps(raw_presence(BASE)).encode(), BASE)
    router.accept(message)
    assert router.pending
    # Also place a sample in the event-time buffer before the fault.
    env.runtime.ingest_location({"time": iso_time(BASE), "location": "kitchen", "location_confidence": .95})
    router.accept(SensingFault(BASE + 1, "test_transport_failure"))
    assert not router.pending
    env.clock.now = BASE + 2
    env.runtime.advance()
    assert env.runtime.controller.realtime_engine.sensing_invalid
    assert env.runtime.last_location is None
    router.accept(message)
    router.flush(env.clock())
    assert env.runtime.home_automation.away is None


def live_safety_config(env):
    env.runtime.config = replace(env.runtime.config, mode="live", base_url="http://not-contacted.invalid",
                                 mock_behavior_contract=False, stove_temperature_validity_verified=False)


@pytest.mark.parametrize("action", ["turn_on", "restore_power", "set_level"])
def test_live_temperature_without_validity_contract_blocks_heating_requests(voice, action):
    safe_kitchen(voice)
    live_safety_config(voice)
    device = voice.runtime.devices["stove"].raw
    request = {"device": "stove", "deviceId": "induction-01", "action": action}
    if action in {"turn_on", "set_level"}: request["level"] = 3
    with pytest.raises(ContractError, match="temperature validity contract"):
        validate_safety(voice.runtime, request, device, voice.clock())


def test_live_temperature_guard_allows_emergency_off(voice):
    live_safety_config(voice)
    device = voice.backend.devices[0]
    validate_safety(voice.runtime, {"device": "stove", "deviceId": "induction-01", "action": "turn_off"}, device, voice.clock())


def test_live_temperature_guard_blocks_automatic_restore(home):
    env = home()
    live_safety_config(env)
    row = {"source": {}, "payload": {"actions": [{"device": "stove", "action": "restore_power"}]}}
    assert env.runtime._revalidate(row, BASE) == "stove_temperature_validity_contract_unconfirmed"


def test_live_temperature_validity_setting_is_strict_and_default_off():
    config = load_settings(environ={}).integration
    assert config.mode == "live" and not config.stove_temperature_trusted
    with pytest.raises(ValueError): replace(config, stove_temperature_validity_verified="true")


def test_invalid_behavior_in_router_also_resets_away_candidate(home):
    env = home(whole_home_presence_verified=True, away_confirm_seconds=2)
    presence(env, 0)
    settings = load_settings(environ={})
    router = InputRouter(settings.mqtt, env.runtime)
    bad = {**raw_presence(BASE + 1), "room": "room", "present": True,
           "activity": "get_up", "activityConfidence": "invalid"}
    router.accept(Incoming(settings.mqtt.location_topic, json.dumps(bad).encode(), BASE + 1))
    presence(env, 2)
    assert not rows(env, "away_all_off")
    assert env.runtime.home_automation.away["started_at"] == BASE + 2


def test_queued_explicit_fall_survives_later_transport_fault(home):
    env = home()
    env.runtime.config = replace(env.runtime.config, allowed_lateness=4)
    settings = load_settings(environ={}, mode="mock", data_dir=env.runtime.config.data_dir)
    settings = replace(settings, integration=env.runtime.config)
    source = BackendSensingSource(settings, env.runtime.client, clock=env.clock)
    router = InputRouter(settings.mqtt, env.runtime)
    try:
        env.clock.now = BASE + 1
        fall = {**raw_presence(BASE), "room": "toilet", "present": True,
                "activity": "fall", "activityConfidence": .95, "validSec": 10}
        source.future = Future()
        source.future.set_result([fall, raw_presence(BASE + 1, confidence=1.5)])
        for message in source.drain(): router.accept(message)
        env.clock.now = BASE + 5
        env.runtime.advance()
        assert env.runtime.outbox.fall_incident() is not None
        assert env.runtime.controller.realtime_engine.sensing_invalid
        assert any(r["payload"] and r["payload"]["scenario"] == "fall_detected" for r in env.runtime.outbox.rows())
    finally:
        source.close()


def test_verified_live_temperature_still_uses_existing_safety_checks(voice):
    safe_kitchen(voice)
    live_safety_config(voice)
    voice.runtime.config = replace(voice.runtime.config, stove_temperature_validity_verified=True)
    validate_safety(voice.runtime, {"device": "stove", "deviceId": "induction-01", "action": "turn_on", "level": 3},
                    voice.runtime.devices["stove"].raw, voice.clock())
