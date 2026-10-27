"""Public model selection only; credentials remain in the provider environment."""
from dataclasses import dataclass
from math import isfinite

from .factory import LLM_PROVIDERS, resolve_llm_provider


@dataclass(frozen=True)
class LLMConfig:
    provider: str = ""  # Empty means the existing LLM_PROVIDER environment setting.
    model: str = ""     # Empty means the selected adapter's environment/default.
    failure_retry_seconds: float = 30.0  # API recovery only; never a sensing hold time.

    def __post_init__(self):
        if (type(self.failure_retry_seconds) not in (int, float)
                or not isfinite(self.failure_retry_seconds) or self.failure_retry_seconds <= 0):
            raise ValueError("llm.failure_retry_seconds must be finite and positive")
        for key in ("provider", "model"):
            value = getattr(self, key)
            if not isinstance(value, str):
                raise ValueError(f"llm.{key} must be a string")
            object.__setattr__(self, key, value.strip())
        object.__setattr__(self, "provider", self.provider.lower())
        if self.provider == "llama":
            raise ValueError("llm.provider=llama is not implemented")
        if self.provider and self.provider not in LLM_PROVIDERS:
            raise ValueError("llm.provider must be none, exaone, gpt, qwen, gemini, or empty")

    @property
    def resolved_provider(self):
        return resolve_llm_provider(self.provider or None)
