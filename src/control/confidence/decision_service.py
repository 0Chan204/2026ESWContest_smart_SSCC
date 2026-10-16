from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import uuid4

from src.control.automation_models import AutomationAction, AutomationDecision
from src.control.confidence.confidence_engine import ConfidenceEngine
from src.control.confidence.config import ConfidenceConfig, DEFAULT_USER_ID
from src.control.confidence.history_storage import DecisionHistoryStorage


class ConfidenceDecisionService:
    def __init__(
        self,
        engine: ConfidenceEngine,
        history: DecisionHistoryStorage,
        config: ConfidenceConfig | None = None,
        feedback_score: Callable[[str, str], float] | None = None,
    ) -> None:
        self.engine = engine
        self.history = history
        self.config = config or engine.weight_manager.config
        self.feedback_score = feedback_score or (lambda _user_id, _scenario: 0.5)

    def score(
        self,
        *,
        scenario: str,
        features: Mapping[str, float],
        timestamp: float,
        device: str,
        action_name: str,
        user_id: str = DEFAULT_USER_ID,
        guard_reason: str | None = None,
    ) -> AutomationDecision:
        result = self.engine.calculate(scenario, features, user_id)
        confidence = float(result["confidence"])
        threshold = self.config.SCENARIO_THRESHOLDS[scenario]
        action_id = uuid4().hex
        action = None
        if guard_reason is not None:
            outcome = "guarded"
        elif confidence >= threshold:
            outcome = "execute"
            action = AutomationAction(
                action_id=action_id,
                timestamp=timestamp,
                scenario=scenario,
                confidence=confidence,
                device=device,
                action=action_name,
                reason=dict(result["features"]),
            )
        elif confidence >= self.config.MEDIUM_CONFIDENCE_THRESHOLD:
            outcome = "wait_for_more_evidence"
        else:
            outcome = "do_nothing"
        decision = AutomationDecision(
            action_id=action_id,
            timestamp=timestamp,
            user_id=user_id,
            scenario=scenario,
            confidence=confidence,
            threshold=threshold,
            medium_threshold=self.config.MEDIUM_CONFIDENCE_THRESHOLD,
            outcome=outcome,
            features=dict(result["features"]),
            weights=dict(result["weights"]),
            contributions=dict(result["contributions"]),
            action=action,
            guard_reason=guard_reason,
        )
        self.history.save(decision.to_dict())
        return decision

