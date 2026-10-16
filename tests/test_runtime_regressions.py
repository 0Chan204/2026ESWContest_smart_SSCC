"""Runtime regressions using explicit MOCK contracts, never deployment defaults."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from examples.backend_integration_demo import FakeClock
from src.control import CentralController, ScenarioConfig
from src.integration import IntegrationConfig, IntegrationRuntime
from src.integration.backend_client import BackendClient
from src.integration.mock_backend import MockBackend, sample_devices
from src.integration.schemas import iso_time
from src.integration.sensing import BehaviorObservation


BASE = datetime(2026, 10, 17, 7, tzinfo=timezone(timedelta(hours=9))).timestamp()


@pytest.fixture
def make_runtime(tmp_path):
    runtimes = []

    def make(lateness=2.0, bedtime_seconds=6):
        # Names deliberately differ from internal scenarios. These are mock-only assumptions.
        config = IntegrationConfig(
            data_dir=tmp_path / str(len(runtimes)), allowed_lateness=lateness,
            room_is_bedroom=True, water_ready_states=("idle",), rule_confidence_policy="null",
            action_routes={
                ("bedtime_light_off", "turn_off"): ("mock_sleep", "light", "turn_off", "bedroom"),
                ("light_auto_off", "turn_off"): ("mock_absence", "light", "turn_off", "bedroom"),
                ("light_auto_on", "turn_on"): ("mock_presence", "light", "turn_on", "bedroom"),
            },
        )
        clock = FakeClock(BASE)
        backend = MockBackend(clock, allow_null_confidence=True)
        controller = CentralController(
            confidence_data_dir=config.outbox_path.parent / "controller",
            scenario_config=ScenarioConfig(BEDTIME_LYING_SECONDS=bedtime_seconds,
                                           MORNING_WATER_AMOUNT_ML=180),
        )
        runtime = IntegrationRuntime(config, BackendClient(config, backend), controller=controller, clock=clock)
        runtimes.append(runtime)
        return runtime, backend, clock

    yield make
    for runtime in runtimes:
        runtime.close()


def feed(runtime, backend, clock, offset, *, room="room", activity="lying", ttl=10,
         light_on=True, sensing_first=False, advance=True, snapshot=None,
         behavior_confidence=.95, behavior_valid=True, behavior_skew=0.0):
    """Poll every 2s, sense/evaluate every 1s; behavior is an explicit synthetic observation."""
    clock.now = BASE + offset
    payload = {"time": iso_time(clock.now), "location": room, "location_confidence": .95}
    behavior = None if activity is None else BehaviorObservation(
        clock.now - behavior_skew, clock.now - behavior_skew + ttl,
        "bedroom" if room == "room" else room,
        confidence=behavior_confidence, activity=activity, valid=behavior_valid)

    def sense():
        runtime.ingest_location(payload, behavior=behavior)

    def devices():
        if offset % 2 == 0:
            backend.snapshot = snapshot or sample_devices(clock.now)
            if snapshot is None:
                backend.snapshot["items"][1]["is_on"] = light_on
            runtime.ingest_device_states({"items": runtime.client.fetch_device_states()})

    for callback in ((sense, devices) if sensing_first else (devices, sense)):
        callback()
    if advance:
        return runtime.advance()


def rows_for(runtime, scenario):
    return [row for row in runtime.outbox.rows() if row["source"].get("scenario") == scenario]


def water_rows(runtime):
    return [row for row in runtime.outbox.rows() if row["source"]["type"] == "DeviceCommand"]


def test_valid_bedtime_request_reaches_mock_while_user_stays_in_bedroom(make_runtime):
    runtime, backend, clock = make_runtime(lateness=0)
    for offset in range(7):
        feed(runtime, backend, clock, offset)
    row, = rows_for(runtime, "bedtime_light_off")
    assert row["source"]["details"]["lying_seconds"] >= 6
    assert row["payload"]["scenario"] == "mock_sleep"
    runtime.dispatch_mock_once()
    saved, = rows_for(runtime, "bedtime_light_off")
    assert saved["status"] == "accepted", saved["diagnostic"]
    assert len(backend.accepted) == 1


@pytest.mark.parametrize("sensing_first", [False, True])
def test_two_second_lateness_uses_past_device_for_light_evaluation(make_runtime, sensing_first):
    runtime, backend, clock = make_runtime()
    for offset in range(11):
        feed(runtime, backend, clock, offset, light_on=False, activity=None, sensing_first=sensing_first)
    assert runtime.last_decision.timestamp == BASE + 8
    assert runtime.devices["light"].measured_at == BASE + 10  # latest received, for sending
    assert runtime.evaluated_devices["light"].measured_at == BASE + 8
    assert rows_for(runtime, "light_auto_on"), "valid past light snapshots were skipped"
    runtime.dispatch_mock_once()
    assert len(backend.accepted) == 1


def test_two_second_lateness_allows_measured_morning_water_request(make_runtime):
    runtime, backend, clock = make_runtime()
    for offset in range(19):
        room = "room" if offset < 7 else "kitchen"
        activity = "lying" if offset == 0 else "standing" if offset < 7 else "walking"
        feed(runtime, backend, clock, offset, room=room, activity=activity)
    row, = water_rows(runtime)
    assert row["source"]["timestamp"] == BASE + 12
    assert row["payload"]["actions"][0]["amountMl"] == 180
    assert row["payload"]["weatherBriefing"] is True
    runtime.dispatch_mock_once()
    assert water_rows(runtime)[0]["status"] == "accepted"
    assert len(backend.accepted) == 1


def qualify_bedtime(runtime, backend, clock, **kwargs):
    for offset in range(9):
        feed(runtime, backend, clock, offset, **kwargs)
    row, = rows_for(runtime, "bedtime_light_off")
    return row


@pytest.mark.parametrize("sensing_first", [False, True])
def test_buffered_short_lived_behavior_maintains_but_never_prequalifies_bedtime(make_runtime, sensing_first):
    runtime, backend, clock = make_runtime()
    for offset in range(8):
        feed(runtime, backend, clock, offset, ttl=1.5, sensing_first=sensing_first)
        assert not rows_for(runtime, "bedtime_light_off")
    feed(runtime, backend, clock, 8, ttl=1.5, sensing_first=sensing_first)
    row, = rows_for(runtime, "bedtime_light_off")
    assert row["source"]["timestamp"] == BASE + 6  # qualification follows watermark, not receipt
    assert runtime.controller.realtime_engine._sensing.activity_valid_until < clock()
    assert runtime._latest_received_sample.activity_valid_until > clock()
    engine, scenario = runtime.controller.realtime_engine, runtime.controller.bedtime_light
    before = (engine._now, deepcopy(vars(scenario)), runtime.controller.peek_outputs(),
              deepcopy(runtime.outbox.rows()), tuple(engine._sensor_history))
    for _ in range(3):
        assert runtime._revalidate(row, clock()) is None
    assert before == (engine._now, vars(scenario), runtime.controller.peek_outputs(),
                      runtime.outbox.rows(), tuple(engine._sensor_history))
    runtime.dispatch_mock_once()
    assert rows_for(runtime, "bedtime_light_off")[0]["status"] == "accepted"
    assert len(backend.accepted) == 1


@pytest.mark.parametrize("change", ["standing", "leaving", "missing", "expired", "low_confidence",
                                    "null_confidence", "invalid_behavior", "unknown", "malformed"])
def test_bedtime_rejects_latest_counterevidence_even_before_application(make_runtime, change):
    runtime, backend, clock = make_runtime()
    row = qualify_bedtime(runtime, backend, clock, ttl=1.5)
    if change == "expired":
        clock.now = BASE + 10
    elif change in {"unknown", "malformed"}:
        clock.now = BASE + 9
        payload = {} if change == "malformed" else {
            "time": iso_time(clock()), "location": "unknown", "location_confidence": None,
            "reason": "node_offline:r3"}
        runtime.ingest_location(payload)
    else:
        kwargs = {"standing": {"activity": "standing"},
                  "leaving": {"room": "kitchen", "activity": "walking"},
                  "missing": {"activity": None},
                  "low_confidence": {"behavior_confidence": .1},
                  "null_confidence": {"behavior_confidence": None},
                  "invalid_behavior": {"behavior_valid": False}}[change]
        feed(runtime, backend, clock, 9, advance=False, **kwargs)
    assert runtime.controller.realtime_engine.last_sensor_update == BASE + 6
    assert runtime._revalidate(row, clock()) is not None
    runtime.dispatch_mock_once()
    assert not backend.accepted


@pytest.mark.parametrize("interruption", ["standing", "leaving", "gap"])
def test_old_bedtime_request_cannot_revive_and_new_episode_must_fully_qualify(make_runtime, interruption):
    runtime, backend, clock = make_runtime()
    old = qualify_bedtime(runtime, backend, clock, ttl=1.5)
    if interruption != "gap":
        feed(runtime, backend, clock, 9, activity="standing",
             room="kitchen" if interruption == "leaving" else "room", advance=False)
    # New lying result is received before either buffered observation is applied.
    feed(runtime, backend, clock, 10, ttl=1.5, advance=False)
    assert runtime._revalidate(old, clock()) == "bedtime_observation_interrupted"
    for offset in range(11, 18):
        feed(runtime, backend, clock, offset, ttl=1.5)
        assert len(rows_for(runtime, "bedtime_light_off")) == 1
    feed(runtime, backend, clock, 18, ttl=1.5)
    old_saved, new = rows_for(runtime, "bedtime_light_off")
    assert new["source"]["timestamp"] == BASE + 16
    assert new["source_id"] != old["source_id"]
    assert runtime._revalidate(old_saved, clock()) is not None
    assert runtime._revalidate(new, clock()) is None
    runtime.dispatch_mock_once()
    assert list(backend.accepted) == [new["payload"]["decisionId"]]


@pytest.mark.parametrize("tamper", ["unsupported_scenario", "target", "request_identity", "backend_room"])
def test_light_route_cannot_bypass_original_source_checks(make_runtime, tamper):
    runtime, backend, clock = make_runtime()
    row = deepcopy(qualify_bedtime(runtime, backend, clock))
    if tamper == "unsupported_scenario":
        row["source"]["scenario"] = "unsupported_sleep"
    elif tamper == "target":
        row["source"]["target"] = "kitchen_light"
    elif tamper == "request_identity":
        row["source"]["timestamp"] -= 1
    else:
        row["payload"]["room"] = "kitchen"
    assert runtime._revalidate(row, clock()) in {
        "unsupported_light_scenario", "light_target_mismatch",
        "bedtime_request_no_longer_current", "device_room_mismatch"}


@pytest.mark.parametrize("change", ["none", "return", "unknown", "stale"])
def test_absence_off_keeps_absence_and_freshness_requirements(make_runtime, change):
    runtime, backend, clock = make_runtime()
    for offset in range(33):
        feed(runtime, backend, clock, offset, room="kitchen", activity="walking")
    row = rows_for(runtime, "light_auto_off")[-1]
    assert row["payload"]["scenario"] == "mock_absence"
    if change == "return":
        feed(runtime, backend, clock, 33, activity=None, advance=False)
    elif change == "unknown":
        clock.now = BASE + 33
        runtime.ingest_location({"time": iso_time(clock()), "location": "unknown",
                                 "location_confidence": None, "reason": "config_mismatch"})
    elif change == "stale":
        clock.now += runtime.controller.realtime_engine.config.UNKNOWN_TIMEOUT
    assert (runtime._revalidate(row, clock()) is None) == (change == "none")
    runtime.dispatch_mock_once()
    assert bool(backend.accepted) == (change == "none")


def test_presence_on_still_requires_confirmed_target_room(make_runtime):
    runtime, backend, clock = make_runtime()
    for offset in range(9):
        feed(runtime, backend, clock, offset, activity=None, light_on=False)
    row = rows_for(runtime, "light_auto_on")[-1]
    assert runtime._revalidate(row, clock()) is None
    feed(runtime, backend, clock, 9, room="kitchen", activity=None, advance=False)
    assert runtime._revalidate(row, clock()) == "location_changed_or_invalid_before_confirmation"
    runtime.dispatch_mock_once()
    assert not backend.accepted


@pytest.mark.parametrize("sensing_first", [False, True])
@pytest.mark.parametrize("one_advance", [False, True])
def test_same_time_input_order_and_multiple_timestamps_use_each_past_device(
        make_runtime, monkeypatch, sensing_first, one_advance):
    runtime, backend, clock = make_runtime()
    calls = []
    original = runtime.state_mapper.water_ready

    def record(observation, at):
        result = original(observation, at)
        calls.append((at, None if observation is None else observation.measured_at, result))
        return result

    monkeypatch.setattr(runtime.state_mapper, "water_ready", record)
    for offset in range(19):
        feed(runtime, backend, clock, offset,
             room="room" if offset < 7 else "kitchen",
             activity="lying" if offset == 0 else "standing" if offset < 7 else "walking",
             sensing_first=sensing_first, advance=not one_advance)
    if one_advance:
        runtime.advance()
    assert calls == [(BASE + t, BASE + t - t % 2, True) for t in range(17)]
    row, = water_rows(runtime)
    assert row["source"]["timestamp"] == BASE + 12
    assert row["payload"]["actions"][0]["amountMl"] == 180
    assert row["payload"]["weatherBriefing"] is True
    runtime.dispatch_mock_once()
    assert len(backend.accepted) == 1
    runtime.advance()
    assert len(water_rows(runtime)) == 1


def test_future_only_device_cannot_substitute_for_missing_past_snapshot(make_runtime, monkeypatch):
    runtime, backend, clock = make_runtime()
    seen = []
    original = runtime.state_mapper.water_ready

    def record(observation, at):
        seen.append((observation, at))
        return original(observation, at)

    monkeypatch.setattr(runtime.state_mapper, "water_ready", record)
    clock.now = BASE + 10
    runtime.ingest_device_states(sample_devices(clock()))
    for offset in range(9):
        runtime.ingest_location({"time": iso_time(BASE + offset), "location": "room",
                                 "location_confidence": .95})
    runtime.advance()
    assert all(observation is None for observation, _ in seen)
    assert seen[-1][1] == BASE + 8
    assert runtime.evaluated_devices == {}
    assert not rows_for(runtime, "light_auto_on")


@pytest.mark.parametrize("kind", ["light", "water_purifier", "stove"])
def test_current_good_state_cannot_replace_historical_offline(make_runtime, kind):
    runtime, backend, clock = make_runtime()
    for offset in range(11):
        snapshot = sample_devices(BASE + offset)
        if offset == 8:
            next(item for item in snapshot["items"] if item["device"] == kind)["online"] = False
        feed(runtime, backend, clock, offset, activity=None, snapshot=snapshot)
    assert runtime.devices[kind].raw["online"] is True
    assert runtime.evaluated_devices[kind].raw["online"] is False
    assert runtime.evaluated_devices[kind].measured_at == BASE + 8
    if kind == "light":
        assert not any(row["source"]["timestamp"] == BASE + 8 for row in rows_for(runtime, "light_auto_on"))
    elif kind == "water_purifier":
        assert runtime.controller.water_dispenser_available is False
    else:
        assert runtime.controller.realtime_engine.appliance_invalid


def morning_until_request(runtime, backend, clock):
    for offset in range(15):
        feed(runtime, backend, clock, offset, room="room" if offset < 7 else "kitchen",
             activity="lying" if offset == 0 else "standing" if offset < 7 else "walking")
    row, = water_rows(runtime)
    return row


@pytest.mark.parametrize("fault", ["offline", "busy", "error", "missing", "malformed", "invalid_room",
                                   "conflict", "http_failure", "future_timestamp"])
def test_latest_device_fault_blocks_old_good_send_and_recovers_only_with_new_good(make_runtime, fault):
    runtime, backend, clock = make_runtime()
    row = morning_until_request(runtime, backend, clock)
    assert runtime.evaluated_devices["water_purifier"].measured_at == BASE + 12
    clock.now = BASE + 15
    snapshot = sample_devices(clock())
    item = snapshot["items"][2]
    if fault == "offline":
        item["online"] = False
    elif fault in {"busy", "error"}:
        item["current_state"]["status"] = fault
    elif fault == "missing":
        snapshot["items"].pop()
    elif fault == "malformed":
        item["online"] = "invalid"
    elif fault == "invalid_room":
        item["room"] = "unknown"
    elif fault == "future_timestamp":
        item["updatedAt"] = iso_time(BASE + 100)
    elif fault == "conflict":
        snapshot = sample_devices(BASE + 14)
        snapshot["items"][2]["online"] = False
    if fault == "http_failure":
        runtime.poll_failed()
    else:
        runtime.ingest_device_states(snapshot)
    assert runtime.evaluated_devices["water_purifier"].raw["online"] is True
    assert runtime._revalidate(row, clock()) is not None
    runtime.dispatch_mock_once()
    assert not backend.accepted
    # A repeat of the previous good measurement is not proof of recovery.
    runtime.ingest_device_states(sample_devices(BASE + 14))
    assert runtime._revalidate(row, clock()) is not None
    feed(runtime, backend, clock, 16, room="kitchen", activity="walking")
    assert runtime._revalidate(row, clock()) is None
    runtime.dispatch_mock_once()
    assert list(backend.accepted) == [row["payload"]["decisionId"]]


def test_repeated_updated_at_is_not_fresh_and_late_or_backward_events_do_not_rewind_cache(make_runtime):
    runtime, backend, clock = make_runtime()
    for offset in range(27):
        feed(runtime, backend, clock, offset, activity=None, light_on=False,
             snapshot=sample_devices(BASE))
    assert runtime.devices["light"].measured_at == BASE
    assert runtime.evaluated_devices["light"].measured_at == BASE
    assert not any(row["source"]["timestamp"] >= BASE + 20 for row in rows_for(runtime, "light_auto_on"))
    assert any(d["code"] == "duplicate_observation" for d in runtime.diagnostics)
    runtime.ingest_device_states(sample_devices(BASE + 1))
    assert any(d["code"] == "late_observation_dropped" for d in runtime.diagnostics)
    runtime.advance()
    assert runtime.evaluated_devices["light"].measured_at == BASE
    row = rows_for(runtime, "light_auto_on")[-1]
    assert runtime._revalidate(row, clock()) == "device_state_stale_or_invalid"
    with pytest.raises(ValueError, match="backwards"):
        runtime.advance(BASE + 25)


def test_conflicting_queued_device_is_invalid_at_that_timestamp_not_older_good(make_runtime):
    runtime, backend, clock = make_runtime()
    for offset in range(9):
        feed(runtime, backend, clock, offset, activity=None, light_on=False)
    conflict = sample_devices(BASE + 8)
    conflict["items"][1]["online"] = False
    runtime.ingest_device_states(conflict)
    feed(runtime, backend, clock, 10, activity=None, light_on=False)
    assert runtime.evaluated_devices["light"] is None
    assert runtime.devices["light"].measured_at == BASE + 10
    assert not any(row["source"]["timestamp"] == BASE + 8 for row in rows_for(runtime, "light_auto_on"))
    feed(runtime, backend, clock, 12, activity=None, light_on=False)
    assert runtime.evaluated_devices["light"].measured_at == BASE + 10


@pytest.mark.parametrize("kind", ["light", "water_purifier", "stove"])
def test_late_conflict_invalidates_cached_measurement_without_rewinding_time(make_runtime, kind):
    runtime, backend, clock = make_runtime()
    for offset in range(10):
        feed(runtime, backend, clock, offset, activity=None)
    clock.now = BASE + 11
    runtime.advance()  # watermark=9, last device observation=8
    conflict = sample_devices(BASE + 8)
    next(item for item in conflict["items"] if item["device"] == kind)["online"] = False
    runtime.ingest_device_states(conflict)
    runtime.advance()
    assert runtime.last_decision.timestamp == BASE + 9
    assert runtime.evaluated_devices[kind] is None
    assert any(d["code"] == "conflicting_observation" and d["stream"] == kind
               for d in runtime.diagnostics)
    feed(runtime, backend, clock, 12, activity=None)
    assert runtime.evaluated_devices[kind] is None  # valid 12 is still buffered
    feed(runtime, backend, clock, 14, activity=None)
    assert runtime.evaluated_devices[kind].measured_at == BASE + 12


@pytest.mark.parametrize("fault", ["offline", "http_failure", "malformed", "missing"])
def test_past_water_qualification_survives_current_fault_but_sending_does_not(make_runtime, fault):
    runtime, backend, clock = make_runtime()
    for offset in range(14):
        feed(runtime, backend, clock, offset, room="room" if offset < 7 else "kitchen",
             activity="lying" if offset == 0 else "standing" if offset < 7 else "walking")
    assert not water_rows(runtime)  # evaluated only through 11; kitchen requires 5 seconds
    clock.now = BASE + 14
    snapshot = sample_devices(clock())
    if fault == "offline":
        snapshot["items"][2]["online"] = False
    elif fault == "malformed":
        snapshot["items"][2]["is_on"] = None
    elif fault == "missing":
        snapshot["items"].pop()
    if fault == "http_failure":
        runtime.poll_failed()
    else:
        runtime.ingest_device_states(snapshot)
    runtime.advance()
    row, = water_rows(runtime)
    assert row["source"]["timestamp"] == BASE + 12
    assert runtime.controller.water_dispenser_available
    assert runtime.evaluated_devices["water_purifier"].measured_at == BASE + 12
    runtime.dispatch_mock_once()
    assert not backend.accepted
    assert water_rows(runtime)[0]["diagnostic"] is not None


def poll_during_sensing_gap(runtime, backend, clock, offset):
    """Keep actual device polling/ticks alive while location and behavior are silent."""
    clock.now = BASE + offset
    if offset % 2 == 0:
        backend.snapshot = sample_devices(clock())
        backend.snapshot["items"][1]["is_on"] = True
        runtime.ingest_device_states({"items": runtime.client.fetch_device_states()})
    runtime.advance()


def first_bedtime_then_gap(runtime, backend, clock):
    old = qualify_bedtime(runtime, backend, clock, ttl=3)
    assert old["status"] == "pending"
    for offset in range(9, 20):
        poll_during_sensing_gap(runtime, backend, clock, offset)
    assert not runtime.controller.bedtime_light.matches_current_request(old["source"])
    return old


@pytest.mark.parametrize("skew", [0.0, 0.5, 1.0])
def test_bedtime_new_episode_after_gap_with_location_behavior_skew(make_runtime, skew):
    runtime, backend, clock = make_runtime()
    old = first_bedtime_then_gap(runtime, backend, clock)
    start = BASE + 20 - skew
    for offset in range(20, 29):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=skew)
        if offset == 20:
            # The old request is already invalid BEFORE its separate command TTL expires.
            assert clock() < old["expires_at"]
            assert runtime._revalidate(old, clock()) == "bedtime_request_no_longer_current"
        if runtime.last_decision.timestamp < start + 6:
            assert len(rows_for(runtime, "bedtime_light_off")) == 1
    old_saved, new = rows_for(runtime, "bedtime_light_off")
    assert old_saved["source_id"] != new["source_id"]
    source = new["source"]
    assert source["timestamp"] - source["details"]["lying_seconds"] == start
    assert 6 <= source["details"]["lying_seconds"] < 7
    assert source["timestamp"] <= runtime.last_decision.timestamp
    assert runtime._latest_received_sample.timestamp == BASE + 28
    assert runtime._latest_received_sample.activity_timestamp == BASE + 28 - skew
    assert runtime._latest_received_sample.activity_valid_until > clock()
    assert runtime.controller.bedtime_light.matches_current_request(source)
    assert runtime._revalidate(old_saved, clock()) is not None
    assert runtime._revalidate(new, clock()) is None
    for _ in range(3):
        runtime.dispatch_mock_once()
        runtime.advance()
    assert list(backend.accepted) == [new["payload"]["decisionId"]]
    assert sum(method == "POST" for method, _, _ in backend.requests) == 1
    assert len(rows_for(runtime, "bedtime_light_off")) == 2
    assert rows_for(runtime, "bedtime_light_off")[1]["status"] == "accepted"


def second_bedtime(runtime, backend, clock, *, skew=1.0):
    old = first_bedtime_then_gap(runtime, backend, clock)
    for offset in range(20, 29):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=skew)
    new = rows_for(runtime, "bedtime_light_off")[-1]
    assert runtime._revalidate(new, clock()) is None
    return old, new


def receive_bedtime(runtime, measured_offset, *, skew=1.0, ttl=3, activity="lying"):
    """Measurement time is independent of the runtime's monotonically increasing receive clock."""
    measured = BASE + measured_offset
    return runtime.ingest_location(
        {"time": iso_time(measured), "location": "room", "location_confidence": .95},
        behavior=BehaviorObservation(measured - skew, measured - skew + ttl,
                                     "bedroom", confidence=.95, activity=activity))


