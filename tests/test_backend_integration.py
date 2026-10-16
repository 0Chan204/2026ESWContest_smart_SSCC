from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from examples.backend_integration_demo import FakeClock, run_demo
from src.control import ApplianceUpdate, CentralController, LightContext, ScenarioConfig, SensingUpdate
from src.control.automation_models import AutomationAction
from src.control.scenario_models import DeviceCommand, ScenarioAction
from src.integration import IntegrationConfig, IntegrationRuntime
from src.integration.backend_client import BackendClient, BackendError, HTTPResult
from src.integration.decision_mapper import DecisionMapper
from src.integration.mock_backend import MockBackend, sample_devices
from src.integration.outbox import Outbox
from src.integration.schemas import ContractError, decision_payload, decision_response, device_items, iso_time, measured_time
from src.integration.sensing import BehaviorObservation, join_behavior, location_observation
from src.integration.state_mapper import StateMapper


BASE = datetime(2026, 10, 17, 7, tzinfo=timezone(timedelta(hours=9))).timestamp()


def loc(at, location="kitchen", confidence=.95, **extra):
    return {"time": iso_time(at), "location": location, "location_confidence": confidence, **extra}


@pytest.fixture
def setup_runtime(tmp_path):
    runtimes = []

    def make(**overrides):
        config = IntegrationConfig(data_dir=tmp_path / str(len(runtimes)), allowed_lateness=0,
                                   room_is_bedroom=True, **overrides)
        clock = FakeClock(BASE)
        backend = MockBackend(clock, allow_null_confidence=config.rule_confidence_policy == "null")
        runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=clock)
        runtimes.append(runtime)
        return runtime, backend, clock

    yield make
    for runtime in runtimes:
        runtime.close()


def observe(runtime, backend, clock, offset, location="kitchen", behavior=None, snapshot=None):
    clock.now = BASE + offset
    backend.snapshot = snapshot or sample_devices(clock.now)
    runtime.ingest_device_states({"items": runtime.client.fetch_device_states()}, fetched_at=clock.now)
    runtime.ingest_location(loc(clock.now, location), behavior=behavior)
    return runtime.advance()


def ready_water(runtime, backend, clock):
    observe(runtime, backend, clock, 0)
    observe(runtime, backend, clock, 5)
    runtime.controller.device_commands.append(DeviceCommand(clock.now, 180, reason="measured test wake sequence"))
    runtime.collect_outputs(clock.now)
    return runtime.outbox.rows()[-1]


@pytest.mark.parametrize("raw,expected", [("kitchen", "kitchen"), ("toilet", "bathroom")])
def test_final_location_mapping(raw, expected):
    item = location_observation(loc(BASE, raw), BASE + 2, IntegrationConfig())
    assert item.sample.location == expected
    assert item.measured_at == BASE and item.received_at == BASE + 2
    assert item.sample.timestamp == BASE
    assert item.sample.activity == "unknown" and item.sample.activity_observed is False
    assert item.sample.activity_confidence is None
    assert item.sample.motion_state is None and item.sample.fall_detected is None


@pytest.mark.parametrize("raw", ["empty", "unknown", "r2", "r3", "r4", "living_room", "outside", "room"])
def test_unconfirmed_locations_never_become_outside(raw):
    item = location_observation(loc(BASE, raw, None), BASE, IntegrationConfig())
    assert not item.valid
    assert item.sample.location == "unknown"
    assert item.raw["location"] == raw and item.raw["location_confidence"] is None
    assert item.sample.confidence == 0 and not item.sample.detected


def test_room_requires_explicit_bedroom_configuration():
    assert location_observation(loc(BASE, "room"), BASE, IntegrationConfig(room_is_bedroom=True)).sample.location == "bedroom"
    assert IntegrationConfig().backend_room("bathroom") == "toilet"
    with pytest.raises(ValueError, match="unmapped_room"):
        IntegrationConfig().backend_room("bedroom")


