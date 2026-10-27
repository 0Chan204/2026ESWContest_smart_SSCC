from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.control.confidence.config import DEFAULT_USER_ID
from src.control.confidence.history_storage import DecisionHistoryStorage
from src.control.confidence.weight_manager import SUPPORTED_FEEDBACK, WeightManager
from src.control.feedback.feedback_storage import FeedbackStorage


class FeedbackManager:
    def __init__(
        self,
        history: DecisionHistoryStorage,
        weight_manager: WeightManager,
        storage: FeedbackStorage,
    ) -> None:
        self.history = history
        self.weight_manager = weight_manager
        self.storage = storage

    def apply_feedback(
        self,
        action_id: str,
        feedback: str,
        user_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if feedback not in SUPPORTED_FEEDBACK:
            raise ValueError(f"Unsupported feedback: {feedback}")
        decision = self.history.get(action_id)
        if decision is None:
            raise KeyError(f"Unknown action_id: {action_id}")
        if decision.get("action") is None:
            raise ValueError("Feedback can only be applied to a decision that emitted an action")
        if self.storage.has_action(action_id):
            raise ValueError(f"Feedback was already applied to action_id: {action_id}")
        decision_user = str(decision.get("user_id", DEFAULT_USER_ID))
        target_user = user_id or decision_user
        if user_id is not None and target_user != decision_user:
            raise ValueError("feedback user_id does not match the decision owner")
        scenario = str(decision["scenario"])
        before, after = self.weight_manager.update_from_feedback(
            target_user, scenario, decision["contributions"], feedback
        )
        record = dict(metadata or {})
        record.update({
            "action_id": action_id,
            "scenario": scenario,
            "user_id": target_user,
            "feedback": feedback,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "weights_before": before,
            "weights_after": after,
            "weight_updated": True,
        })
        self.storage.save(record)
        return record

    def feedback_score(self, user_id: str, scenario: str) -> float:
        return self.storage.score(user_id, scenario)
