import json
import tempfile
import unittest

from src.control import (
    ApplianceUpdate,
    CentralController,
    ConfidenceConfig,
    LightContext,
    NaturalLanguageFeedbackInterpreter,
    SensingUpdate,
)
from src.llm.message_generator import LLMMessageGenerator


class FakeLLM:
    name = "shared-test-llm"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if not self.responses:
            raise RuntimeError("no fake response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(feedback, confidence=0.95, reason="classified_feedback"):
    return json.dumps({
        "feedback": feedback,
        "reason": reason,
        "confidence": confidence,
    })


class NaturalLanguageFeedbackTest(unittest.TestCase):
    def make_controller(self, llm, *, config=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return CentralController(
            confidence_data_dir=directory.name,
            confidence_config=config,
            feedback_llm=llm,
        )

    @staticmethod
    def light_off(controller, timestamp=1):
        decision = controller.evaluate_light(LightContext(
            room="living_room",
            light_on=True,
            user_present=False,
            timestamp=timestamp,
            absence_duration=30,
            location_confidence=1,
            activity_confidence=1,
            sensor_consistency=1,
        ))
        if decision.action is None:
            raise AssertionError("test setup did not emit light_auto_off")
        return decision

    @staticmethod
    def kitchen_reduce(controller):
        for timestamp in (0, 5):
            controller.update_appliance(ApplianceUpdate(True, timestamp, power_watts=1800))
            controller.update_sensing(SensingUpdate(
                "kitchen", timestamp, confidence=0.95, activity_confidence=1
            ))
        for timestamp in range(10, 311, 5):
            controller.update_appliance(ApplianceUpdate(True, timestamp, power_watts=1800))
            controller.update_sensing(SensingUpdate(
                "living_room", timestamp, confidence=0.95, activity_confidence=1
            ))
        actions = [action for action in controller.drain_automation_actions()
                   if action.scenario == "kitchen_leave_reduce_power"]
        if len(actions) != 1:
            raise AssertionError("test setup did not emit one reduce_power action")
        return actions[0]

    def test_kitchen_unnecessary_feedback_uses_existing_pipeline(self):
        llm = FakeLLM(response(
            "unnecessary", 0.95, "user_considered_power_reduction_unnecessary"
        ))
        controller = self.make_controller(llm)
        action = self.kitchen_reduce(controller)
        before = controller.weight_manager.get_weights("default", action.scenario)
        result = controller.apply_natural_language_feedback(
            action.action_id, "굳이 화력을 줄일 필요 없었어"
        )
        after = controller.weight_manager.get_weights("default", action.scenario)
        self.assertEqual(result["feedback"], "unnecessary")
        self.assertTrue(result["weight_updated"])
        self.assertNotEqual(before, after)

    def test_feedback_and_message_generation_share_one_llm_instance(self):
        llm = FakeLLM(response("positive"))
        controller = self.make_controller(llm)
        generator = LLMMessageGenerator(llm)
        self.assertIs(controller.feedback_interpreter.llm, generator.llm)

    def test_light_unnecessary_feedback_contains_action_context(self):
        llm = FakeLLM(response("unnecessary", 0.96, "user_was_still_using_room"))
        controller = self.make_controller(llm)
        decision = self.light_off(controller)
        result = controller.apply_natural_language_feedback(
            decision.action_id, "나 아직 거실에 있는데 왜 불 껐어?"
        )
        self.assertEqual(result["parsed_feedback"]["feedback"], "unnecessary")
        self.assertTrue(result["weight_updated"])
        prompt = llm.calls[0][1]
        self.assertIn(decision.action_id, prompt)
        self.assertIn("light_auto_off", prompt)
        self.assertIn("나 아직 거실에 있는데 왜 불 껐어?", prompt)

    def test_common_labels_are_not_scenario_specific(self):
        cases = (
            ("이번엔 잘했어", "positive"),
            ("너무 예민하게 반응하는 것 같아", "too_sensitive"),
            ("좀 더 빨리 했어야지", "too_late"),
            ("그냥 내가 할게", "user_override"),
        )
        context = {
            "action_id": "any", "scenario": "future_scenario",
            "device": "any_device", "action": "any_action",
        }
        for user_text, expected in cases:
            with self.subTest(user_text=user_text):
                interpreter = NaturalLanguageFeedbackInterpreter(FakeLLM(response(expected)))
                parsed = interpreter.interpret(context, user_text)
                self.assertEqual(parsed.feedback, expected)

    def test_ambiguous_feedback_is_saved_without_weight_update(self):
        controller = self.make_controller(FakeLLM(response("unknown", 0.30, "ambiguous_feedback")))
        decision = self.light_off(controller)
        before = controller.weight_manager.get_weights("default", "light_auto_off")
        result = controller.apply_natural_language_feedback(decision.action_id, "응")
        self.assertEqual(result["parsed_feedback"]["feedback"], "unknown")
        self.assertFalse(result["weight_updated"])
        self.assertEqual(before, controller.weight_manager.get_weights("default", "light_auto_off"))
        self.assertEqual(controller.feedback_storage.list_records()[-1]["raw_feedback"], "응")

    def test_missing_or_unknown_action_id_never_calls_llm(self):
        for action_id, reason in ((None, "action_id_missing"), ("missing", "action_not_found")):
            with self.subTest(action_id=action_id):
                llm = FakeLLM(response("unnecessary"))
                controller = self.make_controller(llm)
                result = controller.apply_natural_language_feedback(action_id, "왜 그랬어?")
                self.assertEqual(result["parsed_feedback"]["reason"], reason)
                self.assertFalse(result["weight_updated"])
                self.assertEqual(llm.calls, [])

    def test_invalid_json_retries_once_then_returns_unknown(self):
        llm = FakeLLM("not json", "```json\n{broken}\n```")
        controller = self.make_controller(llm)
        decision = self.light_off(controller)
        result = controller.apply_natural_language_feedback(decision.action_id, "불필요했어")
        self.assertEqual(result["parsed_feedback"]["feedback"], "unknown")
        self.assertEqual(result["parsed_feedback"]["reason"], "parse_error")
        self.assertFalse(result["weight_updated"])
        self.assertEqual(len(llm.calls), 2)

    def test_generation_failure_does_not_crash(self):
        llm = FakeLLM(RuntimeError("offline"), RuntimeError("still offline"))
        controller = self.make_controller(llm)
        decision = self.light_off(controller)
        result = controller.apply_natural_language_feedback(decision.action_id, "잘했어")
        self.assertEqual(result["parsed_feedback"]["feedback"], "unknown")
        self.assertEqual(result["parsed_feedback"]["reason"], "generation_error")
        self.assertFalse(result["weight_updated"])

    def test_invalid_schema_values_become_unknown(self):
        invalid_outputs = (
            '{"feedback":"new_label","reason":"x","confidence":0.9}',
            '{"feedback":"positive","confidence":0.9}',
            '{"feedback":"positive","reason":"x","confidence":1.5}',
            "",
        )
        for raw in invalid_outputs:
            with self.subTest(raw=raw):
                parsed = NaturalLanguageFeedbackInterpreter(
                    FakeLLM(raw), max_retries=0
                ).interpret({"scenario": "anything"}, "입력")
                self.assertEqual(parsed.feedback, "unknown")
                self.assertEqual(parsed.reason, "parse_error")

    def test_markdown_and_numeric_string_are_parsed(self):
        raw = (
            "분류 결과입니다.\n```json\n"
            '{"feedback":"positive","reason":"user_approved","confidence":"0.93"}'
            "\n```"
        )
        interpreter = NaturalLanguageFeedbackInterpreter(FakeLLM(raw))
        parsed = interpreter.interpret({"scenario": "anything"}, "잘했어")
        self.assertEqual(parsed.feedback, "positive")
        self.assertEqual(parsed.confidence, 0.93)

    def test_review_confidence_is_stored_but_not_applied(self):
        controller = self.make_controller(FakeLLM(response("unnecessary", 0.65)))
        decision = self.light_off(controller)
        before = controller.weight_manager.get_weights("default", "light_auto_off")
        result = controller.apply_natural_language_feedback(decision.action_id, "아닌 것 같아")
        self.assertEqual(result["status"], "review_required")
        self.assertFalse(result["weight_updated"])
        self.assertEqual(before, controller.weight_manager.get_weights("default", "light_auto_off"))
        self.assertEqual(controller.feedback_manager.feedback_score(
            "default", "light_auto_off"
        ), 0.5)

    def test_apply_confidence_invokes_feedback_manager(self):
        controller = self.make_controller(FakeLLM(response("unnecessary", 0.80)))
        decision = self.light_off(controller)
        result = controller.apply_natural_language_feedback(decision.action_id, "불필요했어")
        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["weight_updated"])
        self.assertIn("weights_before", result)
        self.assertIn("weights_after", result)

    def test_negative_light_feedback_only_changes_light_scenario(self):
        controller = self.make_controller(FakeLLM(response("unnecessary", 0.95)))
        decision = self.light_off(controller)
        kitchen_before = controller.weight_manager.get_weights(
            "default", "kitchen_leave_reduce_power"
        )
        light_before = controller.weight_manager.get_weights("default", "light_auto_off")
        controller.apply_natural_language_feedback(decision.action_id, "왜 불 껐어?")
        self.assertNotEqual(light_before,
                            controller.weight_manager.get_weights("default", "light_auto_off"))
        self.assertEqual(kitchen_before, controller.weight_manager.get_weights(
            "default", "kitchen_leave_reduce_power"
        ))

    def test_natural_and_structured_feedback_use_identical_weight_algorithm(self):
        natural = self.make_controller(FakeLLM(response("unnecessary", 0.95)))
        structured = self.make_controller(FakeLLM())
        natural_action = self.light_off(natural)
        structured_action = self.light_off(structured)
        natural_result = natural.apply_natural_language_feedback(
            natural_action.action_id, "불필요했어"
        )
        structured_result = structured.apply_feedback(
            structured_action.action_id, "unnecessary"
        )
        self.assertEqual(natural_result["weights_after"], structured_result["weights_after"])

    def test_action_and_feedback_confidence_remain_separate(self):
        controller = self.make_controller(FakeLLM(response("positive", 0.91)))
        decision = self.light_off(controller)
        result = controller.apply_natural_language_feedback(decision.action_id, "잘했어")
        self.assertEqual(result["action_confidence"], decision.confidence)
        self.assertEqual(result["feedback_confidence"], 0.91)
        self.assertNotEqual(result["action_confidence"], result["feedback_confidence"])

    def test_feedback_changes_next_confidence_without_new_formula(self):
        controller = self.make_controller(FakeLLM(response("unnecessary", 0.95)))
        before = self.light_off(controller)
        controller.apply_natural_language_feedback(before.action_id, "왜 불 껐어?")
        after = controller.evaluate_light(LightContext(
            room="living_room", light_on=True, user_present=False, timestamp=2,
            absence_duration=30, location_confidence=1,
            activity_confidence=1, sensor_consistency=1,
        ))
        self.assertNotEqual(before.confidence, after.confidence)

    def test_new_scenario_uses_same_interpreter_and_pipeline(self):
        base = ConfidenceConfig()
        weights = {name: dict(value) for name, value in base.SCENARIO_WEIGHTS.items()}
        thresholds = dict(base.SCENARIO_THRESHOLDS)
        weights["future_air_control"] = {"signal": 0.50, "context": 0.30, "feedback": 0.20}
        thresholds["future_air_control"] = 0.65
        config = ConfidenceConfig(SCENARIO_WEIGHTS=weights, SCENARIO_THRESHOLDS=thresholds)
        controller = self.make_controller(
            FakeLLM(response("unnecessary", 0.95)), config=config
        )
        decision = controller.confidence_service.score(
            scenario="future_air_control",
            features={"signal": 1.0, "context": 0.5, "feedback": 0.5},
            timestamp=1,
            device="air_conditioner",
            action_name="turn_off",
        )
        self.assertIsNotNone(decision.action)
        result = controller.apply_natural_language_feedback(
            decision.action_id, "아직 사용 중인데 왜 껐어?"
        )
        self.assertTrue(result["weight_updated"])
        self.assertEqual(result["scenario"], "future_air_control")

    def test_updated_user_weights_are_reloaded_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            first = CentralController(
                confidence_data_dir=directory,
                feedback_llm=FakeLLM(response("unnecessary", 0.95)),
            )
            decision = self.light_off(first)
            result = first.apply_natural_language_feedback(
                decision.action_id, "불필요했어"
            )
            restarted = CentralController(confidence_data_dir=directory)
            self.assertEqual(
                restarted.weight_manager.get_weights("default", "light_auto_off"),
                result["weights_after"],
            )


if __name__ == "__main__":
    unittest.main()
