from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from src.control import (
    ApplianceUpdate, CentralController, FallBackendSignal, ScenarioConfig, SensingUpdate,
)


KST = timezone(timedelta(hours=9))


class ExtendedScenarioTest(unittest.TestCase):
    def make_controller(self, tmp: str, **config) -> CentralController:
        return CentralController(
            scenario_config=ScenarioConfig(**config),
            water_purifier_available=True,
            confidence_data_dir=Path(tmp),
        )

    @staticmethod
    def at(day: int, hour: int, minute: int = 0, second: int = 0) -> float:
        return datetime(2026, 9, day, hour, minute, second, tzinfo=KST).timestamp()

    @staticmethod
    def complete_wake(controller: CentralController, base: float) -> None:
        for offset, location, activity in (
            (0, "room", "lying"),
            (1, "room", "standing"),
            (6, "room", "standing"),
            (7, "living_room", "walking"),
            (8, "kitchen", "standing"),
            (13, "kitchen", "standing"),
        ):
            controller.update_sensing(SensingUpdate(location, base + offset, activity=activity))

    def test_bedtime_lying_requests_light_off_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = self.make_controller(tmp, BEDTIME_LYING_SECONDS=10)
            base = self.at(15, 22)
            controller.update_sensing(SensingUpdate("room", base, activity="lying"))
            controller.update_sensing(SensingUpdate("room", base + 9, activity="lying"))
            self.assertEqual(controller.drain_scenario_actions(), [])
            controller.update_sensing(SensingUpdate("room", base + 10, activity="lying"))
            actions = controller.drain_scenario_actions()
            self.assertEqual([(action.action, action.target) for action in actions], [
                ("turn_off", "light")
            ])
            controller.update_sensing(SensingUpdate("room", base + 11, activity="lying"))
            self.assertEqual(controller.drain_scenario_actions(), [])

    def test_bedtime_timer_resets_when_lying_is_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = self.make_controller(tmp, BEDTIME_LYING_SECONDS=10)
            base = self.at(15, 22)
            controller.update_sensing(SensingUpdate("room", base, activity="lying"))
            controller.update_sensing(SensingUpdate("room", base + 8, activity="standing"))
            controller.update_sensing(SensingUpdate("room", base + 9, activity="lying"))
            controller.update_sensing(SensingUpdate("room", base + 18, activity="lying"))
            self.assertEqual(controller.drain_scenario_actions(), [])
            controller.update_sensing(SensingUpdate("room", base + 19, activity="lying"))
            self.assertEqual(controller.drain_scenario_actions()[0].target, "light")

    def test_fall_emits_device_safety_and_staged_backend_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = self.make_controller(
                tmp,
                FALL_CONFIRM_SECONDS=2,
                FALL_WARNING_SECONDS=4,
                FALL_EMERGENCY_SECONDS=6,
                LONG_UNRESPONSIVE_SECONDS=8,
                RECOVERY_CONFIRM_SECONDS=1,
            )
            base = self.at(15, 10)
            controller.update_appliance(ApplianceUpdate(True, base))
            controller.update_sensing(SensingUpdate(
                "toilet", base + 1, activity="lying",
                motion_state="still", fall_detected=True,
            ))
            start = controller.drain_scenario_actions()
            self.assertEqual({(item.action, item.target) for item in start}, {
                ("turn_off", "stove"), ("blink", "light")
            })

            controller.update_sensing(SensingUpdate(
                "toilet", base + 3, activity="lying", motion_state="still"
            ))
            first = controller.drain_scenario_actions()
            self.assertEqual([item.event for item in first], ["fall_user_alert_requested"])

            controller.update_sensing(SensingUpdate(
                "toilet", base + 5, activity="lying", motion_state="still"
            ))
            second = controller.drain_scenario_actions()
            self.assertEqual([item.event for item in second], ["fall_caregiver_alert_requested"])

            controller.update_sensing(SensingUpdate(
                "toilet", base + 7, activity="lying", motion_state="still"
            ))
            self.assertEqual(controller.drain_scenario_actions(), [])
            controller.update_fall_backend_signal(FallBackendSignal(base + 7, True))
            third = controller.drain_scenario_actions()
            self.assertEqual([item.event for item in third], ["fall_emergency_report_requested"])
            controller.update_fall_backend_signal(FallBackendSignal(base + 8, True))
            self.assertEqual(controller.drain_scenario_actions(), [])

    def test_stale_or_off_induction_does_not_emit_off_request(self):
        for power_on, age in ((False, 1), (True, 20)):
            with self.subTest(power_on=power_on, age=age), tempfile.TemporaryDirectory() as tmp:
                controller = self.make_controller(tmp)
                base = self.at(15, 10)
                controller.update_appliance(ApplianceUpdate(power_on, base))
                controller.update_sensing(SensingUpdate(
                    "toilet", base + age, activity="lying",
                    motion_state="still", fall_detected=True,
                ))
                targets = {item.target for item in controller.drain_scenario_actions()}
                self.assertNotIn("stove", targets)
                self.assertIn("light", targets)

    def test_fresh_induction_update_during_fall_requests_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = self.make_controller(tmp)
            base = self.at(15, 10)
            controller.update_sensing(SensingUpdate(
                "toilet", base, activity="lying",
                motion_state="still", fall_detected=True,
            ))
            controller.drain_scenario_actions()
            controller.update_appliance(ApplianceUpdate(True, base))
            actions = controller.drain_scenario_actions()
            self.assertEqual([(item.action, item.target) for item in actions], [
                ("turn_off", "stove")
            ])

    def test_water_command_requests_backend_weather_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = self.make_controller(tmp)
            self.complete_wake(controller, self.at(15, 7))
            command = controller.drain_device_commands()[0]
            payload = command.to_dict()
            self.assertEqual(payload["event"], "water_dispensed")
            self.assertIs(payload["request_weather_info"], True)

    def test_wake_window_is_learned_from_recent_days_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "WAKE_PATTERN_MIN_SAMPLES": 3,
                "WAKE_PATTERN_HISTORY_SIZE": 3,
                "WAKE_WINDOW_MARGIN_SECONDS": 900,
            }
            controller = self.make_controller(tmp, **config)
            for day, minute in ((15, 0), (16, 10), (17, 20)):
                self.complete_wake(controller, self.at(day, 7, minute))
                controller.drain_device_commands()
            self.assertTrue(controller.morning_water.uses_learned_wake_window)
            start, end = controller.morning_water.current_wake_window()
            self.assertEqual((start.hour, start.minute), (6, 45))
            self.assertEqual((end.hour, end.minute), (7, 35))

            restored = self.make_controller(tmp, **config)
            self.assertTrue(restored.morning_water.uses_learned_wake_window)
            self.assertEqual(restored.morning_water.current_wake_window(), (start, end))

    def test_out_of_window_wake_is_recorded_and_updates_recent_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = self.make_controller(
                tmp,
                WAKE_PATTERN_MIN_SAMPLES=2,
                WAKE_PATTERN_HISTORY_SIZE=2,
                WAKE_WINDOW_MARGIN_SECONDS=300,
            )
            self.complete_wake(controller, self.at(15, 7))
            controller.drain_device_commands()
            self.complete_wake(controller, self.at(16, 7, 5))
            controller.drain_device_commands()
            self.complete_wake(controller, self.at(17, 8, 30))
            self.assertEqual(controller.drain_device_commands(), [])
            start, end = controller.morning_water.current_wake_window()
            self.assertGreaterEqual(start, time(6, 59))
            self.assertGreater(end, time(8, 30))

    def test_scenario_threshold_configuration_validation(self):
        with self.assertRaises(ValueError):
            ScenarioConfig(WAKE_PATTERN_MIN_SAMPLES=4, WAKE_PATTERN_HISTORY_SIZE=3)
        with self.assertRaises(ValueError):
            ScenarioConfig(BEDTIME_LYING_SECONDS=0)


if __name__ == "__main__":
    unittest.main()
