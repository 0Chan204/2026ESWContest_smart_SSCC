from __future__ import annotations

from src.llm.adapters.base import BaseLLMAdapter


def create_llm(name: str | None) -> BaseLLMAdapter | None:
    normalized = (name or "none").strip().lower()

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

    raise ValueError(
        f"Unknown LLM '{name}'. "
        "Choose one of: none, gemini, qwen, llama, exaone"
    )
