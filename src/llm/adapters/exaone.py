from __future__ import annotations

from .base import BaseLLMAdapter, LLMNotConfiguredError


class EXAONEAdapter(BaseLLMAdapter):
    name = "exaone"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # TODO: Connect the local EXAONE implementation here later.
        raise LLMNotConfiguredError(
            "EXAONEAdapter is a placeholder. Connect the local EXAONE model here."
        )