@pytest.mark.parametrize("skew", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("lateness", [0.0, 2.0])
def test_continuous_bedtime_with_distinct_behavior_time(make_runtime, skew, lateness):
    runtime, backend, clock = make_runtime(lateness=lateness)
    start = BASE - skew
    for offset in range(9):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=skew)
        if runtime.last_decision.timestamp < start + 6:
            assert not rows_for(runtime, "bedtime_light_off")
    row, = rows_for(runtime, "bedtime_light_off")
    assert row["source"]["timestamp"] - row["source"]["details"]["lying_seconds"] == start
    runtime.dispatch_mock_once()
    assert list(backend.accepted) == [row["payload"]["decisionId"]]


@pytest.mark.parametrize("change", ["standing", "leaving", "unknown", "missing", "invalid",
                                    "low_confidence", "excess_skew", "future", "expired"])
def test_skewed_new_episode_counterevidence_blocks_until_another_full_episode(make_runtime, change):
    runtime, backend, clock = make_runtime()
    old, current = second_bedtime(runtime, backend, clock)
    kwargs = {"standing": {"activity": "standing"}, "leaving": {"room": "kitchen"},
              "unknown": {"room": "unknown"}, "missing": {"activity": None},
              "invalid": {"behavior_valid": False}, "low_confidence": {"behavior_confidence": .1},
              "excess_skew": {"behavior_skew": 1.5}, "future": {"behavior_skew": -.5},
              "expired": {"ttl": 1}}[change]
    feed(runtime, backend, clock, 29, advance=False,
         **({"ttl": 3, "behavior_skew": 1.0} | kwargs))
    assert runtime.controller.realtime_engine.last_sensor_update == BASE + 26
    if change in {"excess_skew", "future", "expired", "invalid", "missing", "unknown"}:
        assert runtime._latest_received_sample.activity_observed is False
    assert runtime._revalidate(current, clock()) is not None
    runtime.dispatch_mock_once()
    assert not backend.accepted
    # Restored lying is still buffered; it cannot revive the interrupted request.
    feed(runtime, backend, clock, 30, advance=False, ttl=3, behavior_skew=1)
    assert runtime._revalidate(current, clock()) is not None
    for offset in range(31, 39):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=1)
        if runtime.last_decision.timestamp < BASE + 35:
            assert len(rows_for(runtime, "bedtime_light_off")) == 2
    latest = rows_for(runtime, "bedtime_light_off")[-1]
    assert len(rows_for(runtime, "bedtime_light_off")) == 3
    assert latest["source"]["timestamp"] - latest["source"]["details"]["lying_seconds"] == BASE + 29
    assert runtime._revalidate(old, clock()) is not None
    assert runtime._revalidate(current, clock()) is not None
    assert runtime._revalidate(latest, clock()) is None
    runtime.dispatch_mock_once()
    assert list(backend.accepted) == [latest["payload"]["decisionId"]]


def test_skewed_episode_expiry_and_second_gap_do_not_revive_either_old_request(make_runtime):
    runtime, backend, clock = make_runtime()
    old, current = second_bedtime(runtime, backend, clock)
    for offset in range(29, 32):
        poll_during_sensing_gap(runtime, backend, clock, offset)
    assert runtime._revalidate(current, clock()) == "bedtime_behavior_missing_or_expired"
    for offset in range(32, 40):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=1)
        if runtime.last_decision.timestamp < BASE + 37:
            assert len(rows_for(runtime, "bedtime_light_off")) == 2
    latest = rows_for(runtime, "bedtime_light_off")[-1]
    assert latest["source"]["timestamp"] - latest["source"]["details"]["lying_seconds"] == BASE + 31
    assert clock() < current["expires_at"]  # identity/continuity blocks it, not just command TTL
    assert runtime._revalidate(current, clock()) == "bedtime_request_no_longer_current"
    runtime.dispatch_mock_once()
    assert list(backend.accepted) == [latest["payload"]["decisionId"]]


@pytest.mark.parametrize("skew", [0.0, 0.5, 1.0])
def test_new_episode_is_identical_when_first_two_location_observations_arrive_reversed(make_runtime, skew):
    sources = []
    for reversed_order in (False, True):
        runtime, backend, clock = make_runtime()
        first_bedtime_then_gap(runtime, backend, clock)
        clock.now = BASE + 21
        # Both are inside the lateness window; receipt time is 21 in either order.
        for offset in ((21, 20) if reversed_order else (20, 21)):
            assert receive_bedtime(runtime, offset, skew=skew)
        runtime.advance()
        for offset in range(22, 29):
            feed(runtime, backend, clock, offset, ttl=3, behavior_skew=skew)
        new = rows_for(runtime, "bedtime_light_off")[-1]
        assert new["source"]["timestamp"] - new["source"]["details"]["lying_seconds"] == BASE + 20 - skew
        assert runtime._revalidate(new, clock()) is None
        sources.append((new["source"], new["source_id"], new["payload"]))
        runtime.dispatch_mock_once()
        assert list(backend.accepted) == [new["payload"]["decisionId"]]
    assert sources[0] == sources[1]


@pytest.mark.parametrize("measured_offset, blocks", [(10.0, False), (27.5, True)])
def test_late_counterevidence_applies_to_its_own_episode(make_runtime, measured_offset, blocks):
    runtime, backend, clock = make_runtime()
    _, new = second_bedtime(runtime, backend, clock)
    accepted = receive_bedtime(runtime, measured_offset, skew=.5, activity="standing")
    assert accepted is blocks  # Old episode is beyond watermark; current one is still buffered.
    assert runtime._latest_received_sample.timestamp == BASE + 28
    assert runtime.controller.realtime_engine.last_sensor_update == BASE + 26
    assert (runtime._revalidate(new, clock()) is not None) is blocks
    runtime.dispatch_mock_once()
    assert bool(backend.accepted) is not blocks


def test_repeated_measurement_after_gap_cannot_extend_validity_or_lying_time(make_runtime):
    runtime, backend, clock = make_runtime()
    first_bedtime_then_gap(runtime, backend, clock)
    clock.now = BASE + 20
    assert receive_bedtime(runtime, 20)
    for offset in range(20, 30):
        clock.now = BASE + offset
        assert not receive_bedtime(runtime, 20)
        poll_during_sensing_gap(runtime, backend, clock, offset)
    assert runtime.controller.realtime_engine.last_sensor_update == BASE + 20
    applied = runtime.outbox.audits("location_applied")
    assert sum(entry["measured_at"] == BASE + 20 for entry in applied) == 1
    assert runtime._latest_received_sample.activity_timestamp == BASE + 19
    assert runtime._latest_received_sample.activity_valid_until == BASE + 22
    assert len(rows_for(runtime, "bedtime_light_off")) == 1
    runtime.dispatch_mock_once()
    assert not backend.accepted