@pytest.mark.parametrize("reason", ["node_offline:r3", "config_mismatch", "future_reason:detail"])
def test_reason_is_not_filtered_by_enum(reason):
    item = location_observation(loc(BASE, "unknown", None, reason=reason), BASE, IntegrationConfig())
    assert item.raw["reason"] == reason and not item.valid


@pytest.mark.parametrize("payload", [
    {"features": [1, 2]}, {"time": "2026-10-02T15:05:03", "location": "kitchen", "location_confidence": .9},
    loc(BASE, confidence=True), loc(BASE, confidence=float("nan")), loc(BASE, confidence=1.1),
])
def test_invalid_location_schema(payload):
    with pytest.raises(ValueError):
        location_observation(payload, BASE, IntegrationConfig())


def test_timezone_conversion_keeps_measurement():
    raw = {"time": "2026-10-02T15:05:03+09:00", "location": "kitchen", "location_confidence": .87}
    observation = location_observation(raw, BASE, IntegrationConfig())
    assert iso_time(observation.measured_at) == "2026-10-02T06:05:03+00:00"
    assert observation.raw == raw


def test_explicit_invalid_immediate_and_timeout_separate(setup_runtime):
    r, backend, clock = setup_runtime()
    observe(r, backend, clock, 0)
    observe(r, backend, clock, 5)
    clock.now = BASE + 6
    r.ingest_location(loc(clock.now, "unknown", None, reason="node_offline:r3"))
    result = r.advance()
    assert result.user_location == "kitchen"  # remembered, not currently observed
    assert result.sensor_uncertain and not result.observation_valid
    assert result.sensing_status == "invalid"
    clock.now += 20
    assert r.advance().sensing_status == "timeout"


def test_polling_duplicate_does_not_confirm_location_or_refresh_timestamp(setup_runtime):
    r, backend, clock = setup_runtime()
    observe(r, backend, clock, 0)
    payload = loc(BASE)
    for offset in (5, 10, 21):
        clock.now = BASE + offset
        r.ingest_location(payload)
        r.ingest_device_states(sample_devices(BASE), fetched_at=clock.now)
        result = r.advance()
    assert r.controller.realtime_engine.last_sensor_update == BASE
    assert r.controller.realtime_engine.last_appliance_update == BASE
    assert len(r.controller.realtime_engine._sensor_history) == 1
    assert result.sensing_status == "timeout" and result.appliance_stale
    assert result.user_location == "unknown"


@pytest.mark.parametrize("delay", [2, 3])
def test_sensing_and_ai_confirmation_delays_add_without_removing_guards(setup_runtime, delay):
    r, backend, clock = setup_runtime()
    # Physical transition at BASE, sensing emits its first confirmed result after delay.
    first = observe(r, backend, clock, delay, "toilet")
    assert first.user_location == "unknown"
    before = observe(r, backend, clock, delay + 4, "toilet")
    assert before.user_location == "unknown"
    confirmed = observe(r, backend, clock, delay + 5, "toilet")
    assert confirmed.user_location == "bathroom"
    assert confirmed.timestamp - BASE == delay + 5
    assert r.controller.realtime_engine.config.RETURN_CONFIRM_TIME == 5


def test_invalid_sensing_cannot_clear_existing_danger(setup_runtime):
    r, backend, clock = setup_runtime()
    for offset in range(0, 306, 5):
        result = observe(r, backend, clock, offset, "toilet")
    assert result.state == "DANGER"
    clock.now += 1
    r.ingest_location(loc(clock.now, "unknown", None, reason="config_mismatch"))
    assert r.advance().state == "DANGER"
    assert not r.last_decision.observation_valid


def test_missing_activity_score_is_zero_and_missing_power_cannot_trigger(setup_runtime):
    r, backend, clock = setup_runtime()
    for offset in range(0, 306, 5):
        observe(r, backend, clock, offset, "toilet")
    score = r.last_decision.confidence_decision
    assert score["features"]["activity"] == 0
    assert score["features"]["stove_power"] == 0
    assert score["confidence"] < score["threshold"]
    assert score["action"] is None
    assert r.controller.morning_water.dispense_count == 0
    assert all(r.missing_inputs.values())
    assert not any(row["payload"] for row in r.outbox.rows())


