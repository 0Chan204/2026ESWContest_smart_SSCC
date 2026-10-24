"""Operational automation with only the actual Wi-Fi location and backend level contract."""
from copy import deepcopy
from dataclasses import replace

import pytest

from examples.backend_integration_demo import FakeClock
from src.alert_service import AlertService
from src.control.confidence.config import ConfidenceConfig
from src.integration.backend_client import BackendClient
from src.integration.runtime import IntegrationRuntime
from src.integration.schemas import iso_time, measured_time
from src.integration.settings import load_settings
from src.integration.simulation import SimulationBackend
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS


BASE = measured_time("2026-10-24T12:00:00+09:00")


class Rig:
    def __init__(self, path, **overrides):
        self.clock = FakeClock(BASE)
        config = load_settings(environ={}, mode="mock", data_dir=path).integration
        self.config = replace(config, allowed_lateness=0, async_alerts=False, **overrides)
        self.backend = SimulationBackend(self.clock)
        self.client = BackendClient(self.config, self.backend)
        self.runtime = IntegrationRuntime(self.config, self.client, clock=self.clock,
            fall_alert_service=AlertService(LLMMessageGenerator(), DryRunTTS(), path / "audio"))

    @property
    def stove(self):
        return self.backend.snapshot["items"][0]

    def step(self, offset, room, confidence=.95, *, poll=True, send=True):
        self.clock.now = BASE + offset
        if poll:
            self.runtime.ingest_device_states({"items": self.client.fetch_device_states()})
        self.runtime.ingest_location({"time": iso_time(self.clock()), "location": room,
                                      "location_confidence": confidence})
        self.runtime.advance()
        if send:
            for _ in range(8):
                self.runtime.dispatch_mock_once()

    def stay(self, start, end, room, **kwargs):
        for offset in range(start, end + 1):
            self.step(offset, room, **kwargs)

    def controls(self, device="stove"):
        return [a for payload, _ in self.backend.accepted.values() for a in payload["actions"]
                if a["device"] == device]

    def close(self):
        self.runtime.close()


@pytest.fixture
def rig(tmp_path):
    value = Rig(tmp_path)
    yield value
    value.close()


@pytest.mark.parametrize("level", [2, 5, 9])
def test_location_only_leave_reduce_return_restore_exactly_once(rig, level):
    rig.stove["current_state"]["level"] = level
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 45, "room")
    assert rig.controls() == []  # continuous 40-second absence has not elapsed
    rig.stay(46, 90, "room")
    assert rig.controls() == [{"device": "stove", "deviceId": "induction-01", "action": "set_level", "level": level - 1}]
    assert rig.stove["current_state"]["level"] == level - 1
    rig.stay(91, 94, "kitchen")
    assert len(rig.controls()) == 1
    rig.stay(95, 125, "kitchen")
    assert [a["action"] for a in rig.controls()] == ["set_level", "restore_power"]
    assert rig.stove["current_state"]["level"] == level
    sample = rig.runtime.controller.realtime_engine._sensing
    assert sample.activity_observed is False and sample.activity_confidence is None
    records = [r for r in rig.runtime.outbox.rows() if r["payload"] and r["payload"]["scenario"] == "stove_absence"]
    assert records[0]["source"]["explanation"]["features"]["stove_level"] == level / 9
    assert "stove_power" not in records[0]["source"]["explanation"]["features"]
    assert records[0]["payload"]["confidence"] >= .82


def test_light_location_only_on_off_and_return(rig):
    rig.stay(0, 4, "room")
    assert not rig.controls("light")
    rig.stay(5, 10, "room")
    assert [a["action"] for a in rig.controls("light")] == ["on"]
    rig.stay(11, 40, "kitchen")
    assert [a["action"] for a in rig.controls("light")] == ["on"]
    rig.stay(41, 50, "kitchen")
    assert [a["action"] for a in rig.controls("light")] == ["on", "off"]
    rig.stay(51, 62, "room")
    assert [a["action"] for a in rig.controls("light")] == ["on", "off", "on"]


@pytest.mark.parametrize("fault", ["user", "off", "hot", "temperature_missing", "different_level", "low_confidence", "fall"])
def test_restore_safety_guards_survive_operational_profile(rig, fault):
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 55, "room")
    assert rig.controls()[0]["action"] == "set_level"
    confidence = .95
    if fault == "user":
        rig.stove["control_state"] = "user"
    elif fault == "off":
        rig.stove["is_on"] = False
    elif fault == "hot":
        rig.stove["current_state"]["temperature"] = 250
    elif fault == "temperature_missing":
        rig.stove["current_state"].pop("temperature")
    elif fault == "different_level":
        rig.stove["current_state"]["level"] = 2
    elif fault == "low_confidence":
        confidence = .4
    else:
        rig.runtime.outbox.latch_fall(rig.clock(), "unresolved-fall")
    rig.stay(56, 100, "kitchen", confidence=confidence)
    assert not any(a["action"] == "restore_power" for a in rig.controls())


@pytest.mark.parametrize("level", [None, 0, 1, 10])
def test_missing_or_minimum_level_does_not_reduce(rig, level):
    rig.stove["current_state"]["level"] = level
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 80, "room")
    assert not rig.controls()


@pytest.mark.parametrize("room,confidence", [("unknown", .99), ("empty", .99), ("room", .3)])
def test_invalid_location_never_means_absence(rig, room, confidence):
    rig.stay(0, 6, "room")
    rig.stay(7, 80, room, confidence=confidence)
    assert not rig.controls()
    assert [a["action"] for a in rig.controls("light")] == ["on"]


