"""Offline v0.7 rules, persistence, and explicit missing cross-device contracts."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from examples.backend_integration_demo import FakeClock
from src.alert_service import AlertService
from src.integration.backend_client import BackendClient, BackendError, HTTPResult
from src.integration.backend_sensing import normalize_result
from src.integration.home_config import HomeAutomationConfig
from src.integration.mock_backend import MockBackend, sample_devices
from src.integration.runtime import IntegrationRuntime
from src.integration.schemas import ContractError, decision_payload, decision_response, iso_time, measured_time
from src.integration.settings import load_settings
from src.integration.state_mapper import purifier_state
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS

BASE = measured_time("2026-10-26T12:00:00+09:00")


def purifier(at=BASE, *, on=False, level="good", control=None, owner="homevis"):
    state = {"reportedAt": iso_time(at), "power": "on" if on else "off", "mode": "auto",
             "airQuality": {"level": level, "pm25": 12.3, "pm10": 23.4, "co2": 500}}
    if control is not None:
        state["lastControl"] = control
    return {"device": "air_purifier", "deviceId": "air-01", "room": "room", "online": True,
            "is_on": on, "current_state": state, "control_state": owner, "updatedAt": iso_time(at)}


class V07Backend(MockBackend):
    def request(self, method, url, headers, body, timeout):
        lost, self.fail_after_accept = self.fail_after_accept, False
        response = super().request(method, url, headers, body, timeout)
        if method == "POST" and response.status == 202:
            request = json.loads(body)
            if request["scenario"] == "away_all_off":
                actions = [{"device": d["device"], "deviceId": d["deviceId"],
                            "action": "turn_off" if d["device"] == "stove" else "off"}
                           for d in self.snapshot["items"] if d["device"] != "water_purifier" and d["is_on"]]
            else:
                actions = request["actions"]
            response.body.update(status="executed", actions=[{**a, "status": "sent", "commandId": f"cmd-{request['decisionId']}-{i}"}
                                                             for i, a in enumerate(actions)])
            self.accepted[request["decisionId"]] = deepcopy(request), deepcopy(response.body)
            if lost:
                raise BackendError("lost mock response", retryable=True)
        return response


@pytest.fixture
def home(tmp_path):
    instances = []
    def make(**policy):
        settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
        home_config = replace(settings.integration.home_automation, **policy)
        config = replace(settings.integration, allowed_lateness=0, async_alerts=False, home_automation=home_config)
        clock = FakeClock(BASE)
        backend = V07Backend(clock)
        service = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio")
        runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=clock, fall_alert_service=service)
        env = SimpleNamespace(runtime=runtime, clock=clock, backend=backend, closed=False)
        instances.append(env)
        return env
    yield make
    for env in instances:
        if not env.closed:
            env.runtime.close()


def close(env):
    env.runtime.close()
    env.closed = True


def devices(env, second=0, *, stove=True, air=False, level="good", control=None, owner="homevis", mutate=None):
    env.clock.now = BASE + second
    snapshot = sample_devices(env.clock())
    snapshot["items"][0].update(is_on=stove, current_state={"state": "on" if stove else "off", "level": 5 if stove else 0, "temperature": 90.0})
    snapshot["items"].append(purifier(env.clock(), on=air, level=level, control=control, owner=owner))
    if mutate:
        mutate(snapshot)
    env.backend.snapshot = deepcopy(snapshot)
    env.runtime.ingest_device_states(snapshot)
    env.runtime.advance()


def rows(env, scenario="cooking_air_clean"):
    return [r for r in env.runtime.outbox.rows() if r["source"].get("scenario") == scenario]


def owned_on(env):
    devices(env)
    env.runtime.dispatch_mock_once()
    row, = rows(env)
    assert row["status"] == "accepted"
    return {"publisher": "api", "commandId": row["response"]["actions"][0]["commandId"]}


def presence(env, second, *, present=False, room=None, confidence=.95, valid=11, **extra):
    env.clock.now = BASE + second
    raw = {"resultId": f"sense-{second}", "observedAt": iso_time(env.clock()), "room": room,
           "present": present, "confidence": confidence, "validSec": valid, **extra}
    env.runtime.ingest_location(normalize_result(raw))
    env.runtime.advance()


def qualify_away(env, start=0):
    for second in range(start, start + 601, 10):
        presence(env, second)


@pytest.mark.parametrize("level", ["good", "normal", "bad"])
def test_purifier_quality_preserved_without_pm_thresholds(home, level):
    env = home()
    devices(env, level=level)
    parsed = purifier_state(env.runtime.devices["air_purifier"].raw, BASE, 20)
    assert parsed["quality"] == {"level": level, "pm25": 12.3, "pm10": 23.4, "co2": 500}
    assert len(rows(env)) == 1  # Cooking ON is independent of PM thresholds.


@pytest.mark.parametrize("change", ["offline", "stale", "old_air", "missing_level", "bad_pm", "missing_device"])
def test_invalid_purifier_blocks_automation(home, change):
    env = home()
    def mutate(snapshot):
        air = snapshot["items"][-1]
        if change == "offline": air["online"] = False
        if change == "stale": air["updatedAt"] = iso_time(BASE - 21)
        if change == "old_air": air["current_state"]["reportedAt"] = iso_time(BASE - 21)
        if change == "missing_level": air["current_state"]["airQuality"].pop("level")
        if change == "bad_pm": air["current_state"]["airQuality"]["pm25"] = -1
        if change == "missing_device": snapshot["items"].pop()
    devices(env, mutate=mutate)
    assert not rows(env)


def test_on_once_per_cooking_episode_and_restart(home):
    env = home()
    devices(env)
    first = rows(env)[0]["payload"]
    env.runtime.dispatch_mock_once()
    for t in range(1, 5): devices(env, t)
    assert len(rows(env)) == 1
    close(env)
    env = home()
    devices(env, 5)
    assert rows(env)[0]["payload"] == first and len(rows(env)) == 1


def test_already_on_does_not_request_on(home):
    env = home()
    devices(env, air=True)
    assert not rows(env)


@pytest.mark.parametrize("level", ["good", "normal"])
def test_off_only_after_owned_on_off_transition_and_clean_hold(home, level):
    env = home()
    control = owned_on(env)
    for t in range(1, 31): devices(env, t, stove=False, air=True, level=level, control=control)
    assert len(rows(env)) == 1
    devices(env, 31, stove=False, air=True, level=level, control=control)
    env.runtime.dispatch_mock_once()
    assert [r["payload"]["actions"][0]["action"] for r in rows(env)] == ["on", "off"]
    assert rows(env)[1]["status"] == "accepted"
    assert rows(env)[1]["source"]["details"]["ownership_confirmed"]


@pytest.mark.parametrize("change", ["system", "user", "unknown", "wrong_command", "bad_quality", "manual_intent"])
def test_no_off_for_ambiguous_or_other_owners(home, change):
    env = home()
    control = owned_on(env)
    if change in {"system", "user"}: control = {"publisher": change}
    if change == "unknown": control = None  # Actual v0.7 GET: lastControl is removed.
    if change == "wrong_command": control["commandId"] = "some-other-command"
    if change == "manual_intent": env.runtime.home_automation.note_manual_control({"device": "air_purifier", "action": "on"}, BASE + 1)
    for t in range(1, 34): devices(env, t, stove=False, air=True, level="bad" if change == "bad_quality" else "good", control=control)
    assert len(rows(env)) == 1


def test_missing_actual_application_cannot_be_treated_as_ownership(home):
    env = home()
    owned_on(env)
    for t in range(1, 34): devices(env, t, stove=False, air=False)
    assert len(rows(env)) == 1


def test_case_a_embedded_reversal_is_not_solved_by_repeated_on(home):
    env = home()
    control = owned_on(env)
    devices(env, 1, air=True, control=control)
    # Adversarial embedded policy: good => OFF. AI has no firmware hold contract.
    for t in range(2, 6): devices(env, t, air=False, control={"publisher": "system"})
    assert len(rows(env)) == 1 and not env.runtime.devices["air_purifier"].raw["is_on"]
    assert any(d.get("reason") == "purifier_on_not_maintained_priority_hold_contract_missing" for d in env.runtime.diagnostics)


def test_no_off_on_silence_or_clean_interval_gap(home):
    env = home()
    control = owned_on(env)
    devices(env, 1, stove=False, air=True, control=control)
    env.clock.now = BASE + 40
    env.runtime.advance()
    devices(env, 41, stove=False, air=True, control=control)
    assert len(rows(env)) == 1


def test_same_id_retry_after_lost_response(home):
    env = home()
    devices(env)
    first = rows(env)[0]["payload"]
    env.backend.fail_after_accept = True
    env.runtime.dispatch_mock_once()
    assert rows(env)[0]["status"] == "pending"
    devices(env, 2)
    env.runtime.dispatch_mock_once()
    assert rows(env)[0]["payload"] == first
    assert rows(env)[0]["response"]["duplicate"] and len(env.backend.accepted) == 1


def test_whole_home_scope_unconfirmed_blocks_even_long_absence(home):
    env = home()
    qualify_away(env)
    assert not rows(env, "away_all_off")


def test_away_exact_interval_empty_actions_and_backend_expansion(home):
    env = home(whole_home_presence_verified=True)
    env.backend.snapshot["items"].append(purifier(on=True))
    for t in range(0, 600, 10): presence(env, t)
    assert not rows(env, "away_all_off")
    presence(env, 600)
    request = rows(env, "away_all_off")[0]["payload"]
    assert request["actions"] == [] and "room" not in request and request["confidence"] == .95
    env.runtime.dispatch_mock_once()
    result = rows(env, "away_all_off")[0]
    assert result["status"] == "accepted"
    assert {a["device"] for a in result["response"]["actions"]} == {"stove", "air_purifier"}
    assert env.runtime.outbox.get_metadata("away_restore_lock")


@pytest.mark.parametrize("change", ["unknown", "one_room", "low_confidence", "diagnostic"])
def test_uncertain_or_partial_absence_never_qualifies(home, change):
    env = home(whole_home_presence_verified=True)
    for t in range(0, 611, 10):
        presence(env, t, room="unknown" if change == "unknown" else ("room" if change == "one_room" else None),
                 confidence=.4 if change == "low_confidence" else .95, **({"reason": "node_offline"} if change == "diagnostic" else {}))
    assert not rows(env, "away_all_off")


def test_absence_silence_duplicate_and_restart_never_fill_time(home):
    env = home(whole_home_presence_verified=True)
    presence(env, 0)
    env.clock.now = BASE + 601
    env.runtime.advance()
    assert not rows(env, "away_all_off")
    close(env)
    env = home(whole_home_presence_verified=True)
    presence(env, 602)
    assert not rows(env, "away_all_off")


def test_away_episode_persists_until_presence_not_uncertainty(home):
    env = home(whole_home_presence_verified=True)
    qualify_away(env)
    env.runtime.dispatch_mock_once()
    close(env)
    env = home(whole_home_presence_verified=True)
    presence(env, 610)
    assert len(rows(env, "away_all_off")) == 1
    presence(env, 620, present=True, room="kitchen")
    assert not env.runtime.home_automation.away_active
    assert env.runtime.outbox.get_metadata("away_restore_lock")
    qualify_away(env, start=630)
    assert len(rows(env, "away_all_off")) == 2


def test_case_b_embedded_bad_air_reactivation_is_reported_not_repeatedly_fought(home):
    env = home(whole_home_presence_verified=True)
    qualify_away(env)
    env.runtime.dispatch_mock_once()
    devices(env, 601, stove=False, air=True, level="bad", control={"publisher": "system"})
    assert len(rows(env, "away_all_off")) == 1 and not rows(env)
    assert any(d.get("reason") == "away_power_reported_on_priority_hold_contract_missing" for d in env.runtime.diagnostics)


def test_away_response_rejects_water_or_turning_on(home):
    env = home(whole_home_presence_verified=True)
    qualify_away(env)
    request = rows(env, "away_all_off")[0]["payload"]
    response = env.runtime.client.post_decision(request)
    for device, action in [("water_purifier", "off"), ("stove", "restore_power"), ("air_purifier", "on")]:
        bad = {**response.body, "actions": [{"device": device, "deviceId": "x", "action": action, "status": "sent"}]}
        with pytest.raises(ContractError): decision_response(202, bad, request)
    with pytest.raises(ContractError): decision_payload({**request, "actions": [{"device": "stove", "action": "turn_off"}]})
    with pytest.raises(ContractError): decision_payload({**request, "scenario": "some_other_scenario"})


@pytest.mark.parametrize("key,value", [("away_confirm_seconds", 0), ("away_min_confidence", 1.1),
                                     ("air_purifier_clean_hold_seconds", float("nan")), ("whole_home_presence_verified", "true")])
def test_new_config_validation(key, value):
    with pytest.raises(ValueError): HomeAutomationConfig(**{key: value})


def test_intermediate_bad_poll_breaks_clean_hold_before_tick(home):
    env = home()
    control = owned_on(env)
    for t in range(1, 21): devices(env, t, stove=False, air=True, control=control)
    # Two HTTP results can arrive before the next decision tick.
    bad = deepcopy(env.backend.snapshot)
    for item in bad["items"]: item["updatedAt"] = iso_time(BASE + 21)
    bad["items"][-1]["current_state"].update(reportedAt=iso_time(BASE + 21), airQuality={"level": "bad"})
    env.runtime.ingest_device_states(bad, fetched_at=BASE + 21)
    for t in range(22, 52): devices(env, t, stove=False, air=True, control=control)
    assert len(rows(env)) == 1
    devices(env, 52, stove=False, air=True, control=control)
    assert len(rows(env)) == 2


@pytest.mark.parametrize("change", ["stove_room", "air_room", "contradiction", "same_time_conflict"])
def test_queued_cooking_revalidates_latest_device_target_and_state(home, change):
    env = home()
    devices(env)
    def mutate(snapshot):
        if change == "stove_room": snapshot["items"][0]["room"] = "toilet"
        if change == "air_room": snapshot["items"][-1]["room"] = "kitchen"
        if change == "contradiction": snapshot["items"][0]["current_state"]["state"] = "off"
        if change == "same_time_conflict": snapshot["items"][-1]["current_state"]["mode"] = "manual"
    devices(env, 0 if change == "same_time_conflict" else 1, mutate=mutate)
    assert env.runtime._revalidate(rows(env)[0], env.clock()) is not None
    env.runtime.dispatch_mock_once()
    assert not env.backend.accepted


def test_new_cooking_episode_has_new_stable_identity(home):
    env = home()
    owned_on(env)
    devices(env, 1, stove=False)
    devices(env, 2, stove=True)
    assert len(rows(env)) == 2
    assert len({r["payload"]["decisionId"] for r in rows(env)}) == 2


def test_off_ownership_survives_restart_but_clean_hold_does_not(home):
    env = home()
    control = owned_on(env)
    devices(env, 1, stove=False, air=True, control=control)
    close(env)
    env = home()
    for t in range(2, 32): devices(env, t, stove=False, air=True, control=control)
    assert len(rows(env)) == 1
    devices(env, 32, stove=False, air=True, control=control)
    assert len(rows(env)) == 2


def test_away_confidence_is_minimum_observed_not_fixed_example(home):
    env = home(whole_home_presence_verified=True)
    for t in range(0, 601, 10): presence(env, t, confidence=.81 if t == 300 else .95)
    assert rows(env, "away_all_off")[0]["payload"]["confidence"] == .81


def test_return_after_away_cannot_reignite_even_with_old_reduction_record(home):
    env = home(whole_home_presence_verified=True)
    qualify_away(env)
    presence(env, 610, present=True, room="kitchen")
    env.runtime.outbox.set_metadata("stove_reduction", {"decisionId": "old", "requested_at": BASE - 1,
        "previous_level": 5, "requested_level": 4, "accepted_at": BASE})
    row = {"source_id": "restore", "source": {}, "payload": {"room": "kitchen", "actions": [
        {"device": "stove", "action": "restore_power"}]}}
    assert env.runtime._revalidate(row, env.clock()) == "away_shutdown_requires_explicit_user_confirmation"
    health = env.runtime.home_automation.health()
    assert health["stove_restore_locked"] and not health["away_active"]
    assert health["embedded_priority_hold_contract_available"] is False