def test_behavior_join_requires_real_confidence_matching_time_room_and_expiry():
    location = location_observation(loc(BASE), BASE, IntegrationConfig())
    behavior = BehaviorObservation(BASE, BASE + 2, "kitchen", confidence=.7, activity="walking")
    joined = join_behavior(location, behavior, 1)
    assert joined.activity == "walking" and joined.activity_confidence == .7
    assert joined.activity_timestamp == BASE and joined.activity_valid_until == BASE + 2
    for bad in (replace(behavior, confidence=None), replace(behavior, location="bedroom"),
                replace(behavior, valid=False), replace(behavior, measured_at=BASE + 1),
                replace(behavior, measured_at=BASE - 3, valid_until=BASE - 1)):
        assert join_behavior(location, bad, 1).activity_observed is False


def test_behavior_expiry_prevents_tick_only_bedtime_action(setup_runtime):
    r, backend, clock = setup_runtime()
    r.controller.bedtime_light.config = ScenarioConfig(BEDTIME_LYING_SECONDS=3)
    behavior = BehaviorObservation(BASE, BASE + 2, "bedroom", .9, "lying")
    observe(r, backend, clock, 0, "room", behavior)
    clock.now += 3
    r.advance()
    assert not any(row["source"].get("scenario") == "bedtime_light_off" for row in r.outbox.rows())


def test_provided_device_schema_and_conservative_power_control_state():
    mapper = StateMapper(IntegrationConfig())
    item = device_items(sample_devices(BASE))[0]
    for owner in ("user", "homevis", None):
        result = mapper.map({**item, "control_state": owner}, BASE + 2)
        assert result.appliance.power_on is True
        assert result.appliance.power_watts is None
        assert result.appliance.control_state is None
        assert result.appliance.temperature_c is None
        assert result.raw["current_state"]["level"] == 5
        assert result.measured_at == BASE and result.fetched_at == BASE + 2
    validated = StateMapper(IntegrationConfig(level_to_watts={5: 1200}, temperature_is_celsius=True))
    assert validated.map(item, BASE).appliance.power_watts == 1200
    assert validated.map(item, BASE).appliance.temperature_c == 120


def test_water_readiness_requires_policy_and_not_is_on():
    item = sample_devices(BASE)["items"][2]
    default = StateMapper(IntegrationConfig())
    assert not default.water_ready(default.map(item, BASE), BASE)
    configured = StateMapper(IntegrationConfig(water_ready_states=("idle",)))
    assert configured.water_ready(configured.map(item, BASE), BASE)
    for status in ("busy", "error"):
        raw = deepcopy(item)
        raw["current_state"]["status"] = status
        assert not configured.water_ready(configured.map(raw, BASE), BASE)


@pytest.mark.parametrize("change", ["offline", "missing", "failed", "stale"])
def test_missing_device_information_never_fabricates_off(setup_runtime, change):
    r, backend, clock = setup_runtime()
    observe(r, backend, clock, 0)
    observe(r, backend, clock, 5)
    clock.now = BASE + (30 if change == "stale" else 6)
    payload = sample_devices(clock.now if change != "stale" else BASE)
    if change == "offline":
        payload["items"][0].update(online=False, is_on=False)
    if change == "missing":
        payload["items"] = payload["items"][1:]
    if change == "failed":
        r.poll_failed()
    else:
        r.ingest_device_states(payload)
    result = r.advance()
    assert result.appliance_on is True
    assert result.appliance_stale


def test_reordering_within_window_and_late_drop_after_tick(tmp_path):
    clock = FakeClock(BASE + 3)
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=2)
    r = IntegrationRuntime(config, BackendClient(config, MockBackend(clock)), clock=clock)
    try:
        r.ingest_location(loc(BASE + 2))
        r.ingest_location(loc(BASE + 1))
        r.advance()
        assert r.controller.realtime_engine.last_sensor_update == BASE + 1
        clock.now = BASE + 4
        r.advance()
        assert r.controller.realtime_engine.last_sensor_update == BASE + 2
        clock.now = BASE + 8
        r.advance()
        r.ingest_device_states(sample_devices(BASE + 3))
        r.advance()
        assert r.controller.realtime_engine.last_appliance_update is None
        assert any(d["code"] == "late_observation_dropped" for d in r.diagnostics)
    finally:
        r.close()


