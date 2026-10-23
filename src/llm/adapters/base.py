from __future__ import annotations

from abc import ABC, abstractmethod


class LLMNotConfiguredError(RuntimeError):
    """Raised when an adapter cannot run because required configuration is absent."""


class LLMConfigurationError(LLMNotConfiguredError):
    """Raised for invalid or missing LLM configuration."""


class LLMAuthenticationError(RuntimeError):
    """Raised when an LLM provider rejects its credentials."""


class LLMRequestTimeoutError(RuntimeError):
    """Raised when a remote LLM request exceeds its configured timeout."""


class LLMServiceError(RuntimeError):
    """Raised for a transient or provider-side LLM API failure."""


class LLMResponseError(RuntimeError):
    """Raised when an LLM provider returns no usable final answer."""


class BaseLLMAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError
