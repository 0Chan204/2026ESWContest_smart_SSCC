"""Internal fall workflow; backend transport waits for a confirmed API contract."""
import tempfile
import unittest
from pathlib import Path

from src.alert_service import AlertService
from src.control import CentralController, FallBackendSignal, SensingUpdate
from src.integration import IntegrationConfig, IntegrationRuntime
from src.integration.backend_client import BackendClient
from src.integration.mock_backend import MockBackend
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS


class FallWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controller = CentralController(confidence_data_dir=Path(self.temp.name) / "controller")

    def sense(self, at, *, fall=False, motion="still"):
        self.controller.update_sensing(SensingUpdate(
            "toilet", at, activity="lying", motion_state=motion,
            fall_detected=fall, confidence=.95,
        ))
        return self.controller.bathroom_decision

    def test_caregiver_safe_closes_incident_without_report_or_retrigger(self):
        incident = self.sense(0, fall=True).incident_id
        self.controller.drain_scenario_actions()
        self.sense(5)
        self.sense(10)
        self.assertEqual([item.event for item in self.controller.drain_scenario_actions()], [
            "fall_user_alert_requested", "fall_caregiver_alert_requested"])
        decision = self.controller.update_fall_backend_signal(FallBackendSignal(
            11, caregiver_status="safe", incident_id=incident))
        self.assertEqual(decision.state, "RESOLVED_BY_CAREGIVER")
        self.assertEqual(decision.risk, "NORMAL")
        self.sense(30, fall=True)
        self.assertEqual(self.controller.drain_scenario_actions(), [])
        self.assertEqual(self.controller.bathroom_decision.state, "RESOLVED_BY_CAREGIVER")

    def test_no_response_waits_for_emergency_threshold_and_emits_once(self):
        incident = self.sense(0, fall=True).incident_id
        self.controller.drain_scenario_actions()
        self.sense(10)
        self.controller.drain_scenario_actions()
        self.controller.update_fall_backend_signal(FallBackendSignal(
            11, caregiver_status="no_response", incident_id=incident))
        self.assertEqual(self.controller.drain_scenario_actions(), [])
        self.sense(20)
        self.sense(30)
        actions = self.controller.drain_scenario_actions()
        self.assertEqual([item.event for item in actions], ["fall_emergency_report_requested"])
        self.assertEqual(actions[0].details["incident_id"], incident)
        self.sense(35)
        self.assertEqual(self.controller.drain_scenario_actions(), [])

    def test_stale_or_premature_caregiver_response_is_rejected(self):
        incident = self.sense(0, fall=True).incident_id
        with self.assertRaisesRegex(ValueError, "before the caregiver alert"):
            self.controller.update_fall_backend_signal(FallBackendSignal(
                1, caregiver_status="safe", incident_id=incident))
        self.sense(10)
        with self.assertRaisesRegex(ValueError, "incident_id"):
            self.controller.update_fall_backend_signal(FallBackendSignal(
                11, caregiver_status="safe", incident_id="different"))
        self.assertEqual(self.controller.bathroom_decision.state, "FALL_WARNING")

    def test_runtime_speaks_stage_one_and_keeps_backend_stages_local(self):
        config = IntegrationConfig(data_dir=Path(self.temp.name) / "integration")
        backend = MockBackend(lambda: 0)
        alert = AlertService(LLMMessageGenerator(), DryRunTTS(), Path(self.temp.name) / "audio")
        runtime = IntegrationRuntime(config, BackendClient(config, backend),
                                     clock=lambda: 0, fall_alert_service=alert)
        self.addCleanup(runtime.close)
        runtime.controller.update_sensing(SensingUpdate(
            "toilet", 0, activity="lying", motion_state="still", fall_detected=True))
        runtime.collect_outputs(0)
        incident = runtime.outbox.fall_incident()["local_incident_id"]
        runtime.controller.update_sensing(SensingUpdate(
            "toilet", 5, activity="lying", motion_state="still"))
        runtime.collect_outputs(5)
        spoken = runtime.outbox.audits("fall_user_alert")
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0]["incident_id"], incident)
        self.assertTrue(Path(spoken[0]["result"]["tts_file"]).exists())
        runtime.controller.update_sensing(SensingUpdate(
            "toilet", 10, activity="lying", motion_state="still"))
        runtime.collect_outputs(10)
        caregiver = [row for row in runtime.outbox.rows()
                     if row["source"].get("event") == "fall_caregiver_alert_requested"]
        self.assertEqual(len(caregiver), 1)
        self.assertIsNone(caregiver[0]["payload"])
        self.assertFalse(backend.requests)

        resolved = runtime.receive_fall_backend_signal(FallBackendSignal(
            11, caregiver_status="safe", incident_id=incident))
        self.assertEqual(resolved.state, "RESOLVED_BY_CAREGIVER")
        self.assertIsNone(runtime.outbox.fall_incident())
        self.assertEqual(runtime.outbox.audits("fall_caregiver_response")[-1]["status"], "safe")

    def test_runtime_rejects_unmatched_or_unconfirmed_backend_result(self):
        config = IntegrationConfig(data_dir=Path(self.temp.name) / "integration")
        backend = MockBackend(lambda: 0)
        runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=lambda: 0,
                                     fall_alert_service=AlertService(
                                         LLMMessageGenerator(), DryRunTTS(), Path(self.temp.name) / "audio"))
        self.addCleanup(runtime.close)
        runtime.controller.update_sensing(SensingUpdate(
            "toilet", 0, activity="lying", motion_state="still", fall_detected=True))
        runtime.collect_outputs(0)
        with self.assertRaisesRegex(ValueError, "identify the unresolved"):
            runtime.receive_fall_backend_signal(FallBackendSignal(
                10, caregiver_status="no_response", incident_id="wrong"))
        with self.assertRaisesRegex(ValueError, "explicit caregiver_status"):
            runtime.receive_fall_backend_signal(FallBackendSignal(10, True))

    def test_runtime_no_response_records_report_request_without_unconfirmed_http(self):
        config = IntegrationConfig(data_dir=Path(self.temp.name) / "integration")
        backend = MockBackend(lambda: 0)
        runtime = IntegrationRuntime(config, BackendClient(config, backend), clock=lambda: 0,
                                     fall_alert_service=AlertService(
                                         LLMMessageGenerator(), DryRunTTS(), Path(self.temp.name) / "audio"))
        self.addCleanup(runtime.close)
        for at in (0, 5, 10):
            runtime.controller.update_sensing(SensingUpdate(
                "toilet", at, activity="lying", motion_state="still", fall_detected=at == 0))
            runtime.collect_outputs(at)
        incident = runtime.outbox.fall_incident()["local_incident_id"]
        runtime.receive_fall_backend_signal(FallBackendSignal(
            11, caregiver_status="no_response", incident_id=incident))
        for at in (20, 30):
            runtime.controller.update_sensing(SensingUpdate(
                "toilet", at, activity="lying", motion_state="still"))
            runtime.collect_outputs(at)
        reports = [row for row in runtime.outbox.rows()
                   if row["source"].get("event") == "fall_emergency_report_requested"]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertIsNone(reports[0]["payload"])
        self.assertEqual(runtime.outbox.fall_incident()["local_incident_id"], incident)
        self.assertFalse(backend.requests)

    def test_safe_response_can_close_persisted_incident_after_restart(self):
        config = IntegrationConfig(data_dir=Path(self.temp.name) / "integration")
        backend = MockBackend(lambda: 0)
        client = BackendClient(config, backend)
        alert = AlertService(LLMMessageGenerator(), DryRunTTS(), Path(self.temp.name) / "audio")
        runtime = IntegrationRuntime(config, client, clock=lambda: 0, fall_alert_service=alert)
        try:
            for at in (0, 5, 10):
                runtime.controller.update_sensing(SensingUpdate(
                    "toilet", at, activity="lying", motion_state="still", fall_detected=at == 0))
                runtime.collect_outputs(at)
            incident = runtime.outbox.fall_incident()["local_incident_id"]
        finally:
            runtime.close()

        restarted = IntegrationRuntime(config, client, clock=lambda: 0, fall_alert_service=alert)
        try:
            result = restarted.receive_fall_backend_signal(FallBackendSignal(
                11, caregiver_status="safe", incident_id=incident))
            self.assertEqual(result.state, "RESOLVED_BY_CAREGIVER")
            self.assertIsNone(restarted.outbox.fall_incident())
        finally:
            restarted.close()


if __name__ == "__main__":
    unittest.main()