def test_conflicting_same_measurement_invalidates_until_newer(setup_runtime):
    r, backend, clock = setup_runtime()
    observe(r, backend, clock, 0)
    observe(r, backend, clock, 5)
    r.ingest_location(loc(clock.now, "toilet"))
    assert not r.advance().observation_valid
    assert observe(r, backend, clock, 6).observation_valid


def test_rules_without_confidence_are_blocked_and_automation_preserves_explanation(setup_runtime):
    r, backend, clock = setup_runtime()
    r.controller.device_commands.append(DeviceCommand(BASE, 180))
    action = r.controller.evaluate_light(LightContext("bedroom", False, True, BASE, presence_duration=5)).action
    assert action is not None
    r.collect_outputs(BASE)
    rows = r.outbox.rows()
    assert len(rows) == 2 and not r.controller.peek_outputs()
    assert any(row["diagnostic"] == "rule_confidence_contract_unconfirmed" for row in rows)
    automation = next(row for row in rows if row["source_id"].startswith("automation:"))
    assert automation["source"]["confidence"] == action.confidence
    assert automation["source"]["explanation"]["contributions"]
    assert automation["status"] == "blocked"


def test_explicit_automation_route_preserves_action_and_confidence(setup_runtime):
    r, backend, clock = setup_runtime(action_routes={
        ("light_auto_on", "turn_on"): ("test_light", "light", "turn_on", "bedroom")})
    action = r.controller.evaluate_light(LightContext("bedroom", False, True, BASE, presence_duration=5)).action
    r.collect_outputs(BASE)
    payload = r.outbox.rows()[0]["payload"]
    assert payload["confidence"] == action.confidence
    assert "contributions=" in payload["reason"]
    assert payload["room"] == "room" and payload["actions"][0]["action"] == "turn_on"
    bad = replace(r.config, action_routes={
        ("light_auto_on", "turn_on"): ("test_light", "light", "turn_off", "bedroom")})
    assert DecisionMapper(bad, r.controller.decision_history).map(action).diagnostic == "action_semantics_mismatch"


def test_outbox_failure_does_not_drain_any_outputs(setup_runtime, monkeypatch):
    r, _, clock = setup_runtime()
    command = DeviceCommand(BASE, 180)
    r.controller.device_commands.append(command)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(r.outbox, "save_batch", fail)
    with pytest.raises(OSError):
        r.collect_outputs(BASE)
    assert r.controller.peek_outputs() == [command]


def test_water_wire_payload_uses_amount_reason_and_weather(setup_runtime):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",))
    row = ready_water(r, backend, clock)
    body = row["payload"]
    assert body["confidence"] is None
    assert body["actions"] == [{"device": "water_purifier", "action": "dispense", "amountMl": 180}]
    assert body["scenario"] == "water_dispense" and body["weatherBriefing"]
    assert body["reason"] == "measured test wake sequence"
    assert "kind" not in body and "message_id" not in body
    r.dispatch_mock_once()
    saved = r.outbox.rows()[-1]
    assert saved["status"] == "accepted" and saved["http_status"] == 202
    assert saved["response"]["actions"][0]["status"] == "sent"
    assert saved["response"]["feedback"] is None
    assert saved["response"]["weather"]["text"]
    assert saved["diagnostic"] == "execution_ack_not_provided"


def test_timeout_retries_same_id_body_and_handles_duplicate_acceptance(setup_runtime):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",))
    first = ready_water(r, backend, clock)
    backend.fail_after_accept = True
    r.dispatch_mock_once()
    assert r.outbox.rows()[-1]["status"] == "pending"
    clock.now += r.config.retry_interval
    r.dispatch_mock_once()
    saved = r.outbox.rows()[-1]
    posts = [body for method, _, body in backend.requests if method == "POST"]
    assert len(posts) == 2 and posts[0] == posts[1]
    assert saved["payload"] == first["payload"]
    assert saved["http_status"] == 200 and saved["response"]["duplicate"]
    assert len(backend.accepted) == 1


