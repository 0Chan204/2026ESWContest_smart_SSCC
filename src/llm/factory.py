from __future__ import annotations

from src.llm.adapters.base import BaseLLMAdapter
from src.llm.adapters.exaone import EXAONEAdapter
from src.llm.adapters.llama import LlamaAdapter
from src.llm.adapters.qwen import QwenAdapter
from src.llm.adapters.gemini import GeminiAdapter


def create_llm(name: str | None) -> BaseLLMAdapter | None:
    normalized = (name or "none").strip().lower()

    if normalized in {"none", "off", "fallback"}:
        return None

    if normalized == "gemini":
        return GeminiAdapter()

    if normalized == "qwen":
        return QwenAdapter()

    if normalized == "llama":
        return LlamaAdapter()

    if normalized == "exaone":
        return EXAONEAdapter()

    raise ValueError(
        f"Unknown LLM '{name}'. "
        "Choose one of: none, gemini, qwen, llama, exaone"
    )