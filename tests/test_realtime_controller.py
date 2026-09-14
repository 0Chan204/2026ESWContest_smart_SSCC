import tempfile
import unittest
from pathlib import Path

from src.control import CentralController, RealtimeConfig, SensingUpdate, ApplianceUpdate
from src.alert_service import AlertService
from src.llm.message_generator import LLMMessageGenerator
from src.models import RiskDecision
from src.voice.tts import DryRunTTS


class RealtimeControllerTest(unittest.TestCase):
    def setUp(self):
        self.c = CentralController()

    def sample(self, t, location="kitchen", **device):
        self.c.update_appliance(ApplianceUpdate(True, t, **device))
        return self.c.update_sensing(SensingUpdate(location, t))

    def start(self):
        self.sample(0)
        return self.sample(5)

    def away(self, end, **device):
        self.start()
        self.sample(10, "living_room", **device)
        result = self.sample(15, "living_room", **device)
        for t in range(20, end, 5):
            result = self.sample(t, "living_room", **device)
        return self.sample(end, "living_room", **device) if end > 15 else result

    def test_initial_confirmation_and_normal(self):
        self.assertEqual(self.sample(0).state, "SENSOR_UNCERTAIN")
        self.assertEqual(self.sample(5).state, "NORMAL")

    def test_absence_boundaries(self):
        for end, expected in [(15, "TEMPORARY_ABSENCE"), (39, "TEMPORARY_ABSENCE"),
                              (40, "CAUTION"), (129, "CAUTION"), (130, "WARNING"),
                              (309, "WARNING"), (310, "DANGER")]:
            with self.subTest(end=end):
                self.c = CentralController()
                result = self.away(end)
                self.assertEqual(result.state, expected)
                self.assertEqual(result.kitchen_absence_seconds, end - 10)

    def test_outside_requires_continuous_confirmation(self):
        self.start()
        self.assertEqual(self.sample(10, "outside").state, "NORMAL")
        self.assertEqual(self.sample(19, "outside").state, "NORMAL")
        self.assertEqual(self.sample(20, "outside").state, "DANGER")

    def test_glitch_does_not_start_absence(self):
        self.start()
        self.sample(6, "outside")
        result = self.sample(8)
        self.assertEqual(result.state, "NORMAL")
        self.assertEqual(result.kitchen_absence_seconds, 0)

    def test_entrance_confirmation(self):
        self.start()
        self.sample(10, "living_room")
        self.sample(15, "living_room")
        self.sample(20, "entrance")
        self.assertEqual(self.sample(29, "entrance").state, "TEMPORARY_ABSENCE")
        self.assertEqual(self.sample(30, "entrance").state, "WARNING")

    def test_return_recovered_then_normal(self):
        self.away(130)
        self.assertEqual(self.c.update_sensing(SensingUpdate("kitchen", 131)).state, "WARNING")
        self.assertEqual(self.c.update_sensing(SensingUpdate("kitchen", 136)).state, "RECOVERED")
        self.assertEqual(self.c.tick(137).state, "NORMAL")
        self.assertEqual(self.c.realtime_engine.current_absence_duration, 0)

    def test_off_recovers(self):
        self.away(130)
        self.assertEqual(self.c.update_appliance(ApplianceUpdate(False, 131)).state, "RECOVERED")
        self.assertEqual(self.c.tick(132).state, "NORMAL")

    def test_unknown_grace_and_timeout(self):
        self.start()
        self.c.update_sensing(SensingUpdate("unknown", 10))
        self.c.update_appliance(ApplianceUpdate(True, 29))
        self.assertEqual(self.c.update_sensing(SensingUpdate("unknown", 29)).state, "NORMAL")
        result = self.c.tick(30)
        self.assertEqual(result.state, "SENSOR_UNCERTAIN")
        self.assertEqual(result.user_location, "kitchen")

    def test_low_confidence_is_not_outside(self):
        self.start()
        self.c.update_sensing(SensingUpdate("outside", 10, confidence=0.1))
        self.c.update_appliance(ApplianceUpdate(True, 30))
        result = self.c.update_sensing(SensingUpdate("outside", 30, confidence=0.1))
        self.assertEqual(result.state, "SENSOR_UNCERTAIN")
        self.assertNotEqual(result.user_location, "outside")

    def test_explicit_non_detection_preserves_location_then_uncertain(self):
        self.start()
        self.c.update_sensing(SensingUpdate("unknown", 10, detected=False))
        result = self.c.update_sensing(SensingUpdate("unknown", 20, detected=False))
        self.assertEqual(result.user_location, "kitchen")
        self.assertNotEqual(result.state, "DANGER")
        self.assertEqual(self.c.tick(30).state, "SENSOR_UNCERTAIN")

    def test_missing_updates_do_not_confirm_outside(self):
        self.start()
        self.c.update_sensing(SensingUpdate("outside", 10))
        self.assertNotEqual(self.c.tick(20).state, "DANGER")
        self.c.update_appliance(ApplianceUpdate(True, 30))
        self.assertEqual(self.c.tick(30).state, "SENSOR_UNCERTAIN")
        self.assertNotEqual(self.c.update_sensing(SensingUpdate("outside", 31)).state, "DANGER")

    def test_stale_appliance(self):
        self.start()
        self.c.update_sensing(SensingUpdate("kitchen", 20))
        self.assertTrue(self.c.tick(25).appliance_stale)
        self.assertEqual(self.c.tick(25).state, "SENSOR_UNCERTAIN")

    def test_uncertain_high_output_warns(self):
        self.c.update_appliance(ApplianceUpdate(True, 0, power_watts=2000))
        self.assertEqual(self.c.tick(0).state, "WARNING")

    def test_emergencies_even_when_off(self):
        for flag in ("smoke", "fire", "abnormal"):
            with self.subTest(flag=flag):
                c = CentralController()
                self.assertEqual(c.update_appliance(ApplianceUpdate(False, 0, **{flag: True})).state, "DANGER")

    def test_rapid_temperature_rise(self):
        self.sample(0, temperature_c=50)
        self.assertEqual(self.sample(5, temperature_c=100).state, "DANGER")

    def test_high_and_rising_escalates(self):
        self.away(125, power_watts=2000, temperature_c=100)
        result = self.sample(130, "living_room", power_watts=2000, temperature_c=110)
        self.assertEqual(result.state, "DANGER")

    def test_danger_retained_on_missing_data(self):
        self.start()
        self.sample(10, "outside")
        self.sample(20, "outside")
        self.assertEqual(self.c.tick(60).state, "DANGER")

    def test_time_validation_does_not_mutate(self):
        self.start()
        for t in (4, 5, float("nan")):
            with self.assertRaises(ValueError):
                self.c.update_sensing(SensingUpdate("outside", t))
        self.assertEqual(self.c.realtime_engine.last_user_location, "kitchen")

    def test_configuration_and_raw_validation(self):
        with self.assertRaises(ValueError):
            RealtimeConfig(KITCHEN_SHORT_ABSENCE=500)
        with self.assertRaises(ValueError):
            ApplianceUpdate(True, 0, power_watts=float("inf"))
        c = CentralController(config=RealtimeConfig(SENSING_CONFIRM_TIME=1, RETURN_CONFIRM_TIME=1))
        c.update_appliance(ApplianceUpdate(True, 0))
        c.update_sensing(SensingUpdate("kitchen", 0))
        self.assertEqual(c.update_sensing(SensingUpdate("kitchen", 1)).state, "NORMAL")

    def test_existing_alert_pipeline_and_serialization(self):
        decision = self.away(130)
        risk = decision.to_risk_decision()
        self.assertEqual(RiskDecision.from_dict(risk.to_dict()), risk)
        self.assertEqual(risk.decision_context["state"], "WARNING")
        with tempfile.TemporaryDirectory() as tmp:
            result = AlertService(LLMMessageGenerator(llm=None), DryRunTTS(), tmp).handle(risk)
            self.assertTrue(result.voice)
            self.assertTrue(Path(result.tts_file).exists())
        self.assertNotIn("decision_context", RiskDecision("NORMAL").to_dict())


if __name__ == "__main__":
    unittest.main()
