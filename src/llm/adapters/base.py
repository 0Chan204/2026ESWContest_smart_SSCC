from __future__ import annotations

from abc import ABC, abstractmethod


class LLMNotConfiguredError(RuntimeError):
    """Raised when a placeholder adapter has no real local model attached."""


class BaseLLMAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError
