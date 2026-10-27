from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from src.llm.adapters.base import BaseLLMAdapter
from src.llm.prompts import (
    FEEDBACK_INTERPRETATION_SYSTEM_PROMPT,
    build_feedback_interpretation_prompt,
)


NATURAL_LANGUAGE_FEEDBACK = {
    "positive", "unnecessary", "too_sensitive", "too_late",
    "cancel", "user_override", "unknown",
}


@dataclass(frozen=True)
class FeedbackInterpretation:
    feedback: str
    reason: str
    confidence: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback": self.feedback,
            "reason": self.reason,
            "confidence": self.confidence,
        }


class NaturalLanguageFeedbackInterpreter:
    """Convert natural language to one existing feedback label; never update weights."""

    def __init__(self, llm: BaseLLMAdapter | None, *, max_retries: int = 1) -> None:
        if type(max_retries) is not int or not 0 <= max_retries <= 1:
            raise ValueError("max_retries must be 0 or 1")
        self.llm = llm
        self.max_retries = max_retries

    @property
    def llm_name(self) -> str:
        return "none" if self.llm is None else self.llm.name

    def interpret(
        self,
        action_context: Mapping[str, Any],
        user_text: str,
    ) -> FeedbackInterpretation:
        if self.llm is None:
            return FeedbackInterpretation("unknown", "llm_not_configured", 0.0)
        if not isinstance(user_text, str) or not user_text.strip():
            return FeedbackInterpretation("unknown", "empty_feedback", 0.0)
        prompt = build_feedback_interpretation_prompt(dict(action_context), user_text.strip())
        last_error: Exception | None = None
        received_response = False
        for _ in range(self.max_retries + 1):
            try:
                response = self.llm.generate(FEEDBACK_INTERPRETATION_SYSTEM_PROMPT, prompt)
                received_response = True
                return self._parse(response)
            except Exception as exc:
                last_error = exc
        reason = "parse_error" if received_response else "generation_error"
        error = None if last_error is None else type(last_error).__name__
        return FeedbackInterpretation("unknown", reason, 0.0, error)

    def _parse(self, response: str) -> FeedbackInterpretation:
        if not isinstance(response, str) or not response.strip():
            raise ValueError("LLM returned an empty response")
        payload = self._extract_json_object(response)
        missing = {"feedback", "reason", "confidence"} - set(payload)
        if missing:
            raise ValueError(f"feedback JSON is missing keys: {sorted(missing)}")
        feedback = payload["feedback"]
        reason = payload["reason"]
        if not isinstance(feedback, str) or feedback.strip().lower() not in NATURAL_LANGUAGE_FEEDBACK:
            raise ValueError("LLM returned an unsupported feedback label")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("feedback reason must be a non-empty string")
        raw_confidence = payload["confidence"]
        if isinstance(raw_confidence, bool):
            raise ValueError("feedback confidence must be numeric")
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("feedback confidence must be numeric") from exc
        if not isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("feedback confidence must be between 0 and 1")
        return FeedbackInterpretation(
            feedback.strip().lower(), reason.strip(), confidence
        )

    @staticmethod
    def _extract_json_object(response: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        for index, character in enumerate(response):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(response[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise ValueError("LLM response does not contain a JSON object")