@pytest.mark.parametrize("status", ["rejected", "failed"])
def test_partial_failure_is_not_replayed_as_new_decision(setup_runtime, status):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",))
    ready_water(r, backend, clock)
    backend.action_status = status
    r.dispatch_mock_once()
    row = r.outbox.rows()[-1]
    assert row["status"] == "accepted_partial"
    assert row["response"]["actions"][0]["message"] == "mock failure"
    clock.now += 3
    r.dispatch_mock_once()
    assert sum(method == "POST" for method, _, _ in backend.requests) == 1


def test_response_identity_and_per_action_status_validation(setup_runtime):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",))
    row = ready_water(r, backend, clock)
    response = r.client.post_decision(row["payload"])
    assert decision_response(202, response.body, row["payload"])["eventId"]
    for bad in ({**response.body, "decisionId": "wrong"}, {**response.body, "actions": []}):
        with pytest.raises(ContractError):
            decision_response(202, bad, row["payload"])
    with pytest.raises(ContractError):
        decision_response(200, response.body, row["payload"])


def test_old_commands_expire_and_revalidation_checks_current_location(setup_runtime):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",))
    ready_water(r, backend, clock)
    observe(r, backend, clock, 6, "toilet")
    r.dispatch_mock_once()
    assert r.outbox.rows()[-1]["diagnostic"] == "user_not_confirmed_in_kitchen"
    clock.now += 20
    r.dispatch_mock_once()
    assert r.outbox.rows()[-1]["status"] == "expired"
    assert not backend.accepted


def test_restart_reuses_inflight_payload_and_keeps_water_reservation(tmp_path):
    config = IntegrationConfig(data_dir=tmp_path, rule_confidence_policy="null")
    controller = CentralController(confidence_data_dir=tmp_path / "controller")
    command = DeviceCommand(BASE, 180)
    mapped = DecisionMapper(config, controller.decision_history).map(command)
    box = Outbox(config.outbox_path, "mock")
    box.save_batch([mapped], BASE, 15)
    box.reserve_water("2026-10-17", 1)
    box.update(mapped.source_id, status="sending", attempts=1)
    box.close()
    clock = FakeClock(BASE + 3)
    runtime = IntegrationRuntime(config, BackendClient(config, MockBackend(clock)), clock=clock)
    try:
        row = runtime.outbox.rows()[0]
        assert row["status"] == "pending" and row["attempts"] == 1
        assert row["payload"] == mapped.payload
        runtime._restore_reservation(clock.now)
        assert runtime.controller.morning_water.dispense_count == 1
        assert runtime.controller.morning_water.morning_water_dispensed
    finally:
        runtime.close()


def test_mock_live_outbox_separation(tmp_path):
    mock = IntegrationConfig(data_dir=tmp_path)
    live = IntegrationConfig(data_dir=tmp_path, mode="live", base_url="https://example.invalid")
    assert mock.outbox_path != live.outbox_path
    box = Outbox(mock.outbox_path, "mock")
    box.close()
    with pytest.raises(ValueError, match="mismatch"):
        Outbox(mock.outbox_path, "live")


def test_fall_backend_stages_are_recorded_but_not_sent_and_restore_suppressed(setup_runtime):
    r, backend, clock = setup_runtime(rule_confidence_policy="null")
    for offset in (0, 5, 10, 30):
        behavior = BehaviorObservation(BASE + offset, BASE + offset + 10, "bathroom", .95,
                                       "lying", "still", True)
        observe(r, backend, clock, offset, "toilet", behavior)
    assert r.outbox.fall_incident()["started_at"] == BASE
    fall_rows = [row for row in r.outbox.rows() if row["source"].get("scenario") == "bathroom_fall"]
    assert fall_rows and all(row["payload"] is None for row in fall_rows)
    assert all("backend_managed_fall" in row["diagnostic"] for row in fall_rows)
    restore = AutomationAction("restore", clock.now, "kitchen_return_restore", .99, "stove", "restore_power", {})
    r.controller.automation_actions.append(restore)
    r.collect_outputs(clock.now)
    assert r.outbox.rows()[-1]["diagnostic"] == "emergency_active:restore_suppressed"
    assert not backend.accepted


