"""User-confirmed confidence, separate user/device state, and AI-owned fall decisions."""
from copy import deepcopy

import pytest

from examples.backend_integration_demo import FakeClock
from src.control import LightContext
from src.control.scenario_models import DeviceCommand
from src.integration import IntegrationConfig, IntegrationRuntime
from src.integration.backend_client import BackendClient
from src.integration.mock_backend import MockBackend, sample_devices, ready_sample_devices
from src.integration.schemas import decision_payload, iso_time, measured_time
from src.integration.sensing import BehaviorObservation
from src.integration.state_mapper import StateMapper


BASE = measured_time("2026-10-17T07:00:00+09:00")


@pytest.fixture
def runtime(tmp_path):
    clock = FakeClock(BASE)
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0, action_routes={
        ("light_auto_on", "turn_on"): ("mock_presence", "light", "turn_on", "room"),
    })
    backend = MockBackend(clock)
    runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=clock)
    yield runtime, backend, clock
    runtime.close()


def sense(runtime, clock, offset, activity=None, *, room="room", motion=None, fall=None):
    clock.now = BASE + offset
    behavior = None if activity is None else BehaviorObservation(
        clock.now, clock.now + 2, room, .83, activity, motion, fall)
    runtime.ingest_location({"time": iso_time(clock.now), "location": room,
                             "location_confidence": .97}, behavior=behavior)
    return runtime.advance()


def test_default_contract_preserves_computed_scores_and_only_unscored_rules_use_null(runtime):
    r, backend, clock = runtime
    action = r.controller.evaluate_light(LightContext(
        "room", False, True, BASE, presence_duration=5,
        location_confidence=.93, activity_confidence=.81)).action
    assert action is not None
    history = deepcopy(r.controller.decision_history.get(action.action_id))
    weights = deepcopy(r.controller.weight_manager.get_weights(r.controller.user_id, action.scenario))
    scored = r.decision_mapper.map(action)
    rule = r.decision_mapper.map(DeviceCommand(BASE, 120))
    assert scored.payload["confidence"] == action.confidence == history["confidence"]
    assert scored.source["explanation"] == history
    assert rule.payload["confidence"] is None
    assert rule.payload["scenario"] == "water_dispense" and rule.payload["weatherBriefing"] is True
    assert rule.payload["actions"] == [{"device": "water_purifier", "action": "dispense", "amountMl": 120}]
    assert decision_payload(rule.payload) == rule.payload
    # Transport keeps both kinds of confidence; backend acceptance does not invoke feedback.
    for result in (scored, rule):
        response = r.client.post_decision(result.payload)
        assert response.status == 202 and response.body["confidence"] == result.payload["confidence"]
    assert r.controller.decision_history.get(action.action_id) == history
    assert r.controller.weight_manager.get_weights(r.controller.user_id, action.scenario) == weights


@pytest.mark.parametrize("status", ["idle", "sitting", "lying"])
def test_user_status_never_grants_water_readiness_even_with_legacy_configuration(status):
    item = sample_devices(BASE)["items"][2]
    item["current_state"]["status"] = status
    for config in (IntegrationConfig(), IntegrationConfig(water_ready_states=(status,))):
        mapper = StateMapper(config)
        observation = mapper.map(item, BASE)
        assert not mapper.water_ready(observation, BASE)
        assert observation.raw == item
    with pytest.raises(ValueError, match="status is not readiness"):
        IntegrationConfig(water_ready_field="status", water_ready_states=(status,))


def test_readiness_test_double_is_independent_of_user_status():
    mapper = StateMapper(IntegrationConfig(water_ready_field="mock_readiness", water_ready_states=("ready",)))
    item = ready_sample_devices(BASE)["items"][2]
    for status in ("idle", "sitting", "lying"):
        item["current_state"]["status"] = status
        assert mapper.water_ready(mapper.map(item, BASE), BASE)
    item["current_state"].pop("mock_readiness")
    assert not mapper.water_ready(mapper.map(item, BASE), BASE)


