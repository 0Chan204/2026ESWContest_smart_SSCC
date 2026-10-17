"""Canonical contract, read-boundary compatibility, and real HTTP serialization.

The local HTTP server is a test double, not validation against a deployed backend.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
from threading import Thread

import pytest

from examples.backend_integration_demo import FakeClock, run_demo
from src.control import CentralController, LightContext, ScenarioConfig, SensingUpdate
from src.control.automation_models import AutomationAction
from src.control.scenario_models import DeviceCommand, ScenarioAction
from src.integration import IntegrationConfig, IntegrationRuntime
from src.integration.backend_client import BackendClient
from src.integration.decision_mapper import MappedDecision
# Readiness fixtures use a separate synthetic field; status=idle is never readiness.
from src.integration.mock_backend import MockBackend, ready_sample_devices as sample_devices
from src.integration.schemas import ContractError, decision_payload, decision_response, iso_time, measured_time
from src.integration.sensing import BehaviorObservation, join_behavior, location_observation
from src.integration.state_mapper import StateMapper


BASE = measured_time("2026-10-17T07:00:00+09:00")


def location(at, room="room"):
    return {"time": iso_time(at), "location": room, "location_confidence": .95}


@pytest.mark.parametrize("legacy,canonical", [("bedroom", "room"), ("bathroom", "toilet")])
def test_legacy_location_boundary_keeps_raw_and_joins_canonical_behavior(legacy, canonical):
    raw = location(BASE, legacy)
    observation = location_observation(raw, BASE + 2, IntegrationConfig())
    behavior = BehaviorObservation(BASE, BASE + 10, legacy, .8, "lying")
    sample = join_behavior(observation, behavior, 1)
    assert observation.raw == raw and observation.raw["location"] == legacy
    assert observation.measured_at == BASE and observation.received_at == BASE + 2
    assert sample.location == behavior.location == canonical
    assert sample.activity_observed and sample.activity_confidence == .8
    assert SensingUpdate(legacy, BASE).location == canonical
    assert LightContext(legacy, True, True, BASE).room == canonical


@pytest.mark.parametrize("state", ["outside", "unknown", "entrance", "living_room"])
def test_non_backend_internal_location_states_remain_available(state):
    assert SensingUpdate(state, BASE).location == state


def test_device_aliases_are_normalized_only_for_new_model_inputs(tmp_path):
    assert DeviceCommand(BASE, 120, device="water_dispenser").device == "water_purifier"
    action = AutomationAction("old-action", BASE, "light_auto_off", .8,
                              "bedroom_light", "turn_off", {})
    assert (action.device, action.room) == ("light", "room")
    scenario = ScenarioAction(BASE, "bedtime_light_off", "bedtime_detected", "turn_off",
                              "bedroom_light", "legacy input")
    assert (scenario.target, scenario.room) == ("light", "room")
    with pytest.raises(ValueError, match="target_room_mismatch"):
        ScenarioAction(BASE, "test", "test", "turn_off", "bathroom_light", "test", room="room")
    controller = CentralController(confidence_data_dir=tmp_path, water_dispenser_available=True)
    assert controller.water_purifier_available
    controller.water_dispenser_available = False
    assert not controller.water_purifier_available


@pytest.mark.parametrize("level", [0, 5, 99])
def test_level_is_a_stage_and_unconfirmed_units_and_ownership_are_preserved(tmp_path, level):
    clock = FakeClock(BASE)
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0)
    runtime = IntegrationRuntime(config, BackendClient(config, MockBackend(clock)), clock=clock)
    try:
        snapshot = sample_devices(BASE)
        stove = snapshot["items"][0]
        stove["current_state"]["level"] = level
        runtime.ingest_device_states(snapshot)
        result = runtime.advance()
        appliance = runtime.controller.realtime_engine._appliance
        assert appliance.level == result.level == result.to_dict()["level"] == level
        assert appliance.power_watts is None and appliance.temperature_c is None
        assert appliance.control_state is None
        assert runtime.devices["stove"].raw == stove
        assert "power_watts_unmeasured" in runtime.devices["stove"].diagnostics
        assert runtime.devices["light"].room == "room"
        assert not runtime.controller.realtime_engine.automatic_restore_enabled
    finally:
        runtime.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_water_state_keeps_original_history_and_requires_confirmed_readiness(legacy):
    raw = sample_devices(BASE)["items"][2]
    if legacy:
        raw["device"] = "water_dispenser"
    mapper = StateMapper(IntegrationConfig())
    result = mapper.map(raw, BASE + 1)
    assert result.raw == raw and result.raw["current_state"]["lastDispensedMl"] == 250
    assert not mapper.water_ready(result, BASE + 1)
    # Only an explicitly supplied test/deployment contract may grant readiness.
    confirmed = StateMapper(IntegrationConfig(water_ready_field="mock_readiness", water_ready_states=("ready",)))
    assert confirmed.water_ready(confirmed.map(raw, BASE + 1), BASE + 1)


def test_room_bedtime_uses_room_light_state_and_remains_guarded_without_routes(tmp_path):
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0)
    clock = FakeClock(BASE)
    controller = CentralController(confidence_data_dir=tmp_path / "controller",
                                   scenario_config=ScenarioConfig(BEDTIME_LYING_SECONDS=6))
    runtime = IntegrationRuntime(config, BackendClient(config, MockBackend(clock)),
                                 controller=controller, clock=clock)
    try:
        for offset in range(7):
            clock.now = BASE + offset
            snapshot = sample_devices(clock.now)
            snapshot["items"][1]["is_on"] = True
            runtime.ingest_device_states(snapshot)
            runtime.ingest_location(location(clock.now), behavior=BehaviorObservation(
                clock.now, clock.now + 10, "room", .95, "lying"))
            runtime.advance()
        row, = [r for r in runtime.outbox.rows() if r["source"].get("scenario") == "bedtime_light_off"]
        assert row["source"]["target"] == "light" and row["source"]["room"] == "room"
        assert row["diagnostic"] == "scenario_action_contract_unconfirmed"
        assert runtime.evaluated_devices["light"].room == runtime.last_decision.user_location == "room"
        assert row["payload"] is None
    finally:
        runtime.close()


@pytest.mark.parametrize("status", ["pending", "sending"])
def test_legacy_light_source_retries_without_rewriting_saved_id_or_body(tmp_path, status):
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0, action_routes={
        ("light_auto_on", "turn_on"): ("mock_presence", "light", "turn_on", "room"),
    })
    clock = FakeClock(BASE)
    backend = MockBackend(clock)
    client = BackendClient(config, backend)
    runtime = IntegrationRuntime(config, client, clock=clock)
    try:
        action = runtime.controller.evaluate_light(LightContext(
            "room", False, True, BASE, presence_duration=5)).action
        mapped = runtime.decision_mapper.map(action)
        old_source = deepcopy(mapped.source)
        old_source["device"] = "bedroom_light"
        old_source.pop("room")
        runtime.outbox.save_batch([MappedDecision(mapped.source_id, mapped.payload, None, old_source)], BASE, 15)
        # The backend accepted the original body before the old process stopped.
        client.post_decision(mapped.payload)
        runtime.outbox.update(mapped.source_id, status=status, attempts=1, next_attempt=BASE + 2)
        old_payload = deepcopy(mapped.payload)
    finally:
        runtime.close()
    runtime = IntegrationRuntime(config, client, clock=clock)
    try:
        for offset in (1, 6):
            clock.now = BASE + offset
            runtime.ingest_device_states(sample_devices(clock.now))
            runtime.ingest_location(location(clock.now))
            runtime.advance()
        runtime.dispatch_mock_once()
        row = next(r for r in runtime.outbox.rows() if r["source_id"] == mapped.source_id)
        posts = [body for method, _, body in backend.requests if method == "POST"]
        assert len(posts) == 2 and posts[0] == posts[1]
        assert row["source"] == old_source and row["payload"] == old_payload
        assert row["http_status"] == 200 and row["response"]["duplicate"] is True
        assert row["attempts"] == 2
    finally:
        runtime.close()


@pytest.mark.parametrize("light_on,room,expected", [
    (False, "room", "light_already_in_requested_state"),
    (True, "toilet", "device_room_mismatch"),
])
def test_bedtime_send_checks_actual_light_state_and_room(tmp_path, light_on, room, expected):
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0, rule_confidence_policy="null",
                               action_routes={
                                   ("bedtime_light_off", "turn_off"): ("mock_sleep", "light", "turn_off", "room"),
                               })
    clock = FakeClock(BASE)
    backend = MockBackend(clock, allow_null_confidence=True)
    controller = CentralController(confidence_data_dir=tmp_path / "controller",
                                   scenario_config=ScenarioConfig(BEDTIME_LYING_SECONDS=6))
    runtime = IntegrationRuntime(config, BackendClient(config, backend), controller=controller, clock=clock)
    try:
        for offset in range(7):
            clock.now = BASE + offset
            snapshot = sample_devices(clock.now)
            snapshot["items"][1].update(is_on=light_on, room=room)
            runtime.ingest_device_states(snapshot)
            runtime.ingest_location(location(clock.now), behavior=BehaviorObservation(
                clock.now, clock.now + 10, "room", .95, "lying"))
            runtime.advance()
        row, = [r for r in runtime.outbox.rows() if r["source"].get("scenario") == "bedtime_light_off"]
        assert runtime._revalidate(row, clock.now) == expected
        runtime.dispatch_mock_once()
        assert not backend.accepted
    finally:
        runtime.close()


@pytest.mark.parametrize("status", ["pending", "sending"])
def test_legacy_water_source_preserves_saved_request_across_restart(tmp_path, status):
    config = IntegrationConfig(data_dir=tmp_path, allowed_lateness=0,
                               water_ready_field="mock_readiness", water_ready_states=("ready",), rule_confidence_policy="null")
    clock = FakeClock(BASE)
    backend = MockBackend(clock, allow_null_confidence=True)
    client = BackendClient(config, backend)
    runtime = IntegrationRuntime(config, client, clock=clock)
    try:
        mapped = runtime.decision_mapper.map(DeviceCommand(BASE, 180))
        old_source = {**mapped.source, "device": "water_dispenser"}
        old_payload = {**mapped.payload, "decisionId": "dec-legacy-water"}
        runtime.outbox.save_batch([MappedDecision("legacy-water", old_payload, None, old_source)], BASE, 15)
        client.post_decision(old_payload)
        runtime.outbox.update("legacy-water", status=status, attempts=1, next_attempt=BASE + 2)
    finally:
        runtime.close()
    runtime = IntegrationRuntime(config, client, clock=clock)
    try:
        for offset in (1, 6):
            clock.now = BASE + offset
            runtime.ingest_device_states(sample_devices(clock.now))
            runtime.ingest_location(location(clock.now, "kitchen"))
            runtime.advance()
        runtime.dispatch_mock_once()
        row = next(r for r in runtime.outbox.rows() if r["source_id"] == "legacy-water")
        posts = [body for method, _, body in backend.requests if method == "POST"]
        assert len(posts) == 2 and posts[0] == posts[1]
        assert row["source"] == old_source and row["payload"] == old_payload
        assert row["payload"]["actions"][0]["amountMl"] == 180
        assert row["http_status"] == 200 and row["response"]["duplicate"] is True
    finally:
        runtime.close()


@pytest.fixture
def full_demo(tmp_path):
    result = run_demo(tmp_path / "demo", with_mock_behavior=True, start_at=BASE)
    return next(row for row in result["decisions"] if row["payload"] is not None)


def test_readme_full_request_and_mock_response_match_serialization(full_demo):
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for marker, value in (("mock-water-request", full_demo["payload"]),
                          ("mock-water-response", full_demo["response"])):
        block = re.search(r"<!-- " + marker + r" -->\s*```json\s*(.*?)\s*```", readme, re.S)
        assert block, f"missing complete JSON example: {marker}"
        assert json.loads(block.group(1)) == value
    assert full_demo["payload"]["actions"][0]["amountMl"] == 120


def test_rule_confidence_is_null_without_fabricating_a_score(tmp_path):
    config = IntegrationConfig(data_dir=tmp_path)
    clock = FakeClock(BASE)
    runtime = IntegrationRuntime(config, BackendClient(config, MockBackend(clock)), clock=clock)
    try:
        mapped = runtime.decision_mapper.map(DeviceCommand(BASE, 120))
        assert mapped.payload["confidence"] is None and mapped.diagnostic is None
        assert config.rule_confidence_policy == "null" and not config.action_routes
        assert ScenarioConfig().MORNING_WATER_AMOUNT_ML == 120
    finally:
        runtime.close()


@pytest.mark.parametrize("field,value", [("room", "bedroom"), ("device", "water_dispenser"),
                                         ("device", "stove")])
def test_wire_requests_reject_noncanonical_or_wrong_dispense_target(full_demo, field, value):
    payload = deepcopy(full_demo["payload"])
    if field == "room":
        payload[field] = value
    else:
        payload["actions"][0][field] = value
    with pytest.raises(ContractError):
        decision_payload(payload, allow_null_confidence=True)


def test_real_http_transport_uses_documented_paths_full_bodies_and_duplicate_response(full_demo):
    clock = FakeClock(BASE + 12)
    backend = MockBackend(clock, allow_null_confidence=True)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def respond(self, method):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))) or None
            received.append((method, self.path, dict(self.headers), body))
            response = backend.request(method, self.path, self.headers, body, 1)
            raw = json.dumps(response.body).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        # Real urllib transport to a TEST server; nullable rule confidence is the agreed contract.
        config = IntegrationConfig(mode="live", base_url=f"http://127.0.0.1:{server.server_port}")
        client = BackendClient(config)
        assert client.fetch_device_states() == backend.snapshot["items"]
        first = client.post_decision(full_demo["payload"])
        second = client.post_decision(full_demo["payload"])
        assert first.status == 202 and first.body == full_demo["response"]
        assert second.status == 200 and second.body["duplicate"] is True
        assert received[0][0:2] == ("GET", "/api/v1/ai/device-states")
        assert received[1][0:2] == ("POST", "/api/v1/ai/decisions")
        assert received[1][2]["Content-Type"] == "application/json"
        assert received[1][3] == received[2][3]
        assert json.loads(received[1][3]) == full_demo["payload"]
        for status in ("rejected", "failed"):
            backend.action_status = status
            payload = {**full_demo["payload"], "decisionId": f"test-{status}"}
            response = client.post_decision(payload)
            assert response.body["actions"][0]["status"] == status
            assert response.body["actions"][0]["message"] == "mock failure"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("http_status,duplicate", [(200, False), (202, True)])
def test_duplicate_flag_must_match_http_status(full_demo, http_status, duplicate):
    response = {**full_demo["response"], "duplicate": duplicate}
    with pytest.raises(ContractError):
        decision_response(http_status, response, full_demo["payload"])
