from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.alert_service import AlertService
from src.llm.adapters.base import BaseLLMAdapter
from src.llm.message_generator import LLMMessageGenerator
from src.models import RiskDecision, RiskLevel
from src.output.output_writer import OutputWriter
from src.voice.tts import DryRunTTS


class FakeLLM(BaseLLMAdapter):
    name = "fake"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return "조리 상태를 확인해 주세요. 필요한 경우 즉시 주방으로 이동해 주세요."


class EmptyLLM(BaseLLMAdapter):
    name = "empty"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return "   "


class AlertServiceTest(unittest.TestCase):
    def make_service(self, tmpdir: str, llm=None) -> AlertService:
        return AlertService(
            message_generator=LLMMessageGenerator(llm=llm, prompt_version="v1"),
            tts=DryRunTTS(),
            output_dir=tmpdir,
        )

    def test_normal_creates_no_message_or_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_service(tmp).handle(
                RiskDecision(risk_level="NORMAL")
            )
            self.assertFalse(result.warning_sound)
            self.assertFalse(result.voice)
            self.assertIsNone(result.message)
            self.assertIsNone(result.tts_file)

    def test_warning_creates_voice_without_warning_sound(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_service(tmp).handle(
                RiskDecision(
                    risk_level="WARNING",
                    situation="COOKING_UNATTENDED",
                    user_state="OUT",
                )
            )
            self.assertFalse(result.warning_sound)
            self.assertTrue(result.voice)
            self.assertTrue(result.fallback_used)
            self.assertIsNotNone(result.message)
            self.assertIsNotNone(result.tts_file)
            self.assertTrue(Path(result.tts_file).exists())

    def test_high_sets_warning_signal_and_creates_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_service(tmp).handle(
                RiskDecision(
                    risk_level="HIGH",
                    situation="COOKING_UNATTENDED",
                    user_state="OUT",
                    heat_level="HIGH",
                )
            )
            self.assertTrue(result.warning_sound)
            self.assertTrue(result.voice)
            self.assertIsNotNone(result.message)
            self.assertIsNotNone(result.tts_file)
            self.assertTrue(Path(result.tts_file).exists())

    def test_llm_can_be_swapped_without_service_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_service(tmp, llm=FakeLLM()).handle(
                RiskDecision(risk_level="WARNING")
            )
            self.assertEqual(result.llm_name, "fake")
            self.assertFalse(result.fallback_used)
            self.assertIn("조리 상태", result.message)

    def test_empty_llm_response_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_service(tmp, llm=EmptyLLM()).handle(
                RiskDecision(risk_level="HIGH")
            )
            self.assertTrue(result.fallback_used)
            self.assertIsNotNone(result.llm_error)
            self.assertIn("위험 상황", result.message)

    def test_output_writer_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_service(tmp).handle(
                RiskDecision(risk_level=RiskLevel.HIGH)
            )
            path = OutputWriter().save_json(
                result,
                Path(tmp) / "alert_output.json",
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["risk_level"], "HIGH")
            self.assertTrue(data["warning_sound"])
            self.assertTrue(data["voice"])

    def test_negative_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskDecision(risk_level="WARNING", duration=-1)


if __name__ == "__main__":
    unittest.main()
