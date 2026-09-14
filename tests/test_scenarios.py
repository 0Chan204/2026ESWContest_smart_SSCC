import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.alert_service import AlertService
from src.control import ApplianceUpdate, CentralController, DeviceCommand, ScenarioConfig, SensingUpdate
from src.llm.message_generator import LLMMessageGenerator
from src.llm.prompts import build_device_command_user_prompt, get_system_prompt
from src.voice.tts import DryRunTTS


class ScenarioTest(unittest.TestCase):
    def setUp(self):
        self.c = CentralController(water_dispenser_available=True)
        self.base = datetime(2026, 9, 15, 7, tzinfo=timezone(timedelta(hours=9))).timestamp()

    def sample(self, seconds, location="bathroom", activity="unknown", **kwargs):
        self.c.update_sensing(SensingUpdate(location, self.base + seconds, activity=activity, **kwargs))
        return self.c.bathroom_decision

    def wake(self, start=0):
        self.sample(start, "bedroom", "lying")
        self.sample(start + 1, "bedroom", "standing")
        self.sample(start + 6, "bedroom", "standing")

    def dispense(self):
        self.wake()
        self.sample(7, "living_room", "walking")
        self.sample(8, "kitchen", "standing")
        self.sample(13, "kitchen")

    def warning(self):
        self.sample(0, fall_detected=True, motion_state="still")
        return self.sample(10, motion_state="still")

    def test_morning_dispense(self):
        self.dispense()
        commands = self.c.drain_device_commands()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].command_type, "DISPENSE_WATER")
        self.assertEqual(commands[0].amount_ml, 250)
        self.assertEqual(commands[0].timestamp, self.base + 13)
        self.assertEqual(self.c.drain_device_commands(), [])

    def test_afternoon_no_dispense(self):
        self.base += 7 * 3600
        self.dispense()
        self.assertEqual(self.c.device_commands, [])

    def test_no_wake_event(self):
        self.sample(0, "bedroom")
        self.sample(1, "kitchen")
        self.sample(6, "kitchen")
        self.assertEqual(self.c.device_commands, [])

    def test_no_duplicate(self):
        self.dispense()
        self.wake(20)
        self.sample(27, "kitchen")
        self.sample(32, "kitchen")
        self.assertEqual(len(self.c.device_commands), 1)

    def test_wake_timeout(self):
        self.wake()
        self.sample(1806, "kitchen")
        self.sample(1811, "kitchen")
        self.assertEqual(self.c.device_commands, [])

    def test_pass_through(self):
        self.wake()
        self.sample(7, "kitchen")
        self.sample(11, "living_room")
        self.c.tick(self.base + 13)
        self.assertEqual(self.c.device_commands, [])

    def test_unavailable_device(self):
        self.c.water_dispenser_available = False
        self.dispense()
        self.assertEqual(self.c.device_commands, [])

    def test_next_day(self):
        self.dispense()
        self.base += 86400
        self.dispense()
        self.assertEqual(len(self.c.device_commands), 2)

    def test_wake_glitch(self):
        self.sample(0, "bedroom", "lying")
        self.sample(1, "bedroom", "standing")
        self.sample(2, "bedroom", "lying")
        self.sample(6, "kitchen")
        self.sample(11, "kitchen")
        self.assertEqual(self.c.device_commands, [])

    def test_kitchen_uncertain_or_gap_does_not_confirm(self):
        for kwargs in ({"detected": False}, {"confidence": 0.1}):
            with self.subTest(kwargs=kwargs):
                self.setUp()
                self.wake()
                self.sample(7, "kitchen")
                self.sample(12, "kitchen", **kwargs)
                self.sample(13, "kitchen")
                self.assertEqual(self.c.device_commands, [])
        self.sample(40, "kitchen")
        self.assertEqual(self.c.device_commands, [])

    def test_normal_bathroom(self):
        result = self.sample(0, activity="sitting", motion_state="still", fall_detected=False)
        self.assertEqual(result.state, "NORMAL_BATHROOM_USE")
        self.assertEqual(result.risk, "NORMAL")

    def test_fall_suspected(self):
        self.assertEqual(self.sample(0, fall_detected=True).state, "FALL_SUSPECTED")

    def test_fall_warning(self):
        result = self.warning()
        self.assertEqual(result.state, "FALL_WARNING")
        self.assertEqual(result.risk, "HIGH")

    def test_fall_emergency(self):
        self.warning()
        self.sample(20, motion_state="still")
        self.assertEqual(self.sample(30, motion_state="still").state, "FALL_EMERGENCY")

    def test_recovery(self):
        self.warning()
        self.assertEqual(self.sample(11, motion_state="moving").state, "FALL_WARNING")
        self.assertEqual(self.sample(16, motion_state="moving").state, "RECOVERED")

    def test_non_detection_preserves_warning(self):
        self.warning()
        result = self.sample(11, detected=False)
        self.assertEqual(result.state, "FALL_WARNING")
        self.assertEqual(result.risk, "HIGH")
        self.assertTrue(result.sensor_uncertain)

    def test_still_alone_never_emergency(self):
        for t in range(0, 61, 5):
            result = self.sample(t, motion_state="still", fall_detected=False)
        self.assertEqual(result.risk, "NORMAL")

    def test_posture_transition(self):
        self.sample(0, activity="standing")
        result = self.sample(1, activity="lying", motion_state="still")
        self.assertEqual(result.state, "FALL_SUSPECTED")
        self.assertEqual(self.sample(6, motion_state="still").state, "FALL_CONFIRMED")

    def test_recovery_glitch_and_sensor_gap(self):
        self.warning()
        self.sample(11, motion_state="moving")
        self.sample(12, motion_state="still")
        self.sample(16, motion_state="moving")
        self.assertEqual(self.sample(20, motion_state="moving").state, "FALL_WARNING")
        self.c.tick(self.base + 60)
        self.assertEqual(self.c.bathroom_decision.risk, "HIGH")
        self.assertTrue(self.c.bathroom_decision.sensor_uncertain)
        self.assertEqual(self.sample(61, motion_state="moving").state, "FALL_WARNING")

    def test_long_unresponsive(self):
        self.sample(0, fall_detected=True, motion_state="still")
        for t in range(5, 61, 5):
            result = self.sample(t, motion_state="still")
        self.assertTrue(result.long_unresponsive)
        self.assertEqual(result.state, "FALL_EMERGENCY")

    def test_config_and_legacy_input(self):
        self.assertIsNone(SensingUpdate("bathroom", 0).fall_detected)
        with self.assertRaises(ValueError):
            ScenarioConfig(FALL_WARNING_SECONDS=40)
        with self.assertRaises(ValueError):
            SensingUpdate("bathroom", 0, fall_detected=1)

    def test_custom_water_amount_and_confirmation(self):
        self.c = CentralController(scenario_config=ScenarioConfig(
            MORNING_WATER_AMOUNT_ML=150, KITCHEN_CONFIRM_SECONDS=8), water_dispenser_available=True)
        self.dispense()
        self.assertEqual(self.c.device_commands, [])
        self.sample(16, "kitchen")
        self.assertEqual(self.c.device_commands[0].amount_ml, 150)

    def test_bathroom_alert_fallback(self):
        decision = self.warning().to_risk_decision()
        with tempfile.TemporaryDirectory() as tmp:
            service = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp)
            output = service.handle(decision)
            self.assertTrue(output.fallback_used)
            self.assertTrue(output.voice)
            self.assertIsNotNone(output.tts_file)
            self.assertIn("욕실", output.message)
        self.assertIn("위험을 새로 판단하거나 변경하지", get_system_prompt("v1", "bathroom_fall"))

    def test_bathroom_llm_and_tts_failure(self):
        class FailingLLM:
            name = "failing"

            def generate(inner, system_prompt, user_prompt):
                self.assertIn("욕실", system_prompt)
                self.assertIn("bathroom_fall", user_prompt)
                self.assertIn("FALL_EMERGENCY", user_prompt)
                raise RuntimeError("LLM unavailable")

        class FailingTTS:
            def synthesize(inner, message, path):
                raise RuntimeError("TTS unavailable")

        self.warning()
        self.sample(20, motion_state="still")
        decision = self.sample(30, motion_state="still").to_risk_decision()
        output = AlertService(LLMMessageGenerator(FailingLLM()), FailingTTS()).handle(decision)
        self.assertTrue(output.fallback_used)
        self.assertIn("LLM unavailable", output.llm_error)
        self.assertIn("TTS unavailable", output.tts_error)
        self.assertEqual(output.message, "욕실에서 낙상 후 움직임이 확인되지 않고 있습니다.")

    def test_kitchen_and_bathroom_risks_remain_independent(self):
        self.warning()
        kitchen = self.c.update_appliance(ApplianceUpdate(True, self.base + 11, fire=True))
        self.assertEqual(kitchen.state, "DANGER")
        self.assertEqual(self.c.bathroom_decision.state, "FALL_WARNING")
        kitchen = self.c.update_appliance(ApplianceUpdate(False, self.base + 12))
        self.assertEqual(kitchen.state, "RECOVERED")
        self.assertEqual(self.c.bathroom_decision.risk, "HIGH")

    def test_generated_water_command_can_create_llm_message(self):
        class RecordingLLM:
            name = "qwen3-8b"

            def generate(inner, system_prompt, user_prompt):
                self.assertIn("완료되었다고 단정하지 마세요", system_prompt)
                self.assertIn('"scenario": "morning_water"', user_prompt)
                self.assertIn('"command_type": "DISPENSE_WATER"', user_prompt)
                self.assertIn('"amount_ml": 250', user_prompt)
                return "아침에 드실 물 250밀리리터를 준비하고 있습니다."

        self.dispense()
        command = self.c.drain_device_commands()[0]
        result = LLMMessageGenerator(RecordingLLM()).generate_device_command(command)
        self.assertEqual(result.message, "아침에 드실 물 250밀리리터를 준비하고 있습니다.")
        self.assertEqual(result.llm_name, "qwen3-8b")
        self.assertFalse(result.fallback_used)

    def test_water_command_without_llm_uses_fallback(self):
        command = DeviceCommand(timestamp=self.base, amount_ml=250)
        result = LLMMessageGenerator().generate_device_command(command)
        self.assertEqual(result.message, "물 250밀리리터를 준비하도록 요청했습니다.")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.llm_name, "none")

    def test_water_command_llm_error_uses_fallback(self):
        class FailingLLM:
            name = "qwen3-8b"

            def generate(self, system_prompt, user_prompt):
                raise RuntimeError("Qwen unavailable")

        command = DeviceCommand(timestamp=self.base, amount_ml=250)
        result = LLMMessageGenerator(FailingLLM()).generate_device_command(command)
        self.assertEqual(result.message, "물 250밀리리터를 준비하도록 요청했습니다.")
        self.assertTrue(result.fallback_used)
        self.assertIn("Qwen unavailable", result.error)

    def test_water_command_fallback_uses_configured_amount(self):
        command = DeviceCommand(timestamp=self.base, amount_ml=150)
        result = LLMMessageGenerator().generate_device_command(command)
        self.assertEqual(result.message, "물 150밀리리터를 준비하도록 요청했습니다.")

    def test_water_command_empty_or_completion_claim_uses_fallback(self):
        class FakeLLM:
            name = "qwen3-8b"

            def __init__(self, message):
                self.message = message

            def generate(self, system_prompt, user_prompt):
                return self.message

        command = DeviceCommand(timestamp=self.base, amount_ml=250)
        for message in ("   ", "물이 준비되었습니다.", "출수가 완료되었습니다."):
            with self.subTest(message=message):
                result = LLMMessageGenerator(FakeLLM(message)).generate_device_command(command)
                self.assertTrue(result.fallback_used)
                self.assertEqual(result.message, "물 250밀리리터를 준비하도록 요청했습니다.")

    def test_morning_water_prompt_and_existing_prompts_are_distinct(self):
        morning = get_system_prompt("v1", "morning_water")
        bathroom = get_system_prompt("v1", "bathroom_fall")
        kitchen = get_system_prompt("v1")
        self.assertIn("DeviceCommand를 재판단하거나 변경하지 마세요", morning)
        self.assertIn("완료되었다고 단정하지 마세요", morning)
        self.assertIn("욕실 안전 안내", bathroom)
        self.assertIn("센서 불확실 상태를 회복으로 표현하지 마세요", bathroom)
        self.assertIn("조리 안전 안내", kitchen)
        self.assertIn("위험도를 새로 판단하거나 변경하지 마세요", kitchen)

    def test_water_command_prompt_contains_required_fields(self):
        command = DeviceCommand(timestamp=self.base, amount_ml=150, reason="test reason")
        prompt = build_device_command_user_prompt(command)
        for value in ("morning_water", "DISPENSE_WATER", "water_dispenser",
                      "150", "room_temp", "test reason"):
            self.assertIn(value, prompt)
