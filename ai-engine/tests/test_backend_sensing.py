"""Backend v0.10 combined results through the same HTTP/MQTT input boundary."""
from concurrent.futures import Future
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from src.control.bathroom_fall import BathroomFallScenario
from src.control.realtime_config import RealtimeConfig
from src.control.scenario_config import ScenarioConfig
from src.control.scenario_models import BathroomFallState
from src.integration.backend_client import BackendClient, BackendError, HTTPResult
from src.integration.backend_sensing import BackendSensingSource, normalize_result
from src.integration.config import IntegrationConfig
from src.integration.mqtt_source import Incoming, InputRouter, parse_behavior
from src.integration.runtime import IntegrationRuntime
from src.integration.schemas import ContractError, iso_time, measured_time
from src.integration.sensing import join_behavior, location_observation, presence_evidence
from src.integration.settings import MQTTSettings, load_settings
from src.integration.simulation import SimulationBackend
from src.interaction.backend import VoiceBackend
from src.interaction.config import VoiceConfig
from src.interaction.response import VoiceResponseService
from src.llm.config import LLMConfig


AT = measured_time("2026-10-27T21:00:02+09:00")


def result(**overrides):
    return {"resultId": "res-20261027-000123", "observedAt": "2026-10-27T21:00:02+09:00",
            "savedAt": "2026-10-27T12:00:02.150+00:00", "room": "kitchen", "present": True,
            "confidence": .91, "presenceReason": None, "activity": "standing",
            "activityConfidence": .80, "activityReason": None, "modelVersion": "fusion-0.2",
            "validSec": 5, **overrides}


def observations(raw, received_at=AT):
    payload = normalize_result(raw)
    location = location_observation(payload, received_at, IntegrationConfig())
    behavior = parse_behavior(payload["behavior"]) if "behavior" in payload else None
    return location, behavior, join_behavior(location, behavior, 1)


def presence(location):
    return presence_evidence(location, allowed_lateness=4, max_age=10, min_confidence=.8)


