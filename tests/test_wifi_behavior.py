"""Confirmed classifier labels plus a separate synthetic-envelope contract."""
from dataclasses import replace
import json

import pytest

from examples.backend_integration_demo import FakeClock
from src.alert_service import AlertService
from src.control import CentralController, ScenarioConfig, SensingUpdate
from src.control.bathroom_fall import BathroomFallScenario
from src.control.realtime_config import RealtimeConfig
from src.integration.backend_client import BackendClient
from src.integration.backend_sensing import normalize_result
from src.integration.config import IntegrationConfig
from src.integration.mqtt_source import Incoming, InputRouter, parse_behavior
from src.integration.runtime import IntegrationRuntime
from src.integration.schemas import iso_time, measured_time
from src.integration.sensing import join_behavior, location_observation
from src.integration.settings import load_settings
from src.integration.simulation import SimulationBackend
from src.integration.mock_backend import sample_devices
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS

BASE = measured_time("2026-10-26T07:00:00+09:00")


def envelope(offset=0, *, room="toilet", label="mock_lie", event_id=None,
             activity=None, motion=None, fall=None, location_confidence=.96, activity_confidence=.92):
    at = BASE + offset
    return {"mockContract": "homevis.behavior.v1", "resultId": f"mock-result-{offset}",
            "observedAt": iso_time(at), "room": room, "present": True,
            "confidence": location_confidence, "validSec": 10,
            "locationExplanation": "해당 구역의 특징이 가장 강함",
            "mockBehavior": {"time": iso_time(at), "valid_until": iso_time(at + 10),
                "location": room, "confidence": activity_confidence,
                "label": label, "eventId": event_id or (f"mock-event-{offset}" if label else None),
                "activity": activity, "motion_state": motion, "fall_detected": fall,
                "reason": "모델이 관측한 패턴 설명"}}


@pytest.fixture
def make_runtime(tmp_path):
    runtimes = []

    def make(*, restart=False, **overrides):
        settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
        config = replace(settings.integration, allowed_lateness=0, async_alerts=False,
                         mock_behavior_contract=True, light_on_seconds=100, **overrides)
        settings = replace(settings, integration=config, mqtt=replace(settings.mqtt, join_wait_seconds=0))
        clock = FakeClock(BASE)
        backend = SimulationBackend(clock)
        alert = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio")
        runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=clock, fall_alert_service=alert)
        router = InputRouter(settings.mqtt, runtime)
        runtimes.append(runtime)
        return settings, runtime, router, backend, clock

    yield make
    for runtime in runtimes:
        if not getattr(runtime, "_test_closed", False):
            runtime.close()


def close_for_restart(parts):
    parts[1].close()
    parts[1]._test_closed = True


def feed(parts, offset=0, *, raw=None, devices=False, **kwargs):
    settings, runtime, router, backend, clock = parts
    clock.now = BASE + offset
    if devices:
        runtime.ingest_device_states(sample_devices(clock.now))
    raw = envelope(offset, **kwargs) if raw is None else raw
    router.accept(Incoming(settings.mqtt.location_topic, json.dumps(raw).encode(), clock.now))
    router.flush(clock.now)
    runtime.advance(clock.now)
    return runtime.controller.bathroom_decision


def fall_rows(runtime):
    return [row for row in runtime.outbox.rows() if row["source_id"].startswith("fall:")]


def test_default_runner_polls_backend_and_mock_is_live_forbidden():
    assert load_settings(environ={}).sensing_source == "backend"
    with pytest.raises(ValueError, match="mock"):
        IntegrationConfig(mode="live", base_url="http://board:8000", mock_behavior_contract=True)
    with pytest.raises(ValueError, match="not permitted"):
        normalize_result(envelope())


def test_normal_explanations_and_independent_confidence_are_preserved():
    raw = envelope()
    normalized = normalize_result(raw, allow_mock_events=True)
    location = location_observation(normalized, BASE, IntegrationConfig())
    behavior = parse_behavior(normalized["behavior"], allow_mock_events=True)
    sample = join_behavior(location, behavior, 1)
    assert location.valid and sample.activity_observed
    assert sample.confidence == .96 and sample.activity_confidence == .92
    assert sample.location_reason == raw["locationExplanation"]
    assert sample.activity_reason == raw["mockBehavior"]["reason"]
    assert sample.activity_event == "lie_down" and sample.raw_activity == "mock_lie"
    assert sample.activity == "unknown" and sample.motion_state is None and sample.fall_detected is None
    assert sample.received_at == BASE and sample.activity_timestamp == BASE
    assert normalized["backend_result"] == raw