def test_one_whole_snapshot_and_wifi_activity_update_do_not_overwrite_devices(runtime):
    r, backend, clock = runtime
    original = deepcopy(backend.snapshot)
    # Order is not identity. An extra unconfigured ID must not replace the real stove.
    extra = {**deepcopy(original["items"][0]), "deviceId": "another-stove", "is_on": False}
    backend.snapshot["items"] = [extra, *reversed(backend.snapshot["items"])]
    r.ingest_device_states({"items": r.client.fetch_device_states()})
    assert len(backend.requests) == 1
    assert backend.requests[0][0:2] == ("GET", "/api/v1/ai/device-states")
    for offset, activity in enumerate(("idle", "sitting", "lying")):
        sense(r, clock, offset, activity)
        user = r.controller.realtime_engine._sensing
        assert user.location == "room" and user.activity == activity
        assert user.activity_observed and user.activity_confidence == .83
        assert user.activity_timestamp == BASE + offset and user.activity_valid_until == BASE + offset + 2
        assert r.outbox.audits("location_applied")[-1]["sample"]["activity"] == activity
        for item in original["items"]:
            observation = r.evaluated_devices[item["device"]]
            assert observation.raw == item and observation.measured_at == BASE
        appliance = r.controller.realtime_engine._appliance
        assert appliance.power_on and appliance.level == 5
        assert appliance.power_watts is None and appliance.temperature_c is None
        assert r.devices["water_purifier"].raw["current_state"] == {"status": "idle", "lastDispensedMl": 250}
        assert not r.controller.water_purifier_available
    # A successful repeat GET updates receipt bookkeeping, not the device measurement time.
    clock.now = BASE + 21
    r.ingest_device_states({"items": r.client.fetch_device_states()})
    decision = r.advance()
    assert decision.appliance_stale
    assert r.devices["stove"].measured_at == BASE
    assert r.devices["stove"].raw["updatedAt"] == iso_time(BASE)
    assert backend.snapshot["items"][-1]["current_state"]["level"] == 5


def test_device_status_does_not_fabricate_sensing_activity(runtime):
    r, backend, clock = runtime
    backend.snapshot["items"][2]["current_state"]["status"] = "lying"
    r.ingest_device_states({"items": r.client.fetch_device_states()})
    sense(r, clock, 0)
    sample = r.controller.realtime_engine._sensing
    assert sample.activity == "unknown" and not sample.activity_observed
    assert sample.activity_confidence is None
    assert all(r.missing_inputs.values())


def test_ai_fall_start_escalation_and_recovery_are_recorded_without_backend_closure(tmp_path):
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0)
    clock = FakeClock(BASE)
    backend = MockBackend(clock)
    client = BackendClient(config, backend)
    r = IntegrationRuntime(config, client, clock=clock)
    try:
        for offset in range(37):
            r.ingest_device_states(sample_devices(BASE + offset), fetched_at=BASE + offset)
            sense(r, clock, offset, "lying" if offset <= 30 else "walking", room="toilet",
                  motion="still" if offset <= 30 else "moving", fall=offset <= 30)
            r.dispatch_mock_once()
        events = r.outbox.audits("fall_state_changed")
        assert [event["decision"]["state"] for event in events] == [
            "FALL_SUSPECTED", "FALL_CONFIRMED", "FALL_WARNING", "FALL_EMERGENCY", "RECOVERED"]
        assert [event["measured_at"] for event in events] == [BASE + t for t in (0, 5, 10, 30, 36)]
        assert r.controller.bathroom_decision.state == "RECOVERED"
        assert r.outbox.audits("evaluation")[-1]["fall_decision"]["state"] == "RECOVERED"
        assert all(event["backend_delivery"] == "fall_state_contract_unconfirmed" for event in events)
        assert all(event["backend_incident_status"] is None for event in events)
        incident = r.outbox.fall_incident()
        assert incident["started_at"] == BASE
        assert all(event["local_incident_id"] == incident["local_incident_id"] for event in events)
        assert not backend.accepted and not backend.requests
        assert all(row["payload"] is None for row in r.outbox.rows())
        r.advance()  # No duplicate transition on tick; recovery does not clear the incident latch.
        assert r.outbox.audits("fall_state_changed") == events
        assert r.outbox.fall_incident() == incident
    finally:
        r.close()
    r = IntegrationRuntime(config, client, clock=clock)
    try:
        r.advance()
        assert r.outbox.audits("fall_state_changed") == events
        assert r.outbox.fall_incident() == incident
    finally:
        r.close()
