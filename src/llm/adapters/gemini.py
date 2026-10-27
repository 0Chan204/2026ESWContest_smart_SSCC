from __future__ import annotations

from copy import copy
from math import isfinite
import os

from google import genai
from google.genai import types

from .base import (
    BaseLLMAdapter, LLMAuthenticationError, LLMConfigurationError,
    LLMRequestTimeoutError, LLMResponseError, LLMServiceError,
)


class GeminiAdapter(BaseLLMAdapter):
    name = "gemini-2.5-flash"

    def __init__(
        self,
        model_name: str | None = None,
        temperature: float = 0.3,
        *, timeout: float | None = None, max_retries: int | None = None, client=None,
    ) -> None:
        self.model_name = (model_name if model_name is not None else
                          os.getenv("GEMINI_MODEL", "gemini-2.5-flash")).strip()
        self.temperature = temperature
        try:
            self.timeout = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30")) if timeout is None else timeout
            self.max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "2")) if max_retries is None else max_retries
        except (ValueError, TypeError):
            raise LLMConfigurationError("Invalid Gemini timeout/retry configuration") from None
        if type(self.timeout) not in (int, float) or not isfinite(self.timeout) or self.timeout <= 0:
            raise LLMConfigurationError("GEMINI_TIMEOUT_SECONDS must be finite and positive")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 5:
            raise LLMConfigurationError("GEMINI_MAX_RETRIES must be an integer in [0, 5]")
        if not self.model_name:
            raise LLMConfigurationError("GEMINI_MODEL must not be empty")
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip()
        if not project or not location:
            raise LLMConfigurationError("GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are required")
        try:
            # Retain Vertex AI / ADC; never silently switch to the Gemini API.
            self.client = client if client is not None else genai.Client(
                vertexai=True, project=project, location=location, http_options=self._http_options())
        except Exception:
            raise LLMConfigurationError("Failed to initialize the Vertex AI client; check ADC configuration") from None

    def _http_options(self):
        return types.HttpOptions(timeout=max(1, int(self.timeout * 1000)),
                                 retry_options=types.HttpRetryOptions(attempts=self.max_retries + 1))

    def with_timeout(self, seconds):
        """Reuse the client with a shorter voice deadline and no additional retries."""
        adapter = copy(self)
        adapter.timeout = min(seconds, self.timeout)
        adapter.max_retries = 0
        return adapter

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=system_prompt,
                    temperature=self.temperature, http_options=self._http_options()))
        except Exception as exc:
            status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            name = type(exc).__name__
            if status in {401, 403} or name in {"RefreshError", "DefaultCredentialsError"}:
                raise LLMAuthenticationError("Vertex AI authentication failed; check ADC credentials") from None
            if isinstance(exc, TimeoutError) or "Timeout" in name:
                raise LLMRequestTimeoutError("Vertex AI request timed out") from None
            raise LLMServiceError("Vertex AI request failed") from None
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise LLMResponseError("Gemini returned an empty response")
        return text.strip()