@pytest.mark.parametrize("error", ["node_offline:r3", "config_mismatch", "unknown_sensor_error"])
def test_errors_remain_errors_even_with_normal_explanation(error):
    raw = envelope()
    raw["locationError"] = error
    normalized = normalize_result(raw, allow_mock_events=True)
    assert not location_observation(normalized, BASE, IntegrationConfig()).valid
    raw.pop("locationError")
    raw["reason"] = error
    assert not location_observation(normalize_result(raw, allow_mock_events=True), BASE, IntegrationConfig()).valid


def test_unknown_legacy_reason_is_not_silently_reclassified_as_explanation():
    raw = {"observedAt": iso_time(BASE), "room": "room", "confidence": .95,
           "validSec": 10, "reason": "방 특징이 가장 강함"}
    assert not location_observation(normalize_result(raw), BASE, IntegrationConfig()).valid


@pytest.mark.parametrize("label", ["wake_up", "sleep", "낙상", "눕기", "NONE"])
def test_unverified_live_labels_never_become_events(label):
    raw = {"observedAt": iso_time(BASE), "room": "toilet", "confidence": .95,
           "validSec": 10, "activity": label, "activityConfidence": .95}
    normalized = normalize_result(raw)
    behavior = parse_behavior(normalized["behavior"])
    sample = join_behavior(location_observation(normalized, BASE, IntegrationConfig()), behavior, 1)
    assert not sample.activity_observed and sample.activity_event is None


def classifier_result(offset=0, *, label="get_up", room="room", confidence=.95):
    """Proposed binding to existing backend fields, not a captured producer packet."""
    return {"resultId": f"result-{offset}", "observedAt": iso_time(BASE + offset),
            "room": room, "present": True, "confidence": .96, "validSec": 10,
            "activity": label, "activityConfidence": confidence}


@pytest.mark.parametrize("label,event", [("none", None), ("fall", "fall"),
                                         ("lie_down", "lie_down"), ("get_up", "wake")])
def test_confirmed_labels_work_without_mock_permission(label, event):
    raw = classifier_result(label=label)
    normalized = normalize_result(raw)
    behavior = parse_behavior(normalized["behavior"])
    sample = join_behavior(location_observation(normalized, BASE, IntegrationConfig()), behavior, 1)
    assert sample.activity_observed and sample.activity_event == event
    assert sample.raw_activity == label and sample.activity == "unknown"
    assert sample.motion_state is None and sample.fall_detected is None
    assert sample.activity_confidence == .95 and sample.confidence == .96
    assert sample.activity_event_id.startswith("behavior-window:")
    assert sample.detected and sample.location == "room"


def test_classifier_window_identity_is_stable_across_polling_and_changed_prediction():
    raw = classifier_result()
    first = parse_behavior(normalize_result(raw)["behavior"])
    raw.update(resultId="other-database-id", savedAt=iso_time(BASE + 2), activity="fall")
    second = parse_behavior(normalize_result(raw)["behavior"])
    assert first.event_id == second.event_id
    assert first != second
    raw["observedAt"] = iso_time(BASE + 1)
    assert first.event_id != parse_behavior(normalize_result(raw)["behavior"]).event_id


@pytest.mark.parametrize("field,value", [("validSec", None), ("validSec", 0), ("activityConfidence", None)])
def test_label_without_required_evidence_never_fabricates_it(field, value):
    raw = classifier_result()
    raw[field] = value
    assert "behavior" not in normalize_result(raw)


@pytest.mark.parametrize("label", ["get_up", "fall", "lie_down"])
def test_confirmed_label_still_requires_fresh_result(make_runtime, label):
    parts = make_runtime()
    raw = classifier_result(label=label, room="toilet" if label != "get_up" else "room")
    raw["validSec"] = 1
    feed(parts, 2, raw=raw, devices=True)
    assert not fall_rows(parts[1]) and not morning_light_rows(parts[1])


