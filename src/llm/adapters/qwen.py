from __future__ import annotations

from .base import BaseLLMAdapter, LLMNotConfiguredError


class QwenAdapter(BaseLLMAdapter):
    name = "qwen"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # TODO: Connect the local Qwen implementation here later.
        raise LLMNotConfiguredError(
            "QwenAdapter is a placeholder. Connect the local Qwen model here."
        )
