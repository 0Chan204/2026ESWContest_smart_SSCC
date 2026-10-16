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
         behavior_confidence=.95, behavior_valid=True):
    """Poll every 2s, sense/evaluate every 1s; behavior is an explicit synthetic observation."""
    clock.now = BASE + offset
    payload = {"time": iso_time(clock.now), "location": room, "location_confidence": .95}
    behavior = None if activity is None else BehaviorObservation(
        clock.now, clock.now + ttl, "bedroom" if room == "room" else room,
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
