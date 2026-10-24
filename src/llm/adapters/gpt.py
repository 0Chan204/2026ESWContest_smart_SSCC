"""OpenAI Responses API behind the existing text-in/text-out LLM contract."""
from __future__ import annotations

from math import isfinite
import os
import re
from typing import Any, NoReturn

from .base import (
    BaseLLMAdapter,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRequestTimeoutError,
    LLMResponseError,
    LLMServiceError,
)


OPENAI_BASE_URL = "https://api.openai.com/v1"
_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)


def _new_openai_client(**kwargs: Any) -> Any:
    # Keep torch/transformers and the optional OpenAI SDK out of other providers.
    try:
        from openai import OpenAI
    except ImportError:
        raise LLMConfigurationError(
            "GPT requires the 'openai' package; install -r requirements.txt."
        ) from None
    return OpenAI(**kwargs)


def _number(name: str, default: int | float, converter: type) -> int | float:
    raw = os.getenv(name, "").strip()
    try:
        return converter(raw) if raw else default
    except (ValueError, OverflowError):
        # Never echo invalid environment values, which might contain secrets.
        raise LLMConfigurationError(f"{name} must be a valid {converter.__name__}") from None


class GPTAdapter(BaseLLMAdapter):
    name = "gpt"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        max_output_tokens: int | None = None,
        client: Any | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        if not isinstance(key, str) or not key.strip():
            raise LLMConfigurationError("OPENAI_API_KEY is required for LLM_PROVIDER=gpt.")
        model = model_name if model_name is not None else os.getenv("OPENAI_MODEL", "")
        if not isinstance(model, str) or not model.strip():
            raise LLMConfigurationError("OPENAI_MODEL is required for LLM_PROVIDER=gpt.")
        self.model_name = model.strip()
        self.timeout = timeout if timeout is not None else _number("OPENAI_TIMEOUT_SECONDS", 30.0, float)
        self.max_retries = max_retries if max_retries is not None else _number("OPENAI_MAX_RETRIES", 2, int)
        self.max_output_tokens = max_output_tokens if max_output_tokens is not None else _number(
            "OPENAI_MAX_OUTPUT_TOKENS", 2048, int
        )
        if (type(self.timeout) not in {int, float} or not isfinite(self.timeout)
                or self.timeout <= 0):
            raise LLMConfigurationError("OPENAI_TIMEOUT_SECONDS must be finite and greater than 0.")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 5:
            raise LLMConfigurationError("OPENAI_MAX_RETRIES must be an integer from 0 to 5.")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 16:
            raise LLMConfigurationError("OPENAI_MAX_OUTPUT_TOKENS must be an integer of at least 16.")

        try:
            # One connection pool per adapter; retries are owned only by the SDK.
            # Explicit URL avoids inheriting an unrelated OpenAI-compatible endpoint.
            self.client = client if client is not None else _new_openai_client(
                api_key=key.strip(), base_url=OPENAI_BASE_URL,
                timeout=self.timeout, max_retries=self.max_retries,
            )
        except LLMConfigurationError:
            raise
        except Exception:
            raise LLMConfigurationError("Failed to initialize the OpenAI GPT client.") from None
        if not callable(getattr(getattr(self.client, "responses", None), "create", None)):
            raise LLMConfigurationError("GPT requires an OpenAI SDK with Responses API support; upgrade openai.")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self.client.responses.create(
                model=self.model_name,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_output_tokens=self.max_output_tokens,
                stream=False,
                store=False,
                # No model-specific sampling/reasoning settings or tool access.
            )
        except Exception as exc:
            self._raise_api_error(exc)
        return self._extract_final_text(response)

    @staticmethod
    def _extract_final_text(response: Any) -> str:
        # Truncated JSON/prose must not be treated as a valid feedback/announcement.
        if getattr(response, "status", None) != "completed" or getattr(response, "error", None) is not None:
            raise LLMResponseError("OpenAI GPT response was not completed successfully.")
        output = getattr(response, "output", None)
        if not isinstance(output, list) or not output:
            raise LLMResponseError("OpenAI GPT response contains no output.")
        texts = []
        for item in output:
            if getattr(item, "type", None) == "reasoning":
                continue
            if (getattr(item, "type", None) != "message"
                    or getattr(item, "role", None) != "assistant"
                    or getattr(item, "status", None) != "completed"):
                raise LLMResponseError("OpenAI GPT returned an unexpected output item.")
            content = getattr(item, "content", None)
            if not isinstance(content, list) or not content:
                raise LLMResponseError("OpenAI GPT returned an empty message.")
            for part in content:
                if getattr(part, "type", None) == "refusal":
                    raise LLMResponseError("OpenAI GPT declined the text generation request.")
                text = getattr(part, "text", None)
                if getattr(part, "type", None) != "output_text" or not isinstance(text, str):
                    raise LLMResponseError("OpenAI GPT returned an invalid text part.")
                texts.append(text)
        # Do not return reasoning summaries, tool payloads, or inline thinking.
        cleaned = _THINK_BLOCK.sub("", "\n".join(texts)).strip()
        if re.search(r"</?think\b", cleaned, re.IGNORECASE) or not cleaned:
            raise LLMResponseError("OpenAI GPT response contains no usable final answer text.")
        return cleaned

    @staticmethod
    def _raise_api_error(exc: Exception) -> NoReturn:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        # Suppress original exception chains: provider bodies can echo credentials.
        if status in {401, 403} or name in {"AuthenticationError", "PermissionDeniedError"}:
            raise LLMAuthenticationError("OpenAI authentication/access failed; check OPENAI_API_KEY and model access.") from None
        if name == "APITimeoutError" or isinstance(exc, TimeoutError):
            raise LLMRequestTimeoutError("OpenAI GPT request timed out.") from None
        if status in {400, 404, 422}:
            raise LLMConfigurationError("OpenAI rejected the GPT request configuration; check model and parameters.") from None
        if status == 429 or name == "RateLimitError":
            raise LLMServiceError("OpenAI GPT rate limit or API quota was reached.") from None
        raise LLMServiceError("OpenAI GPT service request failed.") from None