@pytest.mark.parametrize("owner,power_on", [("homevis", True), ("homevis", False), ("user", False), (None, False)])
def test_integration_never_infers_restore_from_owner_or_off(setup_runtime, owner, power_on):
    r, backend, clock = setup_runtime()
    for offset in (0, 5):
        snapshot = sample_devices(BASE + offset)
        snapshot["items"][0].update(control_state=owner, is_on=power_on)
        observe(r, backend, clock, offset, snapshot=snapshot)
    assert not r.controller.realtime_engine.automatic_restore_enabled
    assert r.controller.realtime_engine._appliance.power_on is power_on
    assert not any(row["source"].get("action") == "restore_power" for row in r.outbox.rows())


def test_network_wait_does_not_block_tick(tmp_path):
    entered, release = Event(), Event()

    class SlowBackend(MockBackend):
        def request(self, *args):
            entered.set()
            release.wait(2)
            return super().request(*args)

    clock = FakeClock(BASE)
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0)
    runtime = IntegrationRuntime(config, BackendClient(config, SlowBackend(clock)), clock=clock)
    try:
        runtime.run_once()
        assert entered.wait(1)
        clock.now += 30
        assert runtime.run_once().sensing_status == "timeout"
    finally:
        release.set()
        runtime.close()


def test_llm_none_does_not_import_optional_model_dependencies():
    script = ("import sys; from src.llm.factory import create_llm; assert create_llm('none') is None; "
              "assert not any(m in sys.modules for m in ('torch','transformers','google.genai'))")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_mock_demos_distinguish_location_only_from_synthetic_behavior(tmp_path):
    location_only = run_demo(tmp_path / "location")
    assert location_only["posts"] == 0 and all(location_only["missing_inputs"].values())
    paired = run_demo(tmp_path / "behavior", with_mock_behavior=True)
    assert paired["device_queries"] == 5 and paired["posts"] == 1
    water = next(d for d in paired["decisions"] if d["payload"] and d["payload"]["scenario"] == "water_dispense")
    assert water["status"] == "accepted"
    assert water["payload"]["confidence"] is None
    assert water["payload"]["actions"][0]["amountMl"] == 180


def test_repeated_invalid_messages_are_not_message_silence(setup_runtime):
    r, backend, clock = setup_runtime()
    observe(r, backend, clock, 0)
    payload = loc(BASE + 1, "unknown", None, reason="node_offline:r3")
    clock.now = BASE + 1
    r.ingest_location(payload)
    r.advance()
    clock.now = BASE + 30
    r.ingest_location(payload)
    r.advance()
    health = r.sensing_health()
    assert health["status"] == "invalid"
    assert health["measurement_stale"] and not health["message_timeout"]
    assert health["reason"] == "node_offline:r3" and health["raw_confidence"] is None
    clock.now += 20
    assert r.sensing_health()["message_timeout"]


def test_repeated_valid_messages_report_stale_measurement_not_transport_timeout(setup_runtime):
    r, backend, clock = setup_runtime()
    observe(r, backend, clock, 0)
    clock.now += 30
    r.ingest_location(loc(BASE))
    r.advance()
    health = r.sensing_health()
    assert health["status"] == "stale_measurement"
    assert not health["message_timeout"]


def test_default_reordering_delay_adds_to_confirmation(tmp_path):
    clock = FakeClock(BASE)
    config = IntegrationConfig(data_dir=tmp_path)
    runtime = IntegrationRuntime(config, BackendClient(config, MockBackend(clock)), clock=clock)
    try:
        for elapsed in (3, 7, 8):
            clock.now = BASE + elapsed
            runtime.ingest_location(loc(clock.now, "toilet"))
            assert runtime.advance().user_location == "unknown"
        clock.now = BASE + 10
        assert runtime.advance().user_location == "bathroom"
        assert runtime.last_decision.timestamp == BASE + 8
        assert runtime.outbox.audits("location_applied")[-1]["processed_at"] == BASE + 10
    finally:
        runtime.close()


