from __future__ import annotations

from src.control.decision.base import DecisionEngine
from src.control.decision.rule_based import RuleBasedDecisionEngine
from src.control.models import ControlDecision, DeviceState, SensingState
from src.control.decision.realtime import RealtimeDecisionEngine
from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import ApplianceUpdate, SensingUpdate, RealtimeDecision
from src.control.scenario_config import ScenarioConfig
from src.control.morning_water import MorningWaterScenario
from src.control.bathroom_fall import BathroomFallScenario
from src.control.scenario_models import DeviceCommand


class CentralController:
    def __init__(self, engine: DecisionEngine | None = None, *, config: RealtimeConfig | None = None,
                 scenario_config: ScenarioConfig | None = None,
                 water_dispenser_available: bool = False) -> None:
        self.engine = engine or RuleBasedDecisionEngine()
        self.realtime_engine = RealtimeDecisionEngine(config)
        scenarios = scenario_config or ScenarioConfig()
        self.morning_water = MorningWaterScenario(scenarios, self.realtime_engine.config)
        self.bathroom_fall = BathroomFallScenario(scenarios, self.realtime_engine.config)
        self.bathroom_decision = None
        self.water_dispenser_available = water_dispenser_available
        self.device_commands: list[DeviceCommand] = []

    def evaluate(self, sensing: SensingState, device: DeviceState) -> ControlDecision:
        return self.engine.predict(sensing, device)

    def update_sensing(self, sample: SensingUpdate) -> RealtimeDecision:
        decision = self.realtime_engine.update_sensing(sample)
        command = self.morning_water.update(sample, self.water_dispenser_available)
        if command is not None:
            self.device_commands.append(command)
        self.bathroom_decision = self.bathroom_fall.update(sample)
        return decision

    def update_appliance(self, sample: ApplianceUpdate) -> RealtimeDecision:
        decision = self.realtime_engine.update_appliance(sample)
        self._tick_scenarios(sample.timestamp)
        return decision

    def tick(self, timestamp: float) -> RealtimeDecision:
        decision = self.realtime_engine.tick(timestamp)
        self._tick_scenarios(timestamp)
        return decision

    def _tick_scenarios(self, timestamp: float) -> None:
        self.morning_water.tick(timestamp)
        self.bathroom_decision = self.bathroom_fall.tick(timestamp)

    def drain_device_commands(self) -> list[DeviceCommand]:
        commands = self.device_commands[:]
        self.device_commands.clear()
        return commands