def test_none_cannot_confirm_or_resolve_toilet_suspicion(make_runtime):
    parts = make_runtime()
    assert feed(parts, raw=classifier_result(label="lie_down", room="toilet")).candidate_only
    for second in range(1, 12):
        decision = feed(parts, second, raw=classifier_result(second, label="none", room="toilet"))
        assert decision.candidate_only and decision.state == "FALL_SUSPECTED"
        assert decision.unresponsive_seconds == 0
    assert not fall_rows(parts[1])


def test_none_cannot_resolve_explicit_fall(make_runtime):
    parts = make_runtime()
    feed(parts, raw=classifier_result(label="fall", room="toilet"))
    incident = parts[1].outbox.fall_incident()
    for second in range(1, 12):
        decision = feed(parts, second, raw=classifier_result(second, label="none", room="toilet"))
        assert decision.state != "RECOVERED"
    assert parts[1].outbox.fall_incident() == incident
    assert len(fall_rows(parts[1])) == 1


def test_backend_safe_then_fresh_none_rearms_for_a_new_fall(make_runtime):
    parts = make_runtime()
    feed(parts, raw=classifier_result(label="fall", room="toilet"))
    parts[1].dispatch_mock_once()
    record = parts[1].outbox.fall_incident()
    parts[4].now = BASE + 1
    parts[1].receive_backend_fall_status({"incidentId": record["fallIncidentId"], "status": "resolved",
                                         "resolvedAt": iso_time(BASE + 1)})
    feed(parts, 2, raw=classifier_result(2, label="fall", room="toilet"))
    assert len(fall_rows(parts[1])) == 1  # Persistent fall output must not immediately re-alarm.
    decision = feed(parts, 3, raw=classifier_result(3, label="none", room="toilet"))
    assert decision.state == "RESOLVED_BY_CAREGIVER"  # Not fabricated physical RECOVERED.
    feed(parts, 4, raw=classifier_result(4, label="fall", room="toilet"))
    assert len(fall_rows(parts[1])) == 2
    assert parts[1].outbox.fall_incident()["local_incident_id"] != record["local_incident_id"]


def morning_light_rows(runtime):
    return [r for r in runtime.outbox.rows() if r["source"].get("scenario") == "morning_light_on"]


def test_get_up_event_turns_on_morning_light_without_fabricating_posture(make_runtime):
    parts = make_runtime()
    feed(parts, raw=classifier_result(), devices=True)
    assert parts[1]._latest_received_sample.activity == "unknown"
    assert not parts[1].controller.bedtime_light._requested
    parts[1].dispatch_mock_once()
    row, = morning_light_rows(parts[1])
    assert row["status"] == "accepted"
    assert row["payload"]["scenario"] == "light_auto_on"
    assert row["payload"]["actions"] == [{"device": "light", "deviceId": "light-01", "action": "on"}]
    assert row["source"]["details"]["basis"] == "get_up_event"
    assert row["source"]["details"]["raw_activity"] == "get_up"
    assert not [r for r in parts[1].outbox.rows() if r["source"].get("type") == "DeviceCommand"]
    # none says nothing about posture, but valid kitchen occupancy still establishes dwell.
    for second in range(1, 7):
        feed(parts, second, raw=classifier_result(second, label="none", room="kitchen"), devices=True)
    parts[1].dispatch_mock_once()
    water, = [r for r in parts[1].outbox.rows() if r["source"].get("type") == "DeviceCommand"]
    assert water["status"] == "accepted" and water["payload"]["actions"][0]["amountMl"] == 120


@pytest.mark.parametrize("label", ["none", "lie_down", "fall"])
def test_other_classifier_labels_never_trigger_morning_light(make_runtime, label):
    parts = make_runtime()
    feed(parts, raw=classifier_result(label=label), devices=True)
    assert not morning_light_rows(parts[1])


@pytest.mark.parametrize("confidence", [.58, .89])
def test_get_up_below_central_wake_policy_does_not_control(make_runtime, confidence):
    parts = make_runtime()
    feed(parts, raw=classifier_result(confidence=confidence), devices=True)
    assert not morning_light_rows(parts[1])
    assert parts[1].controller.morning_water._wake_time is None