class CombinedResultTests(unittest.TestCase):
    def test_postures_preserve_independent_confidence_and_measurement_time(self):
        for activity in ("standing", "sitting", "lying"):
            with self.subTest(activity=activity):
                raw = result(activity=activity)
                location, behavior, sample = observations(raw)
                self.assertTrue(location.valid)
                self.assertEqual(location.raw["backend_result"], raw)
                self.assertEqual((sample.confidence, sample.activity_confidence), (.91, .80))
                self.assertEqual((sample.timestamp, sample.activity_timestamp), (AT, AT))
                self.assertEqual((location.valid_until, sample.activity_valid_until), (AT + 5, AT + 5))
                self.assertTrue(sample.activity_observed)
                self.assertEqual(sample.activity, activity)
                self.assertIsNone(sample.motion_state)
                self.assertIsNone(sample.fall_detected)

    def test_indeterminate_presence_is_never_a_room_or_absence(self):
        for room in (None, "kitchen"):
            for confidence in (None, .99):
                with self.subTest(room=room, confidence=confidence):
                    location, _, sample = observations(result(
                        room=room, present=None, confidence=confidence, presenceReason="warming_up",
                        activity="unknown", activityConfidence=None, activityReason="gap"))
                    self.assertFalse(location.valid)
                    self.assertEqual(sample.location, "unknown")
                    self.assertFalse(sample.activity_observed)
                    self.assertIsNone(presence(location))
                    self.assertEqual(location.raw["reason"], "warming_up")
                    self.assertEqual(location.raw["backend_result"]["activityReason"], "gap")

    def test_unknown_activity_does_not_invalidate_presence_or_become_safe_behavior(self):
        for confidence in (None, .99):
            for reason in (None, "gap", "no_csi", "config_mismatch", "low_confidence", "new_reason"):
                with self.subTest(confidence=confidence, reason=reason):
                    location, behavior, sample = observations(result(
                        activity="unknown", activityConfidence=confidence, activityReason=reason))
                    self.assertTrue(location.valid)
                    self.assertTrue(presence(location)["present"])
                    self.assertFalse(sample.activity_observed)
                    self.assertEqual(behavior.reason, reason or "activity_unknown")
                    self.assertEqual(sample.activity, "unknown")

    def test_presence_reason_blocks_presence_without_erasing_behavior(self):
        for reason in ("warming_up", "gap", "no_csi", "config_mismatch", "low_confidence"):
            with self.subTest(reason=reason):
                location, behavior, sample = observations(result(presenceReason=reason))
                self.assertFalse(location.valid)
                self.assertIsNone(presence(location))
                self.assertIsNone(behavior.reason)
                self.assertEqual(behavior.activity, "standing")
                self.assertFalse(sample.activity_observed)

    def test_activity_reason_does_not_invalidate_presence(self):
        location, behavior, sample = observations(result(activityReason="low_confidence"))
        self.assertTrue(location.valid)
        self.assertEqual(behavior.reason, "low_confidence")
        self.assertFalse(sample.activity_observed)

    def test_explicit_absence_requires_null_room_and_no_presence_diagnostic(self):
        location, _, sample = observations(result(room=None, present=False, activity="unknown",
                                                activityConfidence=None, activityReason="no_csi"))
        self.assertEqual(location.raw["location"], "empty")
        self.assertFalse(presence(location)["present"])
        self.assertFalse(sample.activity_observed)
        for changes in ({"room": "kitchen"}, {"presenceReason": "gap"}, {"present": None}):
            with self.subTest(changes=changes):
                location, _, _ = observations(result(**{"room": None, "present": False, **changes}))
                self.assertIsNone(presence(location))

    def test_missing_zero_and_expired_validity_never_authorize_observation(self):
        for ttl, received_at in ((None, AT), (0, AT), (5, AT + 5), (5, AT + 6)):
            with self.subTest(ttl=ttl, received_at=received_at):
                location, _, sample = observations(result(validSec=ttl, savedAt=iso_time(received_at)), received_at)
                self.assertFalse(location.valid)
                self.assertFalse(sample.activity_observed)
                self.assertIsNone(presence(location))

    def test_invalid_field_types_and_confidences_are_rejected(self):
        for field, value in (("present", "false"), ("room", "empty"), ("room", []),
                             ("presenceReason", False), ("activityReason", {}), ("activity", []),
                             ("confidence", True), ("activityConfidence", 1.1),
                             ("activityConfidence", float("nan")), ("validSec", True), ("validSec", -1)):
            with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                normalize_result(result(**{field: value}))

    def test_unknown_does_not_clear_existing_fall_or_accumulate_stillness(self):
        scenario = BathroomFallScenario(ScenarioConfig(), RealtimeConfig())
        _, _, fall = observations(result(room="toilet", activity="fall", activityConfidence=.99))
        first = scenario.update(fall)
        self.assertEqual(first.state, BathroomFallState.FALL_SUSPECTED)
        self.assertIsNotNone(first.incident_id)
        for second in range(1, 8):
            _, _, unknown = observations(result(
                observedAt=iso_time(AT + second), room="toilet", activity="unknown",
                activityConfidence=.99, activityReason="gap", motion_state="moving", fall_detected=False), AT + second)
            current = scenario.update(unknown)
            self.assertEqual(current.state, first.state)
            self.assertEqual(current.incident_id, first.incident_id)
            self.assertFalse(unknown.activity_observed)


