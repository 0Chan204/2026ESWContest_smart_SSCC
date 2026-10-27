from __future__ import annotations

from .base import BaseLLMAdapter, LLMNotConfiguredError


class LlamaAdapter(BaseLLMAdapter):
    name = "llama"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # TODO: Connect the local Llama implementation here later.
        raise LLMNotConfiguredError(
            "LlamaAdapter is a placeholder. Connect the local Llama model here."
        )