@pytest.mark.parametrize("change", ["left_room", "lie_down", "fall", "expired", "offline", "already_on"])
def test_event_light_revalidated_before_send(make_runtime, change):
    parts = make_runtime()
    feed(parts, raw=classifier_result(), devices=True)
    if change in {"left_room", "lie_down", "fall"}:
        feed(parts, 1, raw=classifier_result(1, label="none" if change == "left_room" else change,
                                           room="kitchen" if change == "left_room" else "room"), devices=True)
    elif change == "expired":
        for second in range(1, 12):
            feed(parts, second, raw=classifier_result(second, label="none"), devices=True)
    else:
        parts[4].now = BASE + 1
        snapshot = sample_devices(BASE + 1)
        snapshot["items"][1]["online" if change == "offline" else "is_on"] = change == "already_on"
        parts[1].ingest_device_states(snapshot)
        parts[1].advance()
    parts[1].dispatch_mock_once()
    assert morning_light_rows(parts[1])[0]["status"] != "accepted"


def test_none_preserves_but_does_not_extend_fresh_event_light_evidence(make_runtime):
    parts = make_runtime()
    feed(parts, raw=classifier_result(), devices=True)
    feed(parts, 1, raw=classifier_result(1, label="none"), devices=True)
    parts[1].dispatch_mock_once()
    row, = morning_light_rows(parts[1])
    assert row["status"] == "accepted"
    assert row["source"]["details"]["wake_valid_until"] == BASE + 10


def test_event_light_not_reissued_on_same_day_restart(make_runtime):
    parts = make_runtime()
    feed(parts, raw=classifier_result(), devices=True)
    parts[1].dispatch_mock_once()
    close_for_restart(parts)
    parts = make_runtime(restart=True)
    feed(parts, 1, raw=classifier_result(1), devices=True)
    assert len(morning_light_rows(parts[1])) == 1


def test_evening_get_up_not_morning_light(make_runtime):
    parts = make_runtime()
    offset = 12 * 3600
    feed(parts, offset, raw=classifier_result(offset), devices=True)
    assert not morning_light_rows(parts[1])


def test_get_up_policy_is_configurable_and_does_not_change_fall_thresholds(make_runtime):
    parts = make_runtime(scenario_config=ScenarioConfig(WAKE_EVENT_MIN_ACTIVITY_CONFIDENCE=.97))
    feed(parts, raw=classifier_result(confidence=.95), devices=True)
    assert not morning_light_rows(parts[1])
    feed(parts, 1, raw=classifier_result(1, confidence=.97), devices=True)
    assert len(morning_light_rows(parts[1])) == 1
    assert parts[1].controller.realtime_engine.config.MIN_CONFIDENCE == .6
    assert parts[1].config.scenario_config.TOILET_LYING_MIN_ACTIVITY_CONFIDENCE == .8


def test_get_up_with_explicit_fall_conflict_never_qualifies_wake(make_runtime):
    parts = make_runtime()
    raw = classifier_result()
    raw["fall_detected"] = True
    feed(parts, raw=raw, devices=True)
    assert not morning_light_rows(parts[1])
    assert parts[1].controller.morning_water._wake_time is None


def test_get_up_with_live_reorder_delay_can_send_fresh_event_light(make_runtime):
    parts = make_runtime()
    # Runner default holds measurements for 4s; the event must remain bounded by
    # its original validity even when a newer none result has already arrived.
    parts[1].config = replace(parts[1].config, allowed_lateness=4)
    for second in range(5):
        feed(parts, second, raw=classifier_result(second, label="get_up" if second == 0 else "none"), devices=True)
    parts[1].dispatch_mock_once()
    row, = morning_light_rows(parts[1])
    assert row["status"] == "accepted"


@pytest.mark.parametrize("interruption", ["lie_down", "left_room", "malformed"])
def test_buffered_interruption_cannot_be_hidden_by_later_none(make_runtime, interruption):
    parts = make_runtime()
    parts[1].config = replace(parts[1].config, allowed_lateness=4)
    feed(parts, raw=classifier_result(), devices=True)
    interrupted = classifier_result(1, label="lie_down" if interruption == "lie_down" else "none",
                                    room="kitchen" if interruption == "left_room" else "room")
    if interruption == "malformed":
        interrupted["activityConfidence"] = "invalid"
    feed(parts, 1, raw=interrupted, devices=True)
    for second in range(2, 5):
        feed(parts, second, raw=classifier_result(second, label="none"), devices=True)
    parts[1].dispatch_mock_once()
    if interruption == "malformed":
        # Transport invalidation now removes the pre-error wake sample before
        # a request can be generated, rather than blocking it only at dispatch.
        assert morning_light_rows(parts[1]) == []
        return
    row, = morning_light_rows(parts[1])
    assert row["status"] != "accepted"


def test_explicit_fall_uses_existing_backend_contract_once(make_runtime):
    parts = make_runtime()
    runtime = parts[1]
    result = feed(parts, label="mock_fall")
    assert result.state == "FALL_SUSPECTED" and not result.candidate_only
    runtime.dispatch_mock_once()
    row, = fall_rows(runtime)
    assert row["payload"]["scenario"] == "fall_detected" and row["payload"]["actions"] == []
    assert row["payload"]["confidence"] == .92 and row["status"] == "accepted"
    assert runtime.outbox.fall_incident()["fallIncidentId"]
    feed(parts, 1, raw=envelope(0, label="mock_fall"))
    assert len(fall_rows(runtime)) == 1 and len(parts[3].accepted) == 1


def test_toilet_lying_is_local_candidate_not_an_incident(make_runtime):
    parts = make_runtime()
    runtime = parts[1]
    decision = feed(parts)
    assert decision.state == "FALL_SUSPECTED" and decision.candidate_only
    assert decision.incident_id is None
    assert runtime.outbox.fall_incident() is None and not fall_rows(runtime)
    runtime.dispatch_mock_once()
    assert not parts[3].accepted
    audit, = runtime.outbox.audits("fall_state_changed")
    assert audit["backend_delivery"] == "local_suspicion_only"
    assert audit["decision"]["evidence"]["location_reason"]
    assert audit["decision"]["evidence"]["motion_state"] is None
    records = runtime.controller.decision_history.db.execute("SELECT record FROM decision_history").fetchall()
    assert any(json.loads(r[0]).get("candidate_only") is True for r in records)


def test_repeated_lying_and_silence_cannot_confirm_fall(make_runtime):
    parts = make_runtime()
    for second in range(12):
        decision = feed(parts, second)
        assert decision.candidate_only and decision.state == "FALL_SUSPECTED"
    parts[4].now = BASE + 40
    parts[1].advance()
    assert parts[1].controller.bathroom_decision.sensor_uncertain
    assert not fall_rows(parts[1]) and parts[1].outbox.fall_incident() is None


def test_lying_then_distinct_still_measurements_confirm_after_interval(make_runtime):
    parts = make_runtime()
    feed(parts, motion="still", fall=False)
    for second in range(1, 5):
        assert feed(parts, second, label=None, motion="still", fall=False).candidate_only
        assert not fall_rows(parts[1])
    decision = feed(parts, 5, label=None, motion="still", fall=False)
    assert decision.state == "FALL_CONFIRMED" and not decision.candidate_only
    row, = fall_rows(parts[1])
    assert row["source"]["details"]["basis"] == "lying_with_observed_stillness"
    assert row["source"]["details"]["candidate_origin"]["activity_event"] == "lie_down"
    parts[1].dispatch_mock_once()
    assert fall_rows(parts[1])[0]["status"] == "accepted"


def test_explicit_fall_promotes_a_candidate_immediately(make_runtime):
    parts = make_runtime()
    feed(parts)
    assert feed(parts, 1, label="mock_fall").incident_id
    assert len(fall_rows(parts[1])) == 1


def test_lying_and_moving_observations_recover_without_backend_incident(make_runtime):
    parts = make_runtime()
    feed(parts, motion="moving", fall=False)
    for second in range(1, 6):
        decision = feed(parts, second, label=None, motion="moving", activity="walking", fall=False)
    assert decision.state == "RECOVERED"
    assert not fall_rows(parts[1]) and parts[1].outbox.fall_incident() is None


@pytest.mark.parametrize("change", [{"activity_confidence": .79}, {"location_confidence": .79},
                                  {"activity_confidence": .1}, {"location_confidence": .1}])
def test_low_confidence_cannot_start_lying_candidate(make_runtime, change):
    parts = make_runtime()
    decision = feed(parts, **change)
    assert decision.state == "NORMAL_BATHROOM_USE" and not fall_rows(parts[1])


@pytest.mark.parametrize("room", ["room", "kitchen", "unknown", "empty"])
@pytest.mark.parametrize("label", ["mock_lie", "mock_fall"])
def test_no_new_fall_policy_outside_toilet(make_runtime, room, label):
    parts = make_runtime()
    decision = feed(parts, room=room, label=label, motion="still")
    assert decision.state == "NORMAL_BATHROOM_USE" and not fall_rows(parts[1])


