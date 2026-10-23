from __future__ import annotations

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


DEFAULT_EXAONE_MODEL = "LGAI-EXAONE/EXAONE-4.0-32B"
DEFAULT_EXAONE_BASE_URL = "https://api.friendli.ai/serverless/v1"
DEFAULT_EXAONE_TIMEOUT_SECONDS = 30.0
DEFAULT_EXAONE_MAX_RETRIES = 2
DEFAULT_EXAONE_MAX_TOKENS = 256
DEFAULT_EXAONE_TEMPERATURE = 0.3

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)


def _new_openai_client(**kwargs: Any) -> Any:
    """Import the optional SDK only when the EXAONE provider is selected."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMConfigurationError(
            "The 'openai' package is required for LLM_PROVIDER=exaone. "
            "Install the project requirements first."
        ) from exc
    return OpenAI(**kwargs)


def _read_float(name: str, default: float, *, allow_zero: bool = False) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be a number") from exc
    if value < 0 or (value == 0 and not allow_zero):
        boundary = "0 or greater" if allow_zero else "greater than 0"
        raise LLMConfigurationError(f"{name} must be {boundary}")
    return value


def _read_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise LLMConfigurationError(f"{name} must be at least {minimum}")
    return value


class EXAONEAdapter(BaseLLMAdapter):
    name = "exaone"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        client: Any | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("FRIENDLI_API_KEY", "")).strip()
        if not self.api_key:
            raise LLMConfigurationError(
                "FRIENDLI_API_KEY environment variable is required for LLM_PROVIDER=exaone."
            )

        self.model_name = (
            model_name if model_name is not None else os.getenv("EXAONE_MODEL", DEFAULT_EXAONE_MODEL)
        ).strip()
        self.base_url = (
            base_url if base_url is not None else os.getenv("EXAONE_BASE_URL", DEFAULT_EXAONE_BASE_URL)
        ).strip().rstrip("/")
        if not self.model_name:
            raise LLMConfigurationError("EXAONE_MODEL must not be empty")
        if not self.base_url:
            raise LLMConfigurationError("EXAONE_BASE_URL must not be empty")

        self.timeout = timeout if timeout is not None else _read_float(
            "EXAONE_TIMEOUT_SECONDS", DEFAULT_EXAONE_TIMEOUT_SECONDS
        )
        self.max_retries = max_retries if max_retries is not None else _read_int(
            "EXAONE_MAX_RETRIES", DEFAULT_EXAONE_MAX_RETRIES, minimum=0
        )
        self.max_tokens = max_tokens if max_tokens is not None else _read_int(
            "EXAONE_MAX_TOKENS", DEFAULT_EXAONE_MAX_TOKENS, minimum=1
        )
        self.temperature = temperature if temperature is not None else _read_float(
            "EXAONE_TEMPERATURE", DEFAULT_EXAONE_TEMPERATURE, allow_zero=True
        )
        if self.timeout <= 0:
            raise LLMConfigurationError("EXAONE timeout must be greater than 0")
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise LLMConfigurationError("EXAONE max_retries must be a non-negative integer")
        if type(self.max_tokens) is not int or self.max_tokens < 1:
            raise LLMConfigurationError("EXAONE max_tokens must be a positive integer")
        if not 0 <= self.temperature <= 2:
            raise LLMConfigurationError("EXAONE temperature must be in the range [0, 2]")

        # A single client owns the connection pool and the SDK's bounded retry policy.
        if client is not None:
            self.client = client
        else:
            try:
                self.client = _new_openai_client(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                    max_retries=self.max_retries,
                )
            except LLMConfigurationError:
                raise
            except Exception as exc:
                raise LLMConfigurationError(
                    "Failed to initialize the FriendliAI OpenAI-compatible client."
                ) from exc

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=False,
                # HomeVIS needs only the final TTS/JSON text, never chain-of-thought.
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except Exception as exc:
            self._raise_api_error(exc)

        return self._extract_final_text(response)

    @staticmethod
    def _extract_final_text(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMResponseError("EXAONE API response contains no choices")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("EXAONE API response contains no final answer text")

        # Friendli normally separates reasoning_content from content. This also
        # protects downstream TTS/JSON parsing if a server leaves <think> inline.
        cleaned = _THINK_BLOCK.sub("", content).strip()
        if re.search(r"<think\b", cleaned, re.IGNORECASE):
            raise LLMResponseError("EXAONE API returned an unterminated reasoning block")
        if not cleaned:
            raise LLMResponseError("EXAONE API response contains reasoning but no final answer")
        return cleaned

    @staticmethod
    def _raise_api_error(exc: Exception) -> NoReturn:
        status_code = getattr(exc, "status_code", None)
        error_name = type(exc).__name__
        if status_code in {401, 403} or error_name == "AuthenticationError":
            raise LLMAuthenticationError(
                "FriendliAI authentication failed; check FRIENDLI_API_KEY."
            ) from exc
        if error_name == "APITimeoutError":
            raise LLMRequestTimeoutError("FriendliAI EXAONE request timed out.") from exc
        if status_code == 429 or error_name == "RateLimitError":
            raise LLMServiceError("FriendliAI EXAONE rate limit was reached.") from exc
        if status_code in {400, 404, 422}:
            raise LLMConfigurationError(
                f"FriendliAI rejected the EXAONE request configuration (HTTP {status_code})."
            ) from exc
        if error_name == "APIConnectionError" or (
            isinstance(status_code, int) and status_code >= 500
        ):
            raise LLMServiceError("FriendliAI EXAONE service is temporarily unavailable.") from exc
        if isinstance(status_code, int):
            raise LLMServiceError(f"FriendliAI EXAONE request failed with HTTP {status_code}.") from exc
        raise LLMServiceError(f"FriendliAI EXAONE request failed ({error_name}).") from exc
