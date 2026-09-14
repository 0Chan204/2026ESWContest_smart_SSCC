from __future__ import annotations

from src.control.decision.base import DecisionEngine
from src.control.decision.rule_based import RuleBasedDecisionEngine
from src.control.models import ControlDecision, DeviceState, SensingState
from src.control.decision.realtime import RealtimeDecisionEngine
from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import ApplianceUpdate, SensingUpdate, RealtimeDecision


class CentralController:
    def __init__(self, engine: DecisionEngine | None = None, *, config: RealtimeConfig | None = None) -> None:
        self.engine = engine or RuleBasedDecisionEngine()
        self.realtime_engine = RealtimeDecisionEngine(config)

    def evaluate(self, sensing: SensingState, device: DeviceState) -> ControlDecision:
        return self.engine.predict(sensing, device)

    def update_sensing(self, sample: SensingUpdate) -> RealtimeDecision:
        return self.realtime_engine.update_sensing(sample)

    def update_appliance(self, sample: ApplianceUpdate) -> RealtimeDecision:
        return self.realtime_engine.update_appliance(sample)

    def tick(self, timestamp: float) -> RealtimeDecision:
        return self.realtime_engine.tick(timestamp)