def test_multiple_lights_follow_registered_rooms_and_exact_device_ids(rig):
    template = deepcopy(rig.backend.snapshot["items"][1])
    for room, identity in [("toilet", "light-00"), ("kitchen", "test-kitchen-light"), ("room", "test-second-room-light")]:
        rig.backend.snapshot["items"].append({**deepcopy(template), "room": room, "deviceId": identity})
    rig.stay(0, 10, "room")
    assert {a["deviceId"] for a in rig.controls("light")} == {"light-01", "test-second-room-light"}
    rig.stay(11, 50, "toilet")
    lights = rig.controls("light")
    assert {a["deviceId"] for a in lights if a["action"] == "off"} == {"light-01", "test-second-room-light"}
    assert any(a["deviceId"] == "light-00" and a["action"] == "on" for a in lights)
    rig.stay(51, 90, "kitchen")
    assert any(a["deviceId"] == "test-kitchen-light" and a["action"] == "on" for a in rig.controls("light"))
    assert any(a["deviceId"] == "light-00" and a["action"] == "off" for a in rig.controls("light"))


def test_legacy_weights_unchanged_and_profile_storage_is_separate(rig):
    legacy = ConfidenceConfig.for_profile("legacy")
    assert legacy.SCENARIO_WEIGHTS["kitchen_leave_reduce_power"]["stove_power"] == .2
    assert rig.runtime.controller.weight_manager.storage_path.name == "user_weights.location_level_v1.json"
    assert rig.runtime.controller.feedback_storage.path.name == "feedback.location_level_v1.jsonl"


def test_two_absence_cycles_restore_the_original_level_each_time(rig):
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 48, "room")
    rig.stay(49, 57, "kitchen")
    rig.stay(58, 100, "room")
    rig.stay(101, 110, "kitchen")
    assert [a["action"] for a in rig.controls()] == ["set_level", "restore_power", "set_level", "restore_power"]
    assert rig.stove["current_state"]["level"] == 5


def test_restart_keeps_reduction_provenance_but_requires_new_return_confirmation(rig):
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 48, "room")
    rig.runtime.close()
    rig.runtime = IntegrationRuntime(rig.config, rig.client, clock=rig.clock,
        fall_alert_service=AlertService(LLMMessageGenerator(), DryRunTTS(), rig.config.data_dir / "audio"))
    rig.stay(49, 53, "kitchen")
    assert len(rig.controls()) == 1
    rig.stay(54, 62, "kitchen")
    assert [a["action"] for a in rig.controls()] == ["set_level", "restore_power"]


def test_pending_restore_does_not_generate_multiple_http_commands(rig):
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 48, "room")
    rig.stay(49, 60, "kitchen", send=False)
    rows = [r for r in rig.runtime.outbox.rows(status="pending") if r["payload"] and
            any(a["action"] == "restore_power" for a in r["payload"]["actions"])]
    assert len(rows) == 1
    rig.step(61, "kitchen")
    rig.stay(62, 70, "kitchen")
    assert [a["action"] for a in rig.controls()] == ["set_level", "restore_power"]


def test_stale_backend_cannot_authorize_restore(rig):
    rig.stay(0, 5, "kitchen")
    rig.stay(6, 48, "room")
    rig.stay(49, 75, "room", poll=False)
    rig.stay(76, 90, "kitchen", poll=False)
    assert not any(a["action"] == "restore_power" for a in rig.controls())


def test_missing_extra_light_cannot_receive_queued_command(rig):
    template = deepcopy(rig.backend.snapshot["items"][1])
    rig.backend.snapshot["items"].append({**template, "room": "toilet", "deviceId": "light-00"})
    rig.stay(0, 6, "toilet", send=False)
    assert any(r["payload"] and r["payload"]["actions"][0].get("deviceId") == "light-00"
               for r in rig.runtime.outbox.rows(status="pending"))
    rig.backend.snapshot["items"].pop()
    rig.stay(7, 15, "toilet")
    assert not any(a["deviceId"] == "light-00" for a in rig.controls("light"))


def test_sleep_off_is_not_undone_by_location_auto_on(rig):
    from src.integration.sensing import BehaviorObservation
    rig.runtime.controller.bedtime_light.config = replace(rig.runtime.controller.bedtime_light.config,
                                                        BEDTIME_LYING_SECONDS=6)
    rig.stay(0, 6, "room")
    for offset in range(7, 25):
        rig.clock.now = BASE + offset
        rig.runtime.ingest_device_states({"items": rig.client.fetch_device_states()})
        rig.runtime.ingest_location({"time": iso_time(rig.clock()), "location": "room", "location_confidence": .95},
            behavior=BehaviorObservation(rig.clock(), rig.clock() + 5, "room", .95, "lying"))
        rig.runtime.advance()
        for _ in range(3):
            rig.runtime.dispatch_mock_once()
    assert [a["action"] for a in rig.controls("light")] == ["on", "off"]


def test_event_time_buffer_and_five_second_heartbeats_still_complete_cycle(tmp_path):
    value = Rig(tmp_path)
    # Match the live runner's reordering margin and the backend's real heartbeat cadence.
    value.runtime.config = value.config = replace(value.config, allowed_lateness=4)
    value.client.config = value.config
    snapshot = None
    try:
        for offset in range(85):
            value.clock.now = BASE + offset
            if offset % 5 == 0:
                snapshot = {"items": value.client.fetch_device_states()}
            value.runtime.ingest_device_states(deepcopy(snapshot))
            room = "kitchen" if offset < 10 or offset >= 65 else "room"
            value.runtime.ingest_location({"time": iso_time(value.clock()), "location": room, "location_confidence": .95})
            value.runtime.advance()
            for _ in range(5):
                value.runtime.dispatch_mock_once()
        assert [a["action"] for a in value.controls()] == ["set_level", "restore_power"]
    finally:
        value.close()
