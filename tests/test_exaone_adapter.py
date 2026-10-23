from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.alert_service import AlertService
from src.control.feedback.natural_language_interpreter import (
    NaturalLanguageFeedbackInterpreter,
)
from src.llm.adapters.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRequestTimeoutError,
    LLMResponseError,
    LLMServiceError,
)
from src.llm.adapters.exaone import (
    DEFAULT_EXAONE_BASE_URL,
    DEFAULT_EXAONE_MODEL,
    EXAONEAdapter,
)
from src.llm.factory import create_llm
from src.llm.message_generator import LLMMessageGenerator
from src.models import RiskDecision
from src.voice.tts import DryRunTTS


def completion(content: str | None, *, reasoning: str | None = None):
    message = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.results:
            raise AssertionError("fake response queue is empty")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, *results):
        self.completions = FakeCompletions(*results)
        self.chat = SimpleNamespace(completions=self.completions)


class EXAONEAdapterTest(unittest.TestCase):
    def adapter(self, client: FakeClient, **kwargs) -> EXAONEAdapter:
        return EXAONEAdapter(api_key="test-key", client=client, **kwargs)

    def test_exaone_sends_openai_compatible_chat_completion_and_reuses_client(self):
        client = FakeClient(completion("첫 번째 안내"), completion("두 번째 안내"))
        adapter = self.adapter(client)

        self.assertEqual(adapter.generate("system one", "user one"), "첫 번째 안내")
        self.assertEqual(adapter.generate("system two", "user two"), "두 번째 안내")
        self.assertIs(adapter.client, client)
        self.assertEqual(adapter.base_url, DEFAULT_EXAONE_BASE_URL)
        self.assertEqual(len(client.completions.calls), 2)

        request = client.completions.calls[0]
        self.assertEqual(request["model"], DEFAULT_EXAONE_MODEL)
        self.assertEqual(request["messages"], [
            {"role": "system", "content": "system one"},
            {"role": "user", "content": "user one"},
        ])
        self.assertFalse(request["stream"])
        self.assertEqual(
            request["extra_body"],
            {"chat_template_kwargs": {"enable_thinking": False}},
        )

    def test_api_key_and_settings_are_loaded_from_environment(self):
        client = FakeClient(completion("ok"))
        environment = {
            "FRIENDLI_API_KEY": "environment-key",
            "EXAONE_MODEL": "custom/model",
            "EXAONE_BASE_URL": "https://friendli.example/v1/",
            "EXAONE_TIMEOUT_SECONDS": "12.5",
            "EXAONE_MAX_RETRIES": "1",
            "EXAONE_MAX_TOKENS": "99",
            "EXAONE_TEMPERATURE": "0",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "src.llm.adapters.exaone._new_openai_client", return_value=client
        ) as constructor:
            adapter = EXAONEAdapter()

        constructor.assert_called_once_with(
            api_key="environment-key",
            base_url="https://friendli.example/v1",
            timeout=12.5,
            max_retries=1,
        )
        self.assertEqual(adapter.model_name, "custom/model")
        self.assertEqual(adapter.max_tokens, 99)
        self.assertEqual(adapter.temperature, 0)

    def test_missing_api_key_is_a_configuration_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LLMConfigurationError, "FRIENDLI_API_KEY"):
                EXAONEAdapter(client=FakeClient(completion("unused")))

    def test_authentication_error_is_distinct_from_configuration_error(self):
        error = RuntimeError("provider body must not leak")
        error.status_code = 401
        adapter = self.adapter(FakeClient(error))
        with self.assertRaisesRegex(LLMAuthenticationError, "authentication failed"):
            adapter.generate("system", "user")

    def test_timeout_is_translated_without_exposing_provider_details(self):
        class APITimeoutError(Exception):
            pass

        adapter = self.adapter(FakeClient(APITimeoutError("socket details")))
        with self.assertRaisesRegex(LLMRequestTimeoutError, "timed out"):
            adapter.generate("system", "user")

    def test_rate_limit_is_reported_as_a_service_error(self):
        error = RuntimeError("provider body must not leak")
        error.status_code = 429
        adapter = self.adapter(FakeClient(error))
        with self.assertRaisesRegex(LLMServiceError, "rate limit") as raised:
            adapter.generate("system", "user")
        self.assertNotIn("provider body", str(raised.exception))

    def test_empty_or_malformed_response_is_rejected(self):
        responses = (
            SimpleNamespace(choices=[]),
            completion(None),
            completion("   "),
        )
        for response in responses:
            with self.subTest(response=response):
                adapter = self.adapter(FakeClient(response))
                with self.assertRaises(LLMResponseError):
                    adapter.generate("system", "user")

    def test_reasoning_is_not_returned_to_tts_or_json_parser(self):
        client = FakeClient(completion(
            "<think>내부 추론은 노출하지 않는다.</think>\n화력을 확인해 주세요.",
            reasoning="별도 reasoning 필드",
        ))
        adapter = self.adapter(client)
        self.assertEqual(adapter.generate("system", "user"), "화력을 확인해 주세요.")

        reasoning_only = self.adapter(FakeClient(completion("<think>only reasoning")))
        with self.assertRaises(LLMResponseError):
            reasoning_only.generate("system", "user")

    def test_alert_text_and_tts_contract_are_unchanged(self):
        client = FakeClient(completion("즉시 주방 상태를 확인해 주세요."))
        with tempfile.TemporaryDirectory() as directory:
            service = AlertService(
                LLMMessageGenerator(self.adapter(client)),
                DryRunTTS(),
                directory,
            )
            result = service.handle(RiskDecision(
                risk_level="HIGH",
                situation="COOKING_UNATTENDED",
                user_state="OUT",
            ))
            self.assertEqual(result.message, "즉시 주방 상태를 확인해 주세요.")
            self.assertEqual(result.llm_name, "exaone")
            self.assertFalse(result.fallback_used)
            self.assertTrue(Path(result.tts_file).exists())

    def test_api_failure_preserves_decision_and_uses_existing_fallback(self):
        class APITimeoutError(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory:
            service = AlertService(
                LLMMessageGenerator(
                    self.adapter(FakeClient(APITimeoutError("network timeout")))
                ),
                DryRunTTS(),
                directory,
            )
            result = service.handle(RiskDecision(
                risk_level="HIGH",
                situation="COOKING_UNATTENDED",
                user_state="OUT",
            ))
            self.assertEqual(result.risk_level.value, "HIGH")
            self.assertTrue(result.fallback_used)
            self.assertIn("LLMRequestTimeoutError", result.llm_error)
            self.assertTrue(result.message)
            self.assertTrue(Path(result.tts_file).exists())

    def test_feedback_json_uses_the_same_adapter_contract(self):
        payload = json.dumps({
            "feedback": "unnecessary",
            "reason": "user_says_action_was_not_needed",
            "confidence": 0.96,
        }, ensure_ascii=False)
        interpreter = NaturalLanguageFeedbackInterpreter(
            self.adapter(FakeClient(completion(payload)))
        )
        parsed = interpreter.interpret(
            {"action_id": "action-1", "scenario": "light_auto_off"},
            "아직 방에 있는데 왜 불을 껐어?",
        )
        self.assertEqual(parsed.feedback, "unnecessary")
        self.assertEqual(parsed.confidence, 0.96)
        self.assertIsNone(parsed.error)


class LLMFactorySelectionTest(unittest.TestCase):
    def test_qwen_selection_keeps_the_existing_adapter_path(self):
        fake_module = types.ModuleType("src.llm.adapters.qwen")

        class FakeQwenAdapter:
            name = "qwen3-8b"

        fake_module.QwenAdapter = FakeQwenAdapter
        with patch.dict(sys.modules, {"src.llm.adapters.qwen": fake_module}):
            selected = create_llm("qwen")
        self.assertIsInstance(selected, FakeQwenAdapter)

    def test_exaone_selection_does_not_import_or_construct_qwen(self):
        fake_qwen_module = types.ModuleType("src.llm.adapters.qwen")

        class QwenMustNotLoad:
            def __init__(self):
                raise AssertionError("Qwen must not load for EXAONE")

        fake_qwen_module.QwenAdapter = QwenMustNotLoad
        client = FakeClient(completion("ok"))
        with patch.dict(
            sys.modules, {"src.llm.adapters.qwen": fake_qwen_module}
        ), patch.dict(
            os.environ, {"FRIENDLI_API_KEY": "test-key"}, clear=True
        ), patch(
            "src.llm.adapters.exaone._new_openai_client", return_value=client
        ):
            selected = create_llm("exaone")
        self.assertIsInstance(selected, EXAONEAdapter)

    def test_environment_selects_exaone_and_absent_environment_preserves_none(self):
        client = FakeClient(completion("ok"))
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(create_llm())
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "exaone", "FRIENDLI_API_KEY": "test-key"
        }, clear=True), patch(
            "src.llm.adapters.exaone._new_openai_client", return_value=client
        ):
            self.assertIsInstance(create_llm(), EXAONEAdapter)


@unittest.skipUnless(
    os.getenv("RUN_EXAONE_API_TEST") == "1" and bool(os.getenv("FRIENDLI_API_KEY")),
    "set RUN_EXAONE_API_TEST=1 and FRIENDLI_API_KEY to call FriendliAI",
)
class EXAONELiveAPITest(unittest.TestCase):
    def test_friendli_chat_completion(self):
        adapter = EXAONEAdapter(timeout=60, max_retries=1, max_tokens=64)
        result = adapter.generate(
            "답변만 간결하게 출력하세요.",
            "HomeVIS EXAONE API 연결 확인이라고 답하세요.",
        )
        self.assertIsInstance(result, str)
        self.assertTrue(result.strip())


if __name__ == "__main__":
    unittest.main()