def test_same_time_behavior_conflict_cannot_be_undone_by_repeating_lying(make_runtime):
    runtime, backend, clock = make_runtime()
    _, new = second_bedtime(runtime, backend, clock)
    assert not receive_bedtime(runtime, 28, activity="standing")
    assert not receive_bedtime(runtime, 28)
    assert any(d["code"] == "conflicting_observation" for d in runtime.diagnostics)
    for offset in range(29, 32):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=1)
    assert runtime.controller.realtime_engine.last_sensor_update == BASE + 29
    assert runtime._revalidate(new, clock()) == "bedtime_observation_interrupted"
    runtime.dispatch_mock_once()
    assert not backend.accepted


@pytest.mark.parametrize("skew", [0.0, 1.0])
@pytest.mark.parametrize("sensing_first", [False, True])
def test_touching_validity_preserves_only_an_episode_not_already_expired_by_tick(
        make_runtime, skew, sensing_first):
    runtime, backend, clock = make_runtime()
    _, current = second_bedtime(runtime, backend, clock, skew=skew)
    previous_end = runtime._latest_received_sample.activity_valid_until
    for offset in (29, 30):
        poll_during_sensing_gap(runtime, backend, clock, offset)
    feed(runtime, backend, clock, 31, ttl=3, behavior_skew=skew, sensing_first=sensing_first)
    assert runtime._latest_received_sample.activity_timestamp == previous_end
    poll_during_sensing_gap(runtime, backend, clock, 32)
    feed(runtime, backend, clock, 33, ttl=3, behavior_skew=skew)
    if skew == 0:
        # Renewal at 31 is applied before the tick at 31; no positive validity gap.
        assert runtime.controller.bedtime_light.matches_current_request(current["source"])
        assert runtime._revalidate(current, clock()) is None
    else:
        # Tick at 30 already expired the old observation. Location 31 / behavior 30
        # starts a new episode when applied; it cannot resurrect the expired one.
        assert runtime._revalidate(current, clock()) == "bedtime_request_no_longer_current"
        assert len(rows_for(runtime, "bedtime_light_off")) == 2
        for offset in range(34, 39):
            feed(runtime, backend, clock, offset, ttl=3, behavior_skew=skew)
            if runtime.last_decision.timestamp < previous_end + 6:
                assert len(rows_for(runtime, "bedtime_light_off")) == 2
        new = rows_for(runtime, "bedtime_light_off")[-1]
        assert new["source"]["timestamp"] - new["source"]["details"]["lying_seconds"] == previous_end
        assert runtime._revalidate(new, clock()) is None


