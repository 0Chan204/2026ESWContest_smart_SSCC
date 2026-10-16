from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.control.confidence.config import ConfidenceConfig, DEFAULT_USER_ID
from src.control.confidence.history_storage import DecisionHistoryStorage
from src.control.feedback.feedback_manager import FeedbackManager
from src.control.feedback.feedback_storage import FeedbackStorage
from src.control.feedback.natural_language_interpreter import (
    FeedbackInterpretation,
    NaturalLanguageFeedbackInterpreter,
)


class NaturalLanguageFeedbackService:
    """Resolve action context and route confident labels into the existing pipeline."""

    def __init__(
        self,
        interpreter: NaturalLanguageFeedbackInterpreter,
        history: DecisionHistoryStorage,
        feedback_manager: FeedbackManager,
        storage: FeedbackStorage,
        config: ConfidenceConfig,
    ) -> None:
        self.interpreter = interpreter
        self.history = history
        self.feedback_manager = feedback_manager
        self.storage = storage
        self.config = config

    def apply_natural_language_feedback(
        self,
        action_id: str | None,
        user_text: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        decision = self.history.get(action_id) if action_id else None
        if decision is None:
            reason = "action_id_missing" if not action_id else "action_not_found"
            return self._save_unapplied(
                action_id=action_id,
                user_text=user_text,
                parsed=FeedbackInterpretation("unknown", reason, 0.0),
                decision=None,
                user_id=user_id or DEFAULT_USER_ID,
                status="ambiguous",
            )
        action = decision.get("action")
        if not isinstance(action, Mapping):
            return self._save_unapplied(
                action_id=action_id,
                user_text=user_text,
                parsed=FeedbackInterpretation("unknown", "decision_has_no_action", 0.0),
                decision=decision,
                user_id=user_id or str(decision.get("user_id", DEFAULT_USER_ID)),
                status="ambiguous",
            )
        owner = str(decision.get("user_id", DEFAULT_USER_ID))
        if user_id is not None and user_id != owner:
            return self._save_unapplied(
                action_id=action_id,
                user_text=user_text,
                parsed=FeedbackInterpretation("unknown", "user_id_mismatch", 0.0),
                decision=decision,
                user_id=user_id,
                status="rejected",
            )
        context = self._action_context(decision, action)
        parsed = self.interpreter.interpret(context, user_text)
        if parsed.confidence < self.config.FEEDBACK_REVIEW_THRESHOLD:
            if parsed.feedback != "unknown":
                parsed = FeedbackInterpretation(
                    "unknown", "low_feedback_confidence", parsed.confidence, parsed.error
                )
            return self._save_unapplied(
                action_id=action_id, user_text=user_text, parsed=parsed,
                decision=decision, user_id=owner, status="ambiguous",
            )
        if parsed.feedback == "unknown":
            return self._save_unapplied(
                action_id=action_id, user_text=user_text, parsed=parsed,
                decision=decision, user_id=owner, status="ambiguous",
            )
        if parsed.confidence < self.config.FEEDBACK_APPLY_THRESHOLD:
            return self._save_unapplied(
                action_id=action_id, user_text=user_text, parsed=parsed,
                decision=decision, user_id=owner, status="review_required",
            )
        metadata = self._base_record(
            action_id, user_text, parsed, decision, owner, status="applied"
        )
        try:
            return self.feedback_manager.apply_feedback(
                action_id=action_id,
                feedback=parsed.feedback,
                user_id=owner,
                metadata=metadata,
            )
        except Exception as exc:
            metadata.update({
                "feedback": parsed.feedback,
                "weight_updated": False,
                "status": "apply_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.storage.save(metadata)
            return metadata

    def _save_unapplied(
        self,
        *,
        action_id: str | None,
        user_text: str,
        parsed: FeedbackInterpretation,
        decision: Mapping[str, Any] | None,
        user_id: str,
        status: str,
    ) -> dict[str, Any]:
        record = self._base_record(
            action_id, user_text, parsed, decision, user_id, status=status
        )
        record.update({
            "feedback": parsed.feedback,
            "weight_updated": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if parsed.error:
            record["error"] = parsed.error
        self.storage.save(record)
        return record

    def _base_record(
        self,
        action_id: str | None,
        user_text: str,
        parsed: FeedbackInterpretation,
        decision: Mapping[str, Any] | None,
        user_id: str,
        *,
        status: str,
    ) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "raw_feedback": user_text,
            "parsed_feedback": parsed.to_dict(),
            "scenario": None if decision is None else decision.get("scenario"),
            "user_id": user_id,
            "action_confidence": None if decision is None else decision.get("confidence"),
            "feedback_confidence": parsed.confidence,
            "weight_updated": False,
            "status": status,
            "llm_name": self.interpreter.llm_name,
        }

    @staticmethod
    def _action_context(
        decision: Mapping[str, Any], action: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "action_id": decision.get("action_id"),
            "scenario": decision.get("scenario"),
            "device": action.get("device"),
            "action": action.get("action"),
            "reason": action.get("reason"),
            "action_confidence": decision.get("confidence"),
            "timestamp": decision.get("timestamp"),
            "features": decision.get("features"),
            "weights": decision.get("weights"),
            "contributions": decision.get("contributions"),
        }
