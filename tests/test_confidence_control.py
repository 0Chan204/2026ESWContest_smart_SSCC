import json
import tempfile
import unittest
from pathlib import Path

from src.control import (
    ApplianceUpdate,
    CentralController,
    ConfidenceConfig,
    LightContext,
    SensingUpdate,
)


class ConfidenceControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.controller = CentralController(confidence_data_dir=self.tmp.name)

    def kitchen_features(self, **overrides):
        values = {
            "location_confidence": 0.95,
            "activity_confidence": 1.0,
            "leave_duration": 300,
            "current_stove_power": 1800,
            "outside_home": False,
            "sensor_consistency": 1.0,
            "previous_homevis_action": False,
            "feedback_score": 0.5,
        }
        values.update(overrides)
        return self.controller.feature_extractor.kitchen_leave(**values)

    def score_kitchen(self, **overrides):
        return self.controller.confidence_engine.calculate(
            "kitchen_leave_reduce_power", self.kitchen_features(**overrides)
        )["confidence"]

    def create_reduce_action(self):
        c = self.controller
        for timestamp in (0, 5):
            c.update_appliance(ApplianceUpdate(True, timestamp, power_watts=1800))
            c.update_sensing(SensingUpdate(
                "kitchen", timestamp, confidence=0.95, activity_confidence=1.0
            ))
        for timestamp in range(10, 311, 5):
            c.update_appliance(ApplianceUpdate(True, timestamp, power_watts=1800))
            c.update_sensing(SensingUpdate(
                "living_room", timestamp, confidence=0.95, activity_confidence=1.0
            ))
        actions = c.drain_automation_actions()
        self.assertEqual([action.action for action in actions], ["reduce_power"])
        return actions[0]

    def test_kitchen_confidence_combines_continuous_features(self):
        config = ConfidenceConfig()
        low_location = self.score_kitchen(location_confidence=0.1)
        short_absence = self.score_kitchen(leave_duration=5)
        long_high_power = self.score_kitchen()
        unstable = self.score_kitchen(sensor_consistency=0.1)
        outside = self.score_kitchen(outside_home=True)

        self.assertLess(low_location, config.SCENARIO_THRESHOLDS["kitchen_leave_reduce_power"])
        self.assertLess(short_absence, long_high_power)
        self.assertGreaterEqual(long_high_power,
                                config.SCENARIO_THRESHOLDS["kitchen_leave_reduce_power"])
        self.assertLess(unstable, long_high_power)
        self.assertGreater(outside, long_high_power)

    def test_reduce_action_has_explainable_history(self):
        action = self.create_reduce_action()
        self.assertEqual(action.device, "stove")
        self.assertIn("duration", action.reason)
        record = self.controller.decision_history.get(action.action_id)
        self.assertEqual(record["scenario"], "kitchen_leave_reduce_power")
        self.assertEqual(record["action"]["action"], "reduce_power")
        self.assertAlmostEqual(sum(record["weights"].values()), 1.0)
        self.assertIn("stove_power", record["contributions"])

    def test_kitchen_feedback_lowers_repeated_condition(self):
        action = self.create_reduce_action()
        record = self.controller.decision_history.get(action.action_id)
        feedback = self.controller.apply_feedback(action.action_id, "unnecessary")
        repeated_features = dict(record["features"])
        repeated_features["feedback"] = self.controller.feedback_manager.feedback_score(
            "default", "kitchen_leave_reduce_power"
        )
        repeated = self.controller.confidence_engine.calculate(
            "kitchen_leave_reduce_power", repeated_features
        )
        self.assertLess(feedback["weights_after"]["duration"],
                        feedback["weights_before"]["duration"])
        self.assertLess(feedback["weights_after"]["stove_power"],
                        feedback["weights_before"]["stove_power"])
        self.assertLess(repeated["confidence"], record["confidence"])

    def test_negative_feedback_reduces_high_contributors_and_next_score(self):
        first = self.controller.evaluate_light(LightContext(
            room="bedroom", light_on=True, user_present=False, timestamp=1,
            absence_duration=30, location_confidence=1,
            activity_confidence=1, sensor_consistency=1,
        ))
        self.assertEqual(first.outcome, "execute")
        feedback = self.controller.apply_feedback(first.action_id, "unnecessary")
        second = self.controller.evaluate_light(LightContext(
            room="bedroom", light_on=True, user_present=False, timestamp=2,
            absence_duration=30, location_confidence=1,
            activity_confidence=1, sensor_consistency=1,
        ))
        self.assertLess(feedback["weights_after"]["leave_duration"],
                        feedback["weights_before"]["leave_duration"])
        self.assertLess(second.confidence, first.confidence)
        stored = json.loads((Path(self.tmp.name) / "user_weights.json").read_text("utf-8"))
        self.assertIn("light_auto_off", stored["default"])

    def test_positive_feedback_increases_contributors_within_bounds(self):
        first = self.controller.evaluate_light(LightContext(
            room="bedroom", light_on=True, user_present=False, timestamp=1,
            absence_duration=30, location_confidence=1,
            activity_confidence=1, sensor_consistency=1,
        ))
        result = self.controller.apply_feedback(first.action_id, "positive")
        self.assertGreater(result["weights_after"]["leave_duration"],
                           result["weights_before"]["leave_duration"])
        contributions = {name: (1.0 if name == "leave_duration" else 0.0)
                         for name in result["weights_after"]}
        for _ in range(200):
            _, weights = self.controller.weight_manager.update_from_feedback(
                "default", "light_auto_off", contributions, "positive"
            )
        self.assertLessEqual(max(weights.values()), ConfidenceConfig().MAX_WEIGHT)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_light_short_absence_waits_and_sustained_absence_turns_off(self):
        short = self.controller.evaluate_light(LightContext(
            room="bedroom", light_on=True, user_present=False, timestamp=1,
            absence_duration=2, sensor_consistency=1,
        ))
        sustained = self.controller.evaluate_light(LightContext(
            room="bedroom", light_on=True, user_present=False, timestamp=31,
            absence_duration=30, sensor_consistency=1,
        ))
        self.assertIsNone(short.action)
        self.assertEqual(sustained.action.action, "turn_off")

    def test_restore_requires_stable_return_and_homevis_control(self):
        self.create_reduce_action()
        self.controller.update_appliance(ApplianceUpdate(True, 315, power_watts=1800))
        early = self.controller.update_sensing(SensingUpdate("kitchen", 315, confidence=0.95))
        early_action = None if early.confidence_decision is None else early.confidence_decision["action"]
        self.assertFalse(early_action and early_action.get("action") == "restore_power")
        self.controller.update_appliance(ApplianceUpdate(True, 320, power_watts=1800))
        stable = self.controller.update_sensing(SensingUpdate("kitchen", 320, confidence=0.95))
        self.assertEqual(stable.confidence_decision["action"]["action"], "restore_power")

    def test_low_confidence_return_does_not_restore(self):
        self.create_reduce_action()
        self.controller.update_appliance(ApplianceUpdate(True, 315, power_watts=1800))
        self.controller.update_sensing(SensingUpdate("kitchen", 315, confidence=0.6))
        self.controller.update_appliance(ApplianceUpdate(True, 320, power_watts=1800))
        decision = self.controller.update_sensing(SensingUpdate("kitchen", 320, confidence=0.6))
        self.assertEqual(decision.confidence_decision["scenario"], "kitchen_return_restore")
        self.assertLess(decision.confidence_decision["confidence"],
                        decision.confidence_decision["threshold"])
        self.assertIsNone(decision.confidence_decision["action"])

    def test_stove_off_blocks_restore(self):
        self.create_reduce_action()
        self.controller.update_appliance(ApplianceUpdate(False, 315, power_watts=0))
        self.controller.update_sensing(SensingUpdate("kitchen", 315, confidence=0.95))
        self.controller.update_appliance(ApplianceUpdate(False, 320, power_watts=0))
        decision = self.controller.update_sensing(SensingUpdate("kitchen", 320, confidence=0.95))
        self.assertFalse(decision.confidence_decision and decision.confidence_decision["action"])
        self.assertEqual(self.controller.drain_automation_actions(), [])

    def test_user_override_blocks_restore(self):
        self.create_reduce_action()
        self.controller.update_appliance(ApplianceUpdate(
            True, 315, power_watts=1800, control_state="USER_OVERRIDE"
        ))
        self.controller.update_sensing(SensingUpdate("kitchen", 315, confidence=0.95))
        self.controller.update_appliance(ApplianceUpdate(True, 320, power_watts=1800))
        decision = self.controller.update_sensing(SensingUpdate("kitchen", 320, confidence=0.95))
        self.assertEqual(decision.confidence_decision["outcome"], "guarded")
        self.assertEqual(decision.confidence_decision["guard_reason"], "user_override")
        self.assertEqual(self.controller.drain_automation_actions(), [])

    def test_routine_records_sensing_and_actions(self):
        self.controller.update_sensing(SensingUpdate("bedroom", 1, activity="lying", confidence=0.9))
        self.controller.evaluate_light(LightContext(
            room="bedroom", light_on=False, user_present=True, timestamp=6,
            presence_duration=5,
        ))
        records = self.controller.routine_manager.storage.list_records()
        self.assertEqual(records[0]["location"], "bedroom")
        self.assertEqual(records[0]["activity"], "lying")
        self.assertEqual(records[-1]["action"], "turn_on")


if __name__ == "__main__":
    unittest.main()