def test_location_timeout_with_long_lived_behavior_also_allows_a_new_skewed_episode(make_runtime):
    runtime, backend, clock = make_runtime()
    old = qualify_bedtime(runtime, backend, clock, ttl=60)
    for offset in range(9, 30):
        poll_during_sensing_gap(runtime, backend, clock, offset)
    for offset in range(30, 38):
        feed(runtime, backend, clock, offset, ttl=60, behavior_skew=1)
        if runtime.last_decision.timestamp < BASE + 35:
            assert len(rows_for(runtime, "bedtime_light_off")) == 1
    new = rows_for(runtime, "bedtime_light_off")[-1]
    assert new["source"]["timestamp"] - new["source"]["details"]["lying_seconds"] == BASE + 29
    assert runtime._revalidate(old, clock()) is not None
    assert runtime._revalidate(new, clock()) is None


def test_revalidation_after_skewed_gap_is_read_only_and_retry_keeps_identity(make_runtime):
    runtime, backend, clock = make_runtime()
    old, new = second_bedtime(runtime, backend, clock)
    engine, scenario = runtime.controller.realtime_engine, runtime.controller.bedtime_light

    def state():
        return (engine._now, engine.last_sensor_update, engine.last_appliance_update,
                deepcopy(vars(scenario)), deepcopy(runtime.controller.peek_outputs()),
                runtime.outbox.rows(), runtime.outbox.db.total_changes)

    before = state()
    for _ in range(3):
        assert runtime._revalidate(old, clock()) is not None
        assert runtime._revalidate(new, clock()) is None
    assert state() == before
    remapped = runtime.decision_mapper.map(scenario._request)
    assert remapped.source_id == new["source_id"]
    assert remapped.payload == new["payload"]
    backend.fail_after_accept = True
    runtime.dispatch_mock_once()
    assert rows_for(runtime, "bedtime_light_off")[-1]["status"] == "pending"
    for offset in (29, 30):
        feed(runtime, backend, clock, offset, ttl=3, behavior_skew=1)
    runtime.dispatch_mock_once()
    posts = [body for method, _, body in backend.requests if method == "POST"]
    assert len(posts) == 2 and posts[0] == posts[1]
    saved = rows_for(runtime, "bedtime_light_off")[-1]
    assert saved["source_id"] == new["source_id"] and saved["payload"] == new["payload"]
    assert saved["status"] == "accepted" and saved["response"]["duplicate"] is True


