"""No API key, GPU, or network needed except for the explicitly opted-in live test."""
import builtins
import json
import os
from pathlib import Path
import traceback
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from src.alert_service import AlertService
from src.control.feedback.natural_language_interpreter import NaturalLanguageFeedbackInterpreter
from src.control.scenario_models import DeviceCommand
from src.llm.adapters.base import (
    LLMAuthenticationError, LLMConfigurationError, LLMRequestTimeoutError,
    LLMResponseError, LLMServiceError,
)
from src.llm.adapters.gpt import GPTAdapter, OPENAI_BASE_URL
from src.llm.factory import LLM_PROVIDERS, create_llm
from src.llm.message_generator import LLMMessageGenerator
from src.llm.prompts import build_user_prompt, get_system_prompt
from src.models import RiskDecision
from src.voice.tts import DryRunTTS


def response(text="안내 문장", **overrides):
    values = dict(status="completed", error=None, output=[NS(
        type="message", role="assistant", status="completed",
        content=[NS(type="output_text", text=text)],
    )])
    values.update(overrides)
    return NS(**values)


def client_for(*results):
    return NS(responses=NS(create=Mock(side_effect=results)))


def adapter_for(*results, **options):
    return GPTAdapter(api_key="test-key", model_name="test-model",
                      client=client_for(*results), **options)


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch, request):
    if request.node.name == "test_live_gpt_api":
        return
    for name in ("LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS",
                 "OPENAI_MAX_RETRIES", "OPENAI_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(name, raising=False)


def test_exact_prompts_request_and_client_reuse():
    adapter = adapter_for(response("첫 안내"), response("둘째 안내"))
    assert adapter.generate("system", "user") == "첫 안내"
    assert adapter.generate("next system", "next user") == "둘째 안내"
    assert adapter.client.responses.create.call_count == 2
    assert adapter.client.responses.create.call_args_list[0].kwargs == {
        "model": "test-model", "input": [
            {"role": "system", "content": "system"}, {"role": "user", "content": "user"}],
        "max_output_tokens": 2048, "stream": False, "store": False,
    }


def test_environment_factory_and_constructor_reused(monkeypatch):
    for key, value in {"LLM_PROVIDER": "gpt", "OPENAI_API_KEY": " environment-key ",
                       "OPENAI_MODEL": " chosen-model ", "OPENAI_TIMEOUT_SECONDS": "12.5",
                       "OPENAI_MAX_RETRIES": "1", "OPENAI_MAX_OUTPUT_TOKENS": "800",
                       "OPENAI_BASE_URL": "https://unrelated.example/v1"}.items():
        monkeypatch.setenv(key, value)
    constructor = Mock(return_value=client_for(response(), response()))
    monkeypatch.setattr("src.llm.adapters.gpt._new_openai_client", constructor)
    adapter = create_llm()
    assert isinstance(adapter, GPTAdapter)
    assert adapter.model_name == "chosen-model"
    assert adapter.max_output_tokens == 800
    adapter.generate("s", "u")
    adapter.generate("s", "u")
    constructor.assert_called_once_with(api_key="environment-key", base_url=OPENAI_BASE_URL,
                                        timeout=12.5, max_retries=1)
    assert "environment-key" not in repr(adapter)


def test_gpt_never_imports_local_models(monkeypatch):
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        assert name not in {"torch", "transformers", "src.llm.adapters.qwen", "src.llm.adapters.llama"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr("src.llm.adapters.gpt._new_openai_client", lambda **_: client_for(response()))
    assert create_llm("gpt").generate("s", "u") == "안내 문장"
    assert "gpt" in LLM_PROVIDERS


def test_default_none_ignores_unselected_gpt_config(monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "invalid")
    assert create_llm() is None


@pytest.mark.parametrize("key,model,missing", [("", "test-model", "OPENAI_API_KEY"),
                                              ("test-key", " ", "OPENAI_MODEL")])
def test_missing_configuration(key, model, missing):
    with pytest.raises(LLMConfigurationError, match=missing):
        GPTAdapter(api_key=key, model_name=model)


@pytest.mark.parametrize("setting,value", [
    ("OPENAI_TIMEOUT_SECONDS", "nan"), ("OPENAI_TIMEOUT_SECONDS", "inf"),
    ("OPENAI_TIMEOUT_SECONDS", "0"), ("OPENAI_TIMEOUT_SECONDS", "secret-invalid-value"),
    ("OPENAI_MAX_RETRIES", "-1"), ("OPENAI_MAX_RETRIES", "6"), ("OPENAI_MAX_RETRIES", "1.5"),
    ("OPENAI_MAX_OUTPUT_TOKENS", "0"), ("OPENAI_MAX_OUTPUT_TOKENS", "15"),
])
def test_invalid_settings_are_rejected_without_echoing_values(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(LLMConfigurationError, match=setting) as error:
        adapter_for(response())
    assert "secret-invalid-value" not in "".join(traceback.format_exception(error.value))


def test_missing_sdk_and_legacy_sdk_are_configuration_errors(monkeypatch):
    original_import = builtins.__import__

    def no_openai(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_openai)
    with pytest.raises(LLMConfigurationError, match="package"):
        GPTAdapter(api_key="test-key", model_name="test-model")
    with pytest.raises(LLMConfigurationError, match="upgrade"):
        GPTAdapter(api_key="test-key", model_name="test-model", client=NS())


@pytest.mark.parametrize("status,expected", [
    (401, LLMAuthenticationError), (403, LLMAuthenticationError),
    (400, LLMConfigurationError), (404, LLMConfigurationError), (422, LLMConfigurationError),
    (429, LLMServiceError), (503, LLMServiceError),
])
def test_api_errors_are_distinct_and_redacted(status, expected):
    error = RuntimeError("secret-provider-body")
    error.status_code = status
    with pytest.raises(expected) as raised:
        adapter_for(error).generate("s", "u")
    assert "secret-provider-body" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("kind,expected", [("APITimeoutError", LLMRequestTimeoutError),
                                          ("APIConnectionError", LLMServiceError)])
def test_transport_errors(kind, expected):
    error = type(kind, (Exception,), {})("secret-network-details")
    with pytest.raises(expected) as raised:
        adapter_for(error).generate("s", "u")
    assert "secret-network-details" not in str(raised.value)


@pytest.mark.parametrize("bad_response", [
    None, NS(), response(" "), response(None), response(status="incomplete"),
    response(status="failed"), response(error=NS(message="private")), response(output=[]),
    response(output="wrong type"), response(output=[NS(type="reasoning", summary="internal")]),
    response(output=[NS(type="function_call", arguments="private")]),
    response(output=[NS(type="message", role="assistant", status="incomplete", content=[])]),
    response(output=[NS(type="message", role="assistant", status="completed", content=[NS(type="refusal")])]),
    response("<think>unfinished reasoning"), response("<think>reasoning only</think>"),
])
def test_empty_malformed_incomplete_and_refused_output_is_rejected(bad_response):
    with pytest.raises(LLMResponseError):
        adapter_for(bad_response).generate("s", "u")


def test_only_final_text_is_returned():
    result = response("<think>inline reasoning</think>안전 확인을 요청했습니다.")
    result.output.insert(0, NS(type="reasoning", summary="private summary"))
    result.output.append(response("주방을 확인해 주세요.").output[0])
    assert adapter_for(result).generate("s", "u") == "안전 확인을 요청했습니다.\n주방을 확인해 주세요."


def test_alert_tts_contract_and_original_prompts(tmp_path):
    adapter = adapter_for(response("즉시 주방 상태를 확인해 주세요."))
    service = AlertService(LLMMessageGenerator(adapter), DryRunTTS(), tmp_path)
    decision = RiskDecision(risk_level="HIGH", situation="COOKING_UNATTENDED", user_state="OUT")
    result = service.handle(decision)
    assert result.message == "즉시 주방 상태를 확인해 주세요."
    assert result.llm_name == "gpt" and not result.fallback_used
    assert Path(result.tts_file).exists()
    assert adapter.client.responses.create.call_args.kwargs["input"] == [
        {"role": "system", "content": get_system_prompt("v1")},
        {"role": "user", "content": build_user_prompt(decision)},
    ]


def test_api_failure_keeps_risk_and_existing_fallback(tmp_path):
    adapter = adapter_for(TimeoutError("private"))
    service = AlertService(LLMMessageGenerator(adapter), DryRunTTS(), tmp_path)
    result = service.handle(RiskDecision(risk_level="HIGH", situation="COOKING_UNATTENDED"))
    assert result.risk_level.value == "HIGH" and result.fallback_used
    assert "LLMRequestTimeoutError" in result.llm_error
    assert result.message and Path(result.tts_file).exists()
    assert "private" not in result.llm_error


def test_feedback_json_and_failure_contract():
    payload = json.dumps({"feedback": "unnecessary", "reason": "not_needed", "confidence": .96})
    result = response(payload)
    result.output.insert(0, NS(type="reasoning", summary='{"feedback":"positive"}'))
    interpreter = NaturalLanguageFeedbackInterpreter(adapter_for(result))
    parsed = interpreter.interpret({"action_id": "a-1", "scenario": "light_auto_off"}, "아직 방에 있어")
    assert parsed.feedback == "unnecessary" and parsed.confidence == .96 and parsed.error is None
    failure = NaturalLanguageFeedbackInterpreter(adapter_for(TimeoutError(), TimeoutError()))
    parsed = failure.interpret({"action_id": "a-1"}, "괜찮아")
    assert parsed.feedback == "unknown" and parsed.confidence == 0


def test_fall_and_water_use_existing_message_paths():
    adapter = adapter_for(response("괜찮으신가요?"), response("물 120밀리리터를 준비하도록 요청했습니다."))
    generator = LLMMessageGenerator(adapter)
    fall = generator.generate(RiskDecision(risk_level="HIGH", decision_context={"scenario": "bathroom_fall"}))
    assert fall.message == "괜찮으신가요?" and not fall.fallback_used
    water = generator.generate_device_command(DeviceCommand(timestamp=0, amount_ml=120))
    assert water.message == "물 120밀리리터를 준비하도록 요청했습니다." and not water.fallback_used


@pytest.mark.parametrize("script", ["test_alert", "test_realtime"])
def test_existing_cli_accepts_gpt(monkeypatch, script):
    import importlib
    module = importlib.import_module(script)
    monkeypatch.setattr("sys.argv", [script + ".py", "--llm", "gpt", "--tts", "dry-run"])
    if script == "test_alert":
        assert module.parse_args().llm == "gpt"
    else:
        class Selected(Exception):
            pass

        def selected(name):
            assert name == "gpt"
            raise Selected

        monkeypatch.setattr(module, "create_llm", selected)
        with pytest.raises(Selected):
            module.main()


def test_continuous_runtime_uses_selected_gpt_without_control_changes(monkeypatch, tmp_path):
    from dataclasses import replace
    from src.integration.backend_client import BackendClient
    from src.integration.runtime import IntegrationRuntime
    from src.integration.settings import load_settings
    from src.integration.simulation import SimulationBackend

    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    constructor = Mock(return_value=client_for(response("주방을 확인해 주세요.")))
    monkeypatch.setattr("src.llm.adapters.gpt._new_openai_client", constructor)
    monkeypatch.setattr("src.integration.runtime.Pyttsx3TTS", DryRunTTS)
    config = replace(load_settings(environ={}, mode="mock", data_dir=tmp_path).integration,
                     async_alerts=False)
    runtime = IntegrationRuntime(config, BackendClient(config, SimulationBackend()))
    try:
        result = runtime.fall_alert_service.handle(RiskDecision(risk_level="HIGH"))
        assert result.llm_name == "gpt" and not result.fallback_used
        assert runtime.outbox.rows() == []  # Text generation never issues a control.
        constructor.assert_called_once()
    finally:
        runtime.close()


def sdk_response():
    return {"id": "resp_mock", "object": "response", "created_at": 0,
            "status": "completed", "error": None, "incomplete_details": None,
            "instructions": None, "metadata": {}, "model": "test-model", "parallel_tool_calls": False,
            "tools": [], "tool_choice": "auto", "output": [
                {"id": "msg_mock", "type": "message", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": "주방을 확인해 주세요.", "annotations": []}]}]}


@pytest.mark.parametrize("status,expected_calls", [(429, 3), (500, 3), (401, 1), (400, 1)])
def test_real_sdk_http_transport_retries_are_bounded(status, expected_calls):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after-ms": "1"},
                              json={"error": {"message": "private", "type": "test_error"}})

    with openai.OpenAI(api_key="test-key", base_url=OPENAI_BASE_URL, max_retries=2,
                       http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        with pytest.raises((LLMServiceError, LLMAuthenticationError, LLMConfigurationError)):
            GPTAdapter(api_key="test-key", model_name="test-model", client=client).generate("s", "u")
    assert len(calls) == expected_calls
    assert all(request.url.path == "/v1/responses" for request in calls)


def test_real_sdk_success_after_timeout_without_network():
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            raise httpx.ReadTimeout("mock timeout", request=request)
        return httpx.Response(200, json=sdk_response())

    with openai.OpenAI(api_key="test-key", max_retries=1,
                       http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        adapter = GPTAdapter(api_key="test-key", model_name="test-model", client=client)
        assert adapter.generate("system", "user") == "주방을 확인해 주세요."
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0]["store"] is False


@pytest.mark.skipif(
    os.getenv("RUN_GPT_API_TEST") != "1" or not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"),
    reason="set RUN_GPT_API_TEST=1, OPENAI_API_KEY and OPENAI_MODEL to call OpenAI (billable)",
)
def test_live_gpt_api():
    adapter = GPTAdapter(timeout=60, max_retries=0)
    try:
        result = adapter.generate("답변만 간결하게 출력하세요.", "HomeVIS API 연결 확인이라고 답하세요.")
        assert isinstance(result, str) and result.strip()
    finally:
        adapter.client.close()