@pytest.mark.parametrize("change", [
    {"location": "room"}, {"time": iso_time(BASE - 2)},
    {"time": iso_time(BASE + 1)}, {"valid_until": iso_time(BASE)},
    {"confidence": 1.1}, {"confidence": None}, {"confidence": True},
    {"error": "node_offline"}, {"valid": False},
])
def test_unusable_behavior_never_starts_candidate(make_runtime, change):
    parts = make_runtime()
    raw = envelope()
    raw["mockBehavior"].update(change)
    decision = feed(parts, raw=raw)
    assert decision is None or decision.state == "NORMAL_BATHROOM_USE"
    assert not fall_rows(parts[1])


def test_conflicting_false_fall_does_not_erase_lying_suspicion(make_runtime):
    parts = make_runtime()
    decision = feed(parts, fall=False)
    assert decision.candidate_only
    decision = feed(parts, 1, label=None, activity="lying", fall=False)
    assert decision.state == "FALL_SUSPECTED" and decision.candidate_only


def test_explicit_fall_wins_conflicting_lying_label(make_runtime):
    parts = make_runtime()
    decision = feed(parts, fall=True, motion="moving")
    assert decision.incident_id and decision.unresponsive_seconds == 0
    assert len(fall_rows(parts[1])) == 1


def test_gap_breaks_stillness_and_expired_candidate_needs_new_evidence(make_runtime):
    parts = make_runtime()
    raw = envelope(motion="still")
    raw["mockBehavior"]["valid_until"] = iso_time(BASE + 2)
    feed(parts, raw=raw)
    feed(parts, 6, label=None, motion="still")
    feed(parts, 12, label=None, motion="still")
    assert not fall_rows(parts[1])


def test_real_movement_can_recover_an_interrupted_candidate(make_runtime):
    parts = make_runtime()
    feed(parts)
    parts[4].now = BASE + 20
    parts[1].advance()
    for second in range(21, 27):
        result = feed(parts, second, label=None, motion="moving", activity="walking")
    assert result.state == "RECOVERED" and not result.candidate_only
    assert not fall_rows(parts[1])


def test_duplicate_event_id_cannot_extend_stillness_or_create_incident(make_runtime):
    parts = make_runtime()
    original = envelope(motion="still", event_id="same")
    feed(parts, raw=original)
    for second in range(1, 7):
        raw = envelope(second, label=None)
        raw["mockBehavior"] = original["mockBehavior"]
        feed(parts, second, raw=raw)
    assert not fall_rows(parts[1])
    assert parts[1].outbox.db.execute("SELECT count(*) FROM behavior_events").fetchone()[0] == 1


def test_conflicting_event_id_is_not_reinterpreted_as_new_fall(make_runtime):
    parts = make_runtime()
    feed(parts, event_id="same")
    feed(parts, 1, event_id="same", label="mock_fall")
    assert not fall_rows(parts[1])
    assert any(d["code"] == "behavior_event_conflict" for d in parts[1].diagnostics)


def test_event_identity_survives_restart(make_runtime):
    first = make_runtime()
    feed(first)
    close_for_restart(first)
    second = make_runtime(restart=True)
    feed(second)
    assert second[1].controller.bathroom_decision.state == "NORMAL_BATHROOM_USE"
    assert not fall_rows(second[1])


def test_backend_incident_not_resolved_by_silence_or_observed_recovery(make_runtime):
    parts = make_runtime()
    feed(parts, label="mock_fall")
    parts[1].dispatch_mock_once()
    incident_id = parts[1].outbox.fall_incident()["local_incident_id"]
    parts[4].now = BASE + 30
    parts[1].advance()
    assert parts[1].controller.bathroom_decision.sensor_uncertain
    for second in range(31, 37):
        decision = feed(parts, second, label=None, activity="walking", motion="moving", fall=False)
    assert decision.state == "RECOVERED"
    assert parts[1].outbox.fall_incident()["local_incident_id"] == incident_id


def test_candidate_can_be_disabled_without_disabling_explicit_falls(make_runtime):
    parts = make_runtime(scenario_config=ScenarioConfig(TOILET_LYING_SUSPICION_ENABLED=False))
    assert feed(parts).state == "NORMAL_BATHROOM_USE"
    assert feed(parts, 1, label="mock_fall").incident_id