def test_restart_does_not_attach_pending_bedtime_to_new_skewed_episode(make_runtime):
    runtime, backend, clock = make_runtime()
    old = qualify_bedtime(runtime, backend, clock, ttl=3)
    config = runtime.config
    scenario_config = runtime.controller.bedtime_light.config
    runtime.close()
    controller = CentralController(confidence_data_dir=config.outbox_path.parent / "controller",
                                   scenario_config=scenario_config)
    restarted = IntegrationRuntime(config, BackendClient(config, backend), controller=controller, clock=clock)
    try:
        for offset in range(9, 17):
            feed(restarted, backend, clock, offset, ttl=3, behavior_skew=1)
            if restarted.last_decision.timestamp < BASE + 14:
                assert len(rows_for(restarted, "bedtime_light_off")) == 1
        old_saved, new = rows_for(restarted, "bedtime_light_off")
        assert clock() < old_saved["expires_at"]
        assert old_saved["source_id"] == old["source_id"] and old_saved["payload"] == old["payload"]
        assert new["source_id"] != old["source_id"]
        assert new["source"]["timestamp"] - new["source"]["details"]["lying_seconds"] == BASE + 8
        assert restarted._revalidate(old_saved, clock()) == "bedtime_request_no_longer_current"
        restarted.dispatch_mock_once()
        assert list(backend.accepted) == [new["payload"]["decisionId"]]
    finally:
        restarted.close()