class CombinedTransportTests(unittest.TestCase):
    def test_combined_result_cannot_fall_back_to_older_separate_behavior(self):
        mqtt = MQTTSettings(behavior_topic="legacy/behavior", join_wait_seconds=0)
        for changes in ({"activity": "unknown", "activityConfidence": None, "activityReason": "gap"},
                        {"activity": "unknown", "activityConfidence": .99},
                        {"activityConfidence": None}, {"validSec": None},
                        {"room": None, "present": None}):
            with self.subTest(changes=changes):
                runtime = Mock(config=IntegrationConfig())
                router = InputRouter(mqtt, runtime)
                older = {"time": iso_time(AT - .5), "valid_until": iso_time(AT + 5),
                         "location": "kitchen", "confidence": .99, "activity": "fall"}
                router.accept(Incoming(mqtt.behavior_topic, json.dumps(older).encode(), AT))
                router.accept(Incoming(mqtt.location_topic, json.dumps(result(**changes)).encode(), AT))
                router.flush(AT)
                runtime.ingest_location.assert_called_once()
                call = runtime.ingest_location.call_args
                location = location_observation(call.args[0], AT, runtime.config)
                self.assertFalse(join_behavior(location, call.kwargs["behavior"], 1).activity_observed)
                runtime.invalidate_sensing.assert_not_called()

    def test_legacy_direct_location_still_joins_separate_behavior(self):
        mqtt = MQTTSettings(location_topic="wifi/occupancy/state", behavior_topic="legacy/behavior", join_wait_seconds=0)
        runtime = Mock(config=IntegrationConfig())
        router = InputRouter(mqtt, runtime)
        behavior = {"time": iso_time(AT), "valid_until": iso_time(AT + 5),
                    "location": "kitchen", "confidence": .8, "activity": "sitting"}
        router.accept(Incoming(mqtt.behavior_topic, json.dumps(behavior).encode(), AT))
        location = {"time": iso_time(AT), "location": "kitchen", "location_confidence": .9}
        router.accept(Incoming(mqtt.location_topic, json.dumps(location).encode(), AT))
        router.flush(AT)
        self.assertEqual(runtime.ingest_location.call_args.kwargs["behavior"].activity, "sitting")

    def test_http_poll_accepts_both_valid_and_indeterminate_results(self):
        settings = load_settings(environ={}, mode="mock")
        source = BackendSensingSource(settings, Mock(), clock=lambda: AT)
        self.addCleanup(source.close)
        source.next_poll = float("inf")
        source.future = Future()
        source.future.set_result([result(), result(room=None, present=None, confidence=None,
            presenceReason="warming_up", activity="unknown", activityConfidence=None, activityReason="gap")])
        messages = source.drain()
        self.assertEqual(len(messages), 2)
        self.assertTrue(all(isinstance(message, Incoming) for message in messages))
        self.assertEqual((source.received, source.rejected), (2, 0))
        self.assertEqual(json.loads(messages[1].payload)["presenceReason"], "warming_up")

    def test_history_endpoint_and_order_are_unchanged(self):
        items = [result(observedAt=iso_time(AT - 1)), result()]
        transport = Mock()
        transport.request.return_value = HTTPResult(200, {"items": items})
        client = BackendClient(IntegrationConfig(), transport)
        self.assertEqual(client.fetch_sensing_results(AT - 1), items)
        url = urlsplit(transport.request.call_args.args[1])
        self.assertEqual(url.path, "/api/v1/sensing/results")
        self.assertEqual(parse_qs(url.query), {"since": [iso_time(AT - 1)], "limit": ["5000"]})

    def test_runtime_keeps_presence_with_unknown_activity_and_expires_at_validsec(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [AT]
            settings = load_settings(environ={}, mode="mock", data_dir=Path(directory))
            config = replace(settings.integration, allowed_lateness=0, llm_config=LLMConfig(provider="none"))
            client = BackendClient(config, SimulationBackend(clock=lambda: now[0]))
            runtime = IntegrationRuntime(config, client, clock=lambda: now[0])
            router = InputRouter(replace(settings.mqtt, join_wait_seconds=0), runtime)
            try:
                for second in range(7):
                    now[0] = AT + second
                    raw = result(observedAt=iso_time(now[0]), activity="unknown", activityConfidence=None, activityReason="gap")
                    router.accept(Incoming(settings.mqtt.location_topic, json.dumps(raw).encode(), now[0]))
                    router.flush(now[0])
                    decision = runtime.advance(now[0])
                self.assertTrue(decision.observation_valid)
                self.assertEqual(decision.user_location, "kitchen")
                self.assertFalse(runtime._latest_received_sample.activity_observed)
                self.assertEqual(runtime.missing_inputs["bedtime_light"], ["activity"])
                now[0] += 5
                self.assertFalse(runtime.advance(now[0]).observation_valid)
                self.assertEqual(runtime.sensing_health(now[0])["status"], "invalid")
            finally:
                runtime.close()


class LatestPresenceTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.backend = VoiceBackend(self.client, VoiceConfig(), clock=lambda: AT)

    def response(self, raw):
        self.client._request.return_value = HTTPResult(200, raw)
        facts = {"presence": self.backend.presence(AT + 10)}
        return VoiceResponseService.status({"query": "presence"}, facts, AT, 20, "voice-test")

    def test_latest_uses_presence_independently_of_unknown_activity(self):
        text = self.response(result(activity="unknown", activityConfidence=None, activityReason="gap"))
        self.assertIn("주방에 사람이 감지", text)
        self.assertEqual(self.client._request.call_args.args[:2], ("GET", "/api/v1/sensing/results/latest"))

    def test_indeterminate_or_diagnostic_presence_is_not_announced_as_absence(self):
        for changes in ({"present": None, "room": None, "confidence": None, "presenceReason": "warming_up"},
                        {"presenceReason": "no_csi"}, {"present": False}):
            with self.subTest(changes=changes):
                self.assertIn("확인할 수 없습니다", self.response(result(**changes)))

    def test_latest_stale_missing_or_invalid_validity_is_rejected(self):
        for changes in ({"observedAt": iso_time(AT - 5)}, {"validSec": None}, {"validSec": 0},
                        {"validSec": 1.5}, {"observedAt": iso_time(AT + 1)}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.response(result(**changes))

    def test_latest_404_is_unavailable_not_an_empty_house(self):
        self.client._request.return_value = HTTPResult(404, {})
        with self.assertRaises(BackendError) as caught:
            self.backend.presence(AT + 10)
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