def test_wake_event_alone_never_controls_light_water_or_bedtime(make_runtime):
    parts = make_runtime()
    feed(parts, room="room", label="mock_wake", devices=True)
    parts[4].now = BASE + 601
    parts[1].advance()
    assert not [r for r in parts[1].outbox.rows() if r["source"].get("scenario") in
                {"morning_light_on", "bedtime_light_off"} or r["source"].get("type") == "DeviceCommand"]


def test_single_lie_event_does_not_create_six_hundred_seconds_of_lying(make_runtime):
    parts = make_runtime()
    feed(parts, room="room", devices=True)
    parts[4].now = BASE + 601
    parts[1].advance()
    assert not parts[1].controller.bedtime_light._requested


@pytest.mark.parametrize("start_with_event", [False, True])
def test_confirmed_morning_wake_turns_on_room_light_via_backend(make_runtime, start_with_event):
    parts = make_runtime()
    feed(parts, room="room", label="mock_wake" if start_with_event else None,
         activity=None if start_with_event else "lying", devices=True)
    for second in range(1, 7):
        feed(parts, second, room="room", label=None, activity="standing", motion="moving", devices=True)
    parts[1].dispatch_mock_once()
    row, = [r for r in parts[1].outbox.rows() if r["source"].get("scenario") == "morning_light_on"]
    assert row["status"] == "accepted"
    assert row["payload"]["scenario"] == "light_auto_on"
    assert row["payload"]["actions"] == [{"device": "light", "deviceId": "light-01", "action": "on"}]
    assert row["payload"]["confidence"] == .92
    assert not [r for r in parts[1].outbox.rows() if r["source"]["type"] == "DeviceCommand"]
    for second in range(7, 13):
        feed(parts, second, room="kitchen", label=None, activity="standing", devices=True)
    parts[1].dispatch_mock_once()
    water, = [r for r in parts[1].outbox.rows() if r["source"]["type"] == "DeviceCommand"]
    assert water["payload"]["actions"][0]["amountMl"] == 120 and water["status"] == "accepted"


@pytest.mark.parametrize("change", ["left_room", "expired", "offline", "already_on"])
def test_morning_light_revalidated_before_send(make_runtime, change):
    parts = make_runtime()
    feed(parts, room="room", label=None, activity="lying", devices=True)
    for second in range(1, 7):
        feed(parts, second, room="room", label=None, activity="standing", devices=True)
    if change == "left_room":
        feed(parts, 7, room="kitchen", label=None, activity="standing", devices=True)
    elif change == "expired":
        parts[4].now = BASE + 20
        parts[1].advance()
    else:
        snapshot = sample_devices(BASE + 7)
        snapshot["items"][1]["online" if change == "offline" else "is_on"] = change == "already_on"
        parts[4].now = BASE + 7
        parts[1].ingest_device_states(snapshot)
        parts[1].advance()
    parts[1].dispatch_mock_once()
    row, = [r for r in parts[1].outbox.rows() if r["source"].get("scenario") == "morning_light_on"]
    assert row["status"] != "accepted"


def test_interrupted_wake_cannot_revive_old_light_request(make_runtime):
    parts = make_runtime()
    feed(parts, room="room", label=None, activity="lying", devices=True)
    for second in range(1, 7):
        feed(parts, second, room="room", label=None, activity="standing", devices=True)
    feed(parts, 7, room="room", label=None, activity="lying", devices=True)
    feed(parts, 8, room="room", label=None, activity="standing", devices=True)
    parts[1].dispatch_mock_once()
    row, = [r for r in parts[1].outbox.rows() if r["source"].get("scenario") == "morning_light_on"]
    assert row["status"] != "accepted"


def test_morning_light_not_reissued_after_restart_same_day(make_runtime):
    parts = make_runtime()
    feed(parts, room="room", label=None, activity="lying", devices=True)
    for second in range(1, 7):
        feed(parts, second, room="room", label=None, activity="standing", devices=True)
    parts[1].dispatch_mock_once()
    close_for_restart(parts)
    parts = make_runtime(restart=True)
    feed(parts, 100, room="room", label=None, activity="lying", devices=True)
    for second in range(101, 107):
        feed(parts, second, room="room", label=None, activity="standing", devices=True)
    assert len([r for r in parts[1].outbox.rows() if r["source"].get("scenario") == "morning_light_on"]) == 1


