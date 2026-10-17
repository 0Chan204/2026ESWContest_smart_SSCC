from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.alert_service import AlertService
from src.control import CentralController, DeviceState, SensingState
from src.llm.message_generator import LLMMessageGenerator
from src.models import RiskLevel
from src.voice.tts import DryRunTTS


class CentralControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = CentralController()

    def assert_decision(self, location, stove_on, situation, risk, **kwargs):
        decision = self.controller.evaluate(
            SensingState(location=location, **kwargs),
            DeviceState(stove_on=stove_on, heat_level="medium"),
        )
        self.assertEqual(decision.situation.value, situation)
        self.assertEqual(decision.risk.value, risk)
        return decision

    def test_cooking(self):
        self.assert_decision("STOVE_AREA", True, "COOKING", "SAFE", activity="cooking")

    def test_temporary_away(self):
        self.assert_decision("KITCHEN", True, "TEMP_AWAY", "LOW", activity="moving")

    def test_away_in_another_room(self):
        self.assert_decision("OTHER_ROOM", True, "IN_HOME_AWAY", "LOW", away_duration=10)

    def test_home_exit_with_stove_on(self):
        self.assert_decision("OUTSIDE_HOME", True, "HOME_EXIT_WITH_STOVE_ON", "HIGH")

    def test_stove_off_takes_precedence_over_location(self):
        self.assert_decision("OUTSIDE_HOME", False, "STOVE_OFF", "SAFE")

    def test_unknown_location_uses_separate_policy(self):
        self.assert_decision("UNKNOWN", True, "LOCATION_UNKNOWN", "LOW")

    def test_high_decision_integrates_with_alert_service(self):
        control = self.assert_decision(
            "OUTSIDE_HOME", True, "HOME_EXIT_WITH_STOVE_ON", "HIGH", away_duration=15
        )
        risk = control.to_risk_decision()
        self.assertEqual(risk.risk_level, RiskLevel.HIGH)
        self.assertEqual(risk.user_state, "OUT")
        self.assertEqual(risk.device, "stove")
        with tempfile.TemporaryDirectory() as tmp:
            service = AlertService(LLMMessageGenerator(llm=None), DryRunTTS(), tmp)
            output = service.handle(risk)
            self.assertTrue(output.warning_sound)
            self.assertTrue(output.voice)
            self.assertTrue(output.message)
            self.assertIsNotNone(output.tts_file)
            self.assertTrue(Path(output.tts_file).exists())


if __name__ == "__main__":
    unittest.main()
