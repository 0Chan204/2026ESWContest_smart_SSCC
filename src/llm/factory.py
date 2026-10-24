from __future__ import annotations

import os

from src.llm.adapters.base import BaseLLMAdapter


LLM_PROVIDERS = ("none", "gemini", "qwen", "llama", "exaone", "gpt")


def resolve_llm_provider(name: str | None = None) -> str:
    """Resolve an explicit provider, or LLM_PROVIDER while preserving the old default."""
    raw = os.getenv("LLM_PROVIDER", "none") if name is None else name
    return (raw or "none").strip().lower()


def create_llm(name: str | None = None) -> BaseLLMAdapter | None:
    normalized = resolve_llm_provider(name)

    if normalized in {"none", "off", "fallback"}:
        return None

    if normalized == "gemini":
        from src.llm.adapters.gemini import GeminiAdapter
        return GeminiAdapter()

    if normalized == "qwen":
        from src.llm.adapters.qwen import QwenAdapter
        return QwenAdapter()

    if normalized == "llama":
        from src.llm.adapters.llama import LlamaAdapter
        return LlamaAdapter()

    if normalized == "exaone":
        from src.llm.adapters.exaone import EXAONEAdapter
        return EXAONEAdapter()

    if normalized == "gpt":
        from src.llm.adapters.gpt import GPTAdapter
        return GPTAdapter()

    raise ValueError(
        f"Unknown LLM '{normalized}'. "
        f"Choose one of: {', '.join(LLM_PROVIDERS)}"
    )
