from __future__ import annotations

from src.control.decision.base import DecisionEngine
from src.control.decision.rule_based import RuleBasedDecisionEngine
from src.control.models import ControlDecision, DeviceState, SensingState


class CentralController:
    def __init__(self, engine: DecisionEngine | None = None) -> None:
        self.engine = engine or RuleBasedDecisionEngine()

    def evaluate(self, sensing: SensingState, device: DeviceState) -> ControlDecision:
        return self.engine.predict(sensing, device)
