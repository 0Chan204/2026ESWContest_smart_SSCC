"""Continuous runner and the verified HomeVIS backend v0.5 wire contract."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from threading import Event
import time
from types import SimpleNamespace

import pytest

from examples.backend_integration_demo import FakeClock
from src.alert_service import AlertService
from src.control import CentralController, LightContext, ScenarioConfig
from src.control.scenario_models import DeviceCommand
from src.integration import IntegrationRuntime
from src.integration.backend_client import BackendClient, BackendError, HTTPResult
from src.integration.backend_sensing import normalize_result
from src.integration.host import ContinuousHost, InstanceLock
from src.integration.mock_backend import sample_devices
from src.integration.mqtt_source import Incoming, InputRouter, MQTTSource
from src.integration.schemas import ContractError, decision_response, iso_time, measured_time
from src.integration.sensing import BehaviorObservation
from src.integration.settings import DEFAULT_CONFIG, load_settings
from src.integration.simulation import SimulationBackend, SimulationSource
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS


BASE = measured_time("2026-10-24T07:00:00+09:00")


@pytest.fixture
def live_contract(tmp_path):
    settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
    settings = replace(settings, integration=replace(settings.integration, allowed_lateness=0, async_alerts=False),
                       mqtt=replace(settings.mqtt, join_wait_seconds=0))
    clock = FakeClock(BASE)
    backend = SimulationBackend(clock)
    service = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio")
    runtime = IntegrationRuntime(settings.integration, BackendClient(settings.integration, backend),
                                 clock=clock, fall_alert_service=service)
    yield settings, runtime, backend, clock
    runtime.close()


def sense(runtime, clock, offset, room="room", activity="walking", fall=False):
    clock.now = BASE + offset
    runtime.ingest_location({"time": iso_time(clock()), "location": room, "location_confidence": .97},
        behavior=BehaviorObservation(clock(), clock() + 10, room, .85, activity,
                                     "still" if fall else "moving", fall))
    runtime.advance()


def test_default_settings_use_discovered_contract_and_hide_credentials(tmp_path):
    settings = load_settings(environ={"HOMEVIS_BACKEND_URL": "http://board:8000",
        "HOMEVIS_BACKEND_TOKEN": "private-backend-token", "HOMEVIS_MQTT_USERNAME": "ai",
        "HOMEVIS_MQTT_PASSWORD": "private-mqtt-password"}, data_dir=tmp_path)
    assert settings.integration.mode == "live"
    assert settings.mqtt.location_topic == "wifi/occupancy/state"
    assert settings.integration.fall_status_path == "/api/v1/fall-incidents/{incident_id}"
    assert settings.integration.rule_confidence_policy == "observed"
    assert settings.integration.headers["Authorization"] == "Bearer private-backend-token"
    assert "private-" not in repr(settings)


def test_toml_calibration_keys_become_integer_levels(tmp_path):
    path = tmp_path / "homevis.toml"
    path.write_text(DEFAULT_CONFIG.read_text(encoding="utf-8")
                    + '\n[backend.level_to_watts]\n"1" = 100.0\n"5" = 900.0\n', encoding="utf-8")
    settings = load_settings(path, environ={}, mode="mock", data_dir=tmp_path)
    assert settings.integration.level_to_watts == {1: 100.0, 5: 900.0}


def test_light_action_alias_preserves_engine_confidence(live_contract):
    _, runtime, _, _ = live_contract
    decision = runtime.controller.evaluate_light(LightContext(
        "room", False, True, BASE, presence_duration=10, location_confidence=.98,
        activity_confidence=.9, sensor_consistency=.98))
    result = runtime.decision_mapper.map(decision.action)
    assert result.payload["actions"] == [{"device": "light", "action": "on", "deviceId": "light-01"}]
    assert result.payload["confidence"] == decision.confidence
    assert result.payload["expiresAt"] == iso_time(BASE + 15)


def test_stove_reduction_maps_to_lower_level_not_off(live_contract):
    _, runtime, _, _ = live_contract
    service = runtime.controller.confidence_service
    decision = service.score(scenario="kitchen_leave_reduce_power", timestamp=BASE,
        device="stove", action_name="reduce_power", room="kitchen",
        features={key: 1 for key in service.config.SCENARIO_WEIGHTS["kitchen_leave_reduce_power"]})
    result = runtime.decision_mapper.map(decision.action, stove_level=5)
    assert result.payload["scenario"] == "stove_absence"
    assert result.payload["actions"] == [{"device": "stove", "deviceId": "induction-01", "action": "set_level", "level": 4}]
    assert runtime.decision_mapper.map(decision.action, stove_level=1).payload is None


def test_water_uses_device_idle_and_real_input_confidence(live_contract):
    _, runtime, backend, clock = live_contract
    for t, room, activity in ((0, "room", "lying"), (1, "room", "standing"),
                               (6, "room", "standing"), (7, "kitchen", "walking"), (12, "kitchen", "walking")):
        runtime.ingest_device_states(sample_devices(BASE + t), fetched_at=BASE + t)
        sense(runtime, clock, t, room, activity)
        runtime.dispatch_mock_once()
    rows = [r for r in runtime.outbox.rows() if r["payload"] and r["payload"]["scenario"] == "water_dispense"]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "accepted"
    assert row["payload"]["confidence"] == .85
    assert row["payload"]["actions"][0]["amountMl"] == 120
    assert row["payload"]["weatherBriefing"] is True
    assert row["source"]["confidence_basis"] == "minimum_observed_location_and_behavior_confidence"


def test_unscored_rule_does_not_fabricate_a_number(live_contract):
    _, runtime, _, _ = live_contract
    result = runtime.decision_mapper.map(DeviceCommand(BASE, 120))
    assert result.payload is None and result.diagnostic == "measured_rule_confidence_missing"


def test_fall_sends_once_without_device_state_and_backend_resolves_early(live_contract):
    _, runtime, backend, clock = live_contract
    sense(runtime, clock, 0, "toilet", "lying", True)
    runtime.dispatch_mock_once()
    row, = [r for r in runtime.outbox.rows() if r["source_id"].startswith("fall:")]
    assert row["payload"]["actions"] == []
    assert row["payload"]["confidence"] == .85
    assert row["status"] == "accepted"
    assert {a["action"] for a in row["response"]["actions"]} == {"turn_off", "blink"}
    incident = runtime.outbox.fall_incident()
    clock.now += 1
    runtime.receive_backend_fall_status({"incidentId": incident["fallIncidentId"], "status": "resolved",
        "stage": "user", "resolvedAt": iso_time(clock()), "confirmUrl": "https://example.invalid/?token=secret"})
    assert runtime.outbox.fall_incident() is None
    sense(runtime, clock, 30, "toilet", "lying", True)
    runtime.dispatch_mock_once()
    assert len(backend.accepted) == 1
    assert runtime.controller.bathroom_decision.state == "RESOLVED_BY_CAREGIVER"
    assert "secret" not in json.dumps(runtime.outbox.audits("backend_fall_status"))


def test_fall_backend_timers_are_not_duplicated_by_local_stages(live_contract):
    _, runtime, backend, clock = live_contract
    for t in (0, 5, 10, 20, 30, 60, 90):
        sense(runtime, clock, t, "toilet", "lying", True)
        runtime.dispatch_mock_once()
    assert len(backend.accepted) == 1
    assert not any(r["source"].get("event") in {"fall_caregiver_alert_requested", "fall_emergency_report_requested"}
                   for r in runtime.outbox.rows())
    assert len(runtime.outbox.audits("fall_user_alert")) == 1


def test_backend_whole_second_resolution_accepts_fractional_detection(live_contract):
    _, runtime, _, clock = live_contract
    sense(runtime, clock, .25, "toilet", "lying", True)
    runtime.dispatch_mock_once()
    incident = runtime.outbox.fall_incident()
    runtime.receive_backend_fall_status({"incidentId": incident["fallIncidentId"], "status": "pending",
        "stage": "user", "detectedAt": iso_time(clock())})
    clock.now += .5
    runtime.receive_backend_fall_status({"incidentId": incident["fallIncidentId"], "status": "resolved",
        "stage": "user", "resolvedAt": iso_time(int(clock()))})
    assert runtime.outbox.fall_incident() is None


def test_nonfinite_json_extra_field_cannot_crash_live_loop(live_contract):
    settings, runtime, _, clock = live_contract
    router = InputRouter(settings.mqtt, runtime)
    payload = {"time": iso_time(clock()), "location": "room", "location_confidence": .97,
               "extra": float("nan")}
    router.accept(Incoming(settings.mqtt.location_topic, json.dumps(payload).encode(), clock()))
    router.flush(clock())
    assert not router.pending
    assert runtime.controller.realtime_engine.sensing_invalid
    assert runtime.diagnostics[-1]["code"] == "input_rejected"


def test_backend_reported_is_not_treated_as_safe(live_contract):
    _, runtime, backend, clock = live_contract
    sense(runtime, clock, 0, "toilet", "lying", True)
    runtime.dispatch_mock_once()
    incident = runtime.outbox.fall_incident()
    clock.now += 90
    runtime.receive_backend_fall_status({"incidentId": incident["fallIncidentId"], "status": "auto_reported",
                                       "stage": "guardian", "reportedAt": iso_time(clock())})
    assert runtime.outbox.fall_incident()["backend_status"] == "auto_reported"
    assert len(backend.accepted) == 1


def test_fall_response_allows_backend_added_actions_but_validates_id(live_contract):
    _, runtime, backend, clock = live_contract
    sense(runtime, clock, 0, "toilet", "lying", True)
    runtime.dispatch_mock_once()
    row, = runtime.outbox.rows()
    assert decision_response(202, row["response"], row["payload"])
    with pytest.raises(ContractError):
        decision_response(202, {**row["response"], "fallIncidentId": None}, row["payload"])
    with pytest.raises(ContractError):
        decision_response(202, {**row["response"], "decisionId": "wrong"}, row["payload"])


@pytest.mark.parametrize("corrupt", ["status", "action_status", "action_device"])
def test_malformed_backend_response_is_a_handled_contract_error(live_contract, corrupt):
    _, runtime, _, clock = live_contract
    sense(runtime, clock, 0, "toilet", "lying", True)
    runtime.dispatch_mock_once()
    row, = runtime.outbox.rows()
    body = deepcopy(row["response"])
    if corrupt == "status":
        body["status"] = []
    elif corrupt == "action_status":
        body["actions"][0]["status"] = {}
    else:
        body["actions"][0]["device"] = []
    with pytest.raises(ContractError):
        decision_response(202, body, row["payload"])


def test_expired_response_is_terminal_not_retried(live_contract):
    _, runtime, backend, clock = live_contract
    mapped = runtime.decision_mapper.map(DeviceCommand(BASE, 120), evidence_confidence=.85)
    runtime.outbox.save_batch([mapped], BASE, 15)
    row, = runtime.outbox.rows()
    response = {"decisionId": mapped.payload["decisionId"], "scenario": "water_dispense", "confidence": .85,
                "receivedAt": iso_time(BASE + 20), "duplicate": False, "actions": [], "status": "expired"}
    parsed = decision_response(202, response, mapped.payload)
    runtime._finish_send(row, HTTPResult(202, parsed))
    assert runtime.outbox.rows()[0]["status"] == "expired"


def test_offline_unreported_extra_devices_do_not_break_entire_snapshot(live_contract):
    _, runtime, _, clock = live_contract
    snapshot = sample_devices(clock())
    snapshot["items"].append({"device": "fan", "deviceId": "fan-02", "room": "toilet",
        "online": False, "is_on": False, "current_state": None, "control_state": None, "updatedAt": None})
    runtime.ingest_device_states(snapshot)
    assert runtime._backend_ok
    assert runtime.devices["stove"].raw["is_on"]
    snapshot["items"][1].update(online=False, current_state=None, updatedAt=None)
    runtime.ingest_device_states(snapshot)
    assert "light" not in runtime.devices and "light" in runtime._device_faults


def test_restore_requires_observed_own_reduction_and_rejects_manual_changes(live_contract):
    _, runtime, _, clock = live_contract
    runtime.outbox.set_metadata("stove_reduction", {"requested_at": BASE, "accepted_at": BASE + 1,
                                                    "previous_level": 5})
    clock.now = BASE + 2
    item = sample_devices(clock())["items"][0]
    item["control_state"] = "homevis"
    item["current_state"]["level"] = 4
    observation = runtime._restore_evidence(runtime.state_mapper.map(item, clock()))
    assert observation.appliance.control_state == "HOMEVIS_REDUCED"
    item["control_state"] = "user"
    observation = runtime._restore_evidence(runtime.state_mapper.map(item, clock()))
    assert observation.appliance.control_state == "USER_OVERRIDE"
    assert runtime.outbox.get_metadata("stove_reduction") is None


def test_http_result_normalization_preserves_validity_and_does_not_infer_motion(live_contract):
    settings, runtime, _, clock = live_contract
    raw = {"resultId": "one", "observedAt": iso_time(BASE), "savedAt": iso_time(BASE),
           "room": "toilet", "present": True, "confidence": .9, "activity": "lying",
           "activityConfidence": .8, "validSec": 5}
    normalized = normalize_result(raw)
    assert normalized["backend_result"] == raw
    assert normalized["behavior"]["motion_state"] is None
    router = InputRouter(settings.mqtt, runtime)
    router.accept(Incoming(settings.mqtt.location_topic, json.dumps(raw).encode(), BASE))
    router.flush(BASE)
    runtime.advance()
    assert runtime.controller.realtime_engine._sensing.activity == "lying"
    clock.now += 6
    runtime.advance()
    assert runtime.sensing_health()["explicit_invalid"]
    assert "motion_state" in runtime.missing_inputs["bathroom_fall"]


def test_wifi_location_only_does_not_fabricate_fall_or_wake(live_contract):
    settings, runtime, _, clock = live_contract
    router = InputRouter(settings.mqtt, runtime)
    for offset in range(12):
        clock.now = BASE + offset
        payload = {"time": iso_time(clock()), "location": "room", "location_confidence": .97}
        router.accept(Incoming(settings.mqtt.location_topic, json.dumps(payload).encode(), clock()))
        router.flush(clock())
        runtime.advance()
    assert not runtime.controller.realtime_engine._sensing.activity_observed
    assert runtime.missing_inputs["morning_water"] == ["wake_activity"]
    assert runtime.outbox.fall_incident() is None


def test_join_buffers_reordered_behavior_and_bad_json_does_not_crash(live_contract):
    settings, runtime, _, clock = live_contract
    mqtt = replace(settings.mqtt, behavior_topic="test/behavior", join_wait_seconds=.25)
    router = InputRouter(mqtt, runtime)
    location = {"time": iso_time(BASE), "location": "room", "location_confidence": .97}
    router.accept(Incoming(mqtt.location_topic, json.dumps(location).encode(), BASE))
    behavior = {"time": iso_time(BASE), "valid_until": iso_time(BASE + 5), "location": "room",
                "confidence": .8, "activity": "standing"}
    router.accept(Incoming(mqtt.behavior_topic, json.dumps(behavior).encode(), BASE + .1))
    clock.now += .3
    router.flush(clock())
    runtime.advance()
    assert runtime.controller.realtime_engine._sensing.activity == "standing"
    router.accept(Incoming(mqtt.location_topic, b"not-json", clock()))
    assert runtime.controller.realtime_engine.sensing_invalid
    router.accept(Incoming(mqtt.location_topic, json.dumps(location).encode(), clock(), retained=True))
    assert len(runtime.outbox.audits("diagnostic")) >= 2


class FakeMQTT:
    def __init__(self):
        self.subscriptions = []
    def reconnect_delay_set(self, **kwargs): pass
    def connect_async(self, *args, **kwargs): pass
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def subscribe(self, topics):
        self.subscriptions.append(topics)
        return 0, len(self.subscriptions)


def test_mqtt_reconnect_resubscribes_and_queue_is_bounded(live_contract):
    settings, _, _, clock = live_contract
    fake = FakeMQTT()
    source = MQTTSource(replace(settings.mqtt, queue_size=1), client=fake, clock=clock)
    source.start()
    source._connect(fake, None, None, 0, None)
    source._disconnect(fake, None, None, 0, None)
    source._connect(fake, None, None, 0, None)
    assert len(fake.subscriptions) == 2
    assert fake.subscriptions[0] == [("wifi/occupancy/state", 1)]
    message = SimpleNamespace(topic=settings.mqtt.location_topic, payload=b"{}", retain=False)
    source._message(fake, None, message)
    source._message(fake, None, message)
    assert source.dropped == 1 and len(list(source.drain())) == 1
    source.close()


def test_instance_lock_rejects_second_runner_and_releases(tmp_path):
    with InstanceLock(tmp_path):
        with pytest.raises(RuntimeError, match="another HomeVIS"):
            with InstanceLock(tmp_path):
                pass
    with InstanceLock(tmp_path):
        pass


def test_no_default_run_deadline_and_shutdown_closes_resources(live_contract):
    settings, runtime, _, clock = live_contract
    source = SimulationSource(settings.mqtt, clock=clock)
    host = ContinuousHost(settings, runtime, source, clock=clock)
    closed = []
    runtime.close = lambda: closed.append(True)
    stop = Event()
    original_step = host.step
    def step():
        original_step()
        stop.set()
    host.step = step
    host.run(stop)
    assert closed and not source.connected
    status = json.loads(host.status_path.read_text(encoding="utf-8"))
    assert status["running"] is False
    # Restore cleanup since this fixture normally closes the real runtime.
    runtime.close = lambda: IntegrationRuntime.close(runtime)


def test_fall_timeout_restart_reuses_exact_payload_and_safe_guard_persists(tmp_path):
    settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
    config = replace(settings.integration, allowed_lateness=0, async_alerts=False)
    clock = FakeClock(BASE)
    backend = SimulationBackend(clock)
    client = BackendClient(config, backend)
    alert = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio")
    first = IntegrationRuntime(config, client, clock=clock, fall_alert_service=alert)
    try:
        sense(first, clock, 0, "toilet", "lying", True)
        backend.fail_after_accept = True
        first.dispatch_mock_once()
        original = deepcopy(first.outbox.rows()[0]["payload"])
        assert first.outbox.rows()[0]["status"] == "pending"
    finally:
        first.close()
    second = IntegrationRuntime(config, client, clock=clock, fall_alert_service=alert)
    try:
        clock.now = BASE + 120  # Regular command TTL has passed; recorded fall must still be sent.
        second.dispatch_mock_once()
        row = second.outbox.rows()[0]
        assert row["payload"] == original and row["response"]["duplicate"] is True
        assert len(backend.incidents) == 1
        incident = second.outbox.fall_incident()
        second.receive_backend_fall_status({"incidentId": incident["fallIncidentId"], "status": "resolved",
                                           "stage": "user", "resolvedAt": iso_time(clock())})
    finally:
        second.close()
    third = IntegrationRuntime(config, client, clock=clock, fall_alert_service=alert)
    try:
        sense(third, clock, 121, "toilet", "lying", True)
        third.dispatch_mock_once()
        assert third.outbox.fall_incident() is None and len(backend.incidents) == 1
        sense(third, clock, 122, "toilet", "walking", False)
        sense(third, clock, 123, "toilet", "lying", True)
        third.dispatch_mock_once()
        assert len(backend.incidents) == 2
    finally:
        third.close()


def test_slow_tts_does_not_block_detection_or_fall_post(tmp_path):
    settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
    config = replace(settings.integration, allowed_lateness=0)
    clock = FakeClock(BASE)
    backend = SimulationBackend(clock)
    entered, release = Event(), Event()
    service = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio")
    class SlowAlert:
        def handle(self, decision):
            entered.set()
            release.wait(5)
            return service.handle(decision)
    runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=clock, fall_alert_service=SlowAlert())
    try:
        sense(runtime, clock, 0, "toilet", "lying", True)
        runtime.dispatch_mock_once()
        sense(runtime, clock, 5, "toilet", "lying", True)
        assert entered.wait(1)
        sense(runtime, clock, 6, "toilet", "lying", True)
        assert runtime.controller.bathroom_decision.timestamp == BASE + 6 and len(backend.incidents) == 1
        release.set()
        deadline = time.monotonic() + 3
        while runtime._alert_worker.results.empty() and time.monotonic() < deadline:
            time.sleep(.01)
        runtime.run_once()
        announcements = [r for r in runtime.outbox.rows() if r["source"].get("type") == "Announcement"]
        assert len(announcements) == 1 and announcements[0]["payload"]["actions"] == []
        assert announcements[0]["payload"]["scenario"] != "fall_detected"
        assert announcements[0]["payload"]["announcement"]
    finally:
        release.set()
        runtime.close()


def test_disk_history_preserves_feedback_lookup_without_accumulating_ram(live_contract):
    _, runtime, _, _ = live_contract
    decision = runtime.controller.evaluate_light(LightContext(
        "room", False, True, BASE, presence_duration=10, location_confidence=.98,
        activity_confidence=.9, sensor_consistency=.98))
    history = runtime.controller.decision_history
    assert history.get(decision.action_id)["confidence"] == decision.confidence
    assert not hasattr(history, "_records")
    assert runtime.controller.feedback_manager.history is history
    result = runtime.controller.feedback_manager.apply_feedback(decision.action_id, "positive")
    assert result["weight_updated"] is True


def test_disk_history_import_preserves_latest_record_and_original_file(tmp_path):
    from src.integration.history import SQLiteDecisionHistory
    from src.integration.outbox import Outbox
    path = tmp_path / "decision_history.jsonl"
    original = '{"action_id":"old","confidence":0.5}\n{"action_id":"old","confidence":0.9}\n'
    path.write_text(original, encoding="utf-8")
    outbox = Outbox(tmp_path / "outbox.sqlite3", "mock")
    try:
        history = SQLiteDecisionHistory(outbox, path)
        assert history.get("old")["confidence"] == .9
        history.save({"action_id": "old", "confidence": .95})
        assert SQLiteDecisionHistory(outbox, path).get("old")["confidence"] == .95
        assert path.read_text(encoding="utf-8") == original
    finally:
        outbox.close()


def test_kitchen_warning_is_sent_as_announcement_without_extra_control(tmp_path):
    settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
    config = replace(settings.integration, allowed_lateness=0)
    clock = FakeClock(BASE)
    backend = SimulationBackend(clock)
    runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=clock,
        fall_alert_service=AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio"))
    try:
        for offset in range(33):
            clock.now = BASE + offset
            runtime.ingest_device_states(sample_devices(clock()))
            sense(runtime, clock, offset, "kitchen" if offset < 6 else "room")
        assert runtime._warning_context
        deadline = time.monotonic() + 3
        while runtime._alert_worker.results.empty() and time.monotonic() < deadline:
            time.sleep(.01)
        runtime.run_once()
        rows = [r for r in runtime.outbox.rows() if r["source"].get("type") == "WarningAnnouncement"]
        assert len(rows) == 1 and rows[0]["payload"]["actions"] == []
        assert rows[0]["payload"]["announcement"]
    finally:
        runtime.close()