def test_evening_wake_does_not_request_morning_light(tmp_path):
    controller = CentralController(confidence_data_dir=tmp_path)
    at = BASE + 12 * 3600
    for offset, activity in ((0, "lying"), (1, "standing"), (6, "standing")):
        controller.update_sensing(SensingUpdate("room", at + offset, activity=activity))
    assert not controller.drain_scenario_actions()


def test_legacy_posture_transition_still_uses_existing_fall_path():
    scenario = BathroomFallScenario(ScenarioConfig(), RealtimeConfig())
    scenario.update(SensingUpdate("toilet", BASE, activity="standing"))
    result = scenario.update(SensingUpdate("toilet", BASE + 1, activity="lying"))
    assert result.incident_id and not result.candidate_only


def test_malformed_message_breaks_candidate_stillness(make_runtime):
    parts = make_runtime()
    feed(parts, motion="still")
    malformed = envelope(2)
    malformed["mockBehavior"]["confidence"] = "not-a-confidence"
    feed(parts, 2, raw=malformed)
    feed(parts, 5, label=None, motion="still")
    feed(parts, 10, label=None, motion="still")
    assert not fall_rows(parts[1])


def test_bare_posture_lying_without_motion_never_confirms(make_runtime):
    parts = make_runtime()
    for second in range(12):
        result = feed(parts, second, label=None, activity="lying")
        assert result.candidate_only
    assert not fall_rows(parts[1])


def test_behavior_expired_before_receipt_keeps_metadata_but_is_not_used(make_runtime):
    parts = make_runtime()
    raw = envelope(0, label="mock_fall")
    raw["mockBehavior"]["valid_until"] = iso_time(BASE + 2)
    result = feed(parts, 3, raw=raw)
    sample = parts[1]._latest_received_sample
    assert not sample.activity_observed and sample.activity_timestamp == BASE
    assert result.state == "NORMAL_BATHROOM_USE" and not fall_rows(parts[1])


def test_persisted_backend_resolution_clears_a_local_only_candidate(make_runtime):
    parts = make_runtime()
    feed(parts, label="mock_fall")
    parts[1].dispatch_mock_once()
    record = parts[1].outbox.fall_incident()
    close_for_restart(parts)
    parts = make_runtime(restart=True)
    assert feed(parts, 1).candidate_only
    parts[4].now = BASE + 2
    parts[1].receive_backend_fall_status({"incidentId": record["fallIncidentId"], "status": "resolved",
                                         "resolvedAt": iso_time(BASE + 2)})
    assert not parts[1].controller.bathroom_decision.candidate_only
    assert parts[1].outbox.fall_incident() is None


@pytest.mark.parametrize("scenario", ["fall", "morning_light"])
def test_new_paths_match_inspected_backend_v07_schema(make_runtime, scenario):
    import os
    import subprocess
    import sys
    from types import ModuleType
    checkout = os.environ.get("HOMEVIS_BACKEND_CHECKOUT")
    if not checkout:
        pytest.skip("optional: HOMEVIS_BACKEND_CHECKOUT for pinned v0.7 schema check")
    pytest.importorskip("pydantic")
    source = subprocess.run(["git", "show", "fb22929879d255f6c1788f465df48c941b9338b7:app/schemas.py"],
                            cwd=checkout, capture_output=True, encoding="utf-8", check=True).stdout
    module = ModuleType("homevis_behavior_backend_v07")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, "verified_backend_v07_schemas.py", "exec"), module.__dict__)
        parts = make_runtime()
        if scenario == "fall":
            feed(parts, label="mock_fall")
            row, = fall_rows(parts[1])
        else:
            feed(parts, room="room", label=None, activity="lying", devices=True)
            for second in range(1, 7):
                feed(parts, second, room="room", label=None, activity="standing", devices=True)
            row, = [r for r in parts[1].outbox.rows() if r["source"].get("scenario") == "morning_light_on"]
        parsed = module.AiDecisionRequest.model_validate(row["payload"])
        assert parsed.confidence == .92
        assert parsed.scenario == ("fall_detected" if scenario == "fall" else "light_auto_on")
    finally:
        sys.modules.pop(module.__name__, None)