def test_restart_does_not_reissue_reserved_morning_water(tmp_path):
    first = run_demo(tmp_path, with_mock_behavior=True)
    second = run_demo(tmp_path, with_mock_behavior=True)
    assert first["posts"] == 1 and second["posts"] == 0


def test_mixed_action_response_preserves_partial_results_and_weather():
    body = decision_payload({"decisionId": "dec-test", "scenario": "water_dispense", "confidence": .9,
                             "reason": "test fixture only", "timestamp": iso_time(BASE), "room": "kitchen",
                             "actions": [{"device": "water_purifier", "action": "dispense", "amountMl": 150},
                                         {"device": "light", "action": "turn_off"}]})
    response = {"decisionId": "dec-test", "scenario": "water_dispense", "confidence": .9,
                "receivedAt": iso_time(BASE + 1), "duplicate": True,
                "actions": [{"device": "light", "action": "turn_off", "status": "failed", "message": "offline"},
                            {"device": "water_purifier", "action": "dispense", "status": "sent", "commandId": "cmd-1"}],
                "weather": {"available": True, "text": "as of 06:00", "stale": True},
                "feedback": None, "eventId": "evt-1", "fallIncidentId": "fall-1"}
    parsed = decision_response(200, response, body)
    assert parsed == response
    assert parsed["actions"][0]["message"] == "offline"


def test_retry_limit_does_not_generate_another_id(setup_runtime, monkeypatch):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",), max_attempts=2)
    original = ready_water(r, backend, clock)["payload"]
    calls = []

    def fail(payload):
        calls.append(deepcopy(payload))
        raise BackendError("temporary server failure", retryable=True)

    monkeypatch.setattr(r.client, "post_decision", fail)
    for _ in range(3):
        r.dispatch_mock_once()
        clock.now += 2
    assert len(calls) == 2 and calls[0] == calls[1] == original
    assert r.outbox.rows()[-1]["status"] == "exhausted"


def test_behavior_validity_gap_does_not_count_as_continuous_lying(setup_runtime):
    r, backend, clock = setup_runtime()
    r.controller.bedtime_light.config = ScenarioConfig(BEDTIME_LYING_SECONDS=3)
    for offset in (0, 4):
        behavior = BehaviorObservation(BASE + offset, BASE + offset + 2, "bedroom", .9, "lying")
        observe(r, backend, clock, offset, "room", behavior)
    assert not any(row["source"].get("scenario") == "bedtime_light_off" for row in r.outbox.rows())


def test_invalid_result_interrupts_sleep_and_active_fall_without_clearing_risk(setup_runtime):
    r, backend, clock = setup_runtime()
    for offset in (0, 5):
        behavior = BehaviorObservation(BASE + offset, BASE + offset + 10, "bathroom", .95,
                                       "lying", "still", True)
        observe(r, backend, clock, offset, "toilet", behavior)
    assert r.controller.bathroom_decision.state == "FALL_CONFIRMED"
    observe(r, backend, clock, 6, "toilet")  # location-only does not imply recovery or stillness
    assert r.controller.bathroom_decision.state == "FALL_CONFIRMED"
    assert r.controller.bathroom_decision.sensor_uncertain


def test_unprocessed_new_location_blocks_queued_water(setup_runtime):
    r, backend, clock = setup_runtime(rule_confidence_policy="null", water_ready_states=("idle",))
    ready_water(r, backend, clock)
    clock.now += 1
    r.ingest_location(loc(clock.now, "toilet"))
    # The host has received a new observation but has not yet advanced the event-time cursor.
    r.dispatch_mock_once()
    assert r.outbox.rows()[-1]["diagnostic"] == "location_changed_or_invalid_before_confirmation"
    assert not backend.accepted
