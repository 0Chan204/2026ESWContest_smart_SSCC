from __future__ import annotations

from pathlib import Path

from src.control.automation_models import AutomationAction, AutomationDecision, LightContext
from src.control.confidence import (
    ConfidenceConfig, ConfidenceDecisionService, ConfidenceEngine,
    DecisionHistoryStorage, FeatureExtractor, WeightManager,
)
from src.control.confidence.config import DEFAULT_USER_ID
from src.control.decision.base import DecisionEngine
from src.control.decision.rule_based import RuleBasedDecisionEngine
from src.control.models import ControlDecision, DeviceState, SensingState
from src.control.decision.realtime import RealtimeDecisionEngine
from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import ApplianceUpdate, SensingUpdate, RealtimeDecision
from src.control.scenario_config import ScenarioConfig
from src.control.morning_water import MorningWaterScenario
from src.control.bathroom_fall import BathroomFallScenario
from src.control.bedtime_light import BedtimeLightScenario
from src.control.scenario_models import (
    BathroomFallDecision, DeviceCommand, FallBackendSignal, ScenarioAction,
)
from src.control.feedback import (
    FeedbackManager, FeedbackStorage, NaturalLanguageFeedbackInterpreter,
    NaturalLanguageFeedbackService,
)
from src.control.routine import RoutineManager, RoutineStorage
from src.llm.adapters.base import BaseLLMAdapter


class CentralController:
    def __init__(self, engine: DecisionEngine | None = None, *, config: RealtimeConfig | None = None,
                 scenario_config: ScenarioConfig | None = None,
                 water_dispenser_available: bool = False,
                 confidence_config: ConfidenceConfig | None = None,
                 confidence_data_dir: str | Path | None = None,
                 feedback_llm: BaseLLMAdapter | None = None,
                 user_id: str = DEFAULT_USER_ID) -> None:
        self.engine = engine or RuleBasedDecisionEngine()
        self.user_id = user_id
        confidence_config = confidence_config or ConfidenceConfig()
        data_dir = (Path(confidence_data_dir) if confidence_data_dir is not None else
                    Path(__file__).resolve().parents[2] / "output" / "confidence")
        self.weight_manager = WeightManager(confidence_config, data_dir / "user_weights.json")
        self.decision_history = DecisionHistoryStorage(data_dir / "decision_history.jsonl")
        self.feedback_storage = FeedbackStorage(data_dir / "feedback.jsonl")
        self.feedback_manager = FeedbackManager(
            self.decision_history, self.weight_manager, self.feedback_storage
        )
        self.feedback_interpreter = NaturalLanguageFeedbackInterpreter(feedback_llm)
        self.natural_language_feedback_service = NaturalLanguageFeedbackService(
            self.feedback_interpreter,
            self.decision_history,
            self.feedback_manager,
            self.feedback_storage,
            confidence_config,
        )
        self.confidence_engine = ConfidenceEngine(self.weight_manager)
        self.feature_extractor = FeatureExtractor(confidence_config)
        self.confidence_service = ConfidenceDecisionService(
            self.confidence_engine,
            self.decision_history,
            confidence_config,
            self.feedback_manager.feedback_score,
        )
        self.routine_manager = RoutineManager(RoutineStorage(data_dir / "routines.jsonl"))
        self.realtime_engine = RealtimeDecisionEngine(
            config,
            confidence_service=self.confidence_service,
            feature_extractor=self.feature_extractor,
            user_id=user_id,
        )
        scenarios = scenario_config or ScenarioConfig()
        self.morning_water = MorningWaterScenario(
            scenarios, self.realtime_engine.config, data_dir / "wake_times.jsonl", user_id
        )
        self.bedtime_light = BedtimeLightScenario(scenarios, self.realtime_engine.config)
        self.bathroom_fall = BathroomFallScenario(scenarios, self.realtime_engine.config)
        self.bathroom_decision = None
        self.water_dispenser_available = water_dispenser_available
        self.device_commands: list[DeviceCommand] = []
        self.scenario_actions: list[ScenarioAction] = []
        self.automation_actions: list[AutomationAction] = []
        self._last_induction_update: ApplianceUpdate | None = None

    def evaluate(self, sensing: SensingState, device: DeviceState) -> ControlDecision:
        return self.engine.predict(sensing, device)

    def update_sensing(self, sample: SensingUpdate) -> RealtimeDecision:
        decision = self.realtime_engine.update_sensing(sample)
        self.routine_manager.record(
            timestamp=sample.timestamp,
            location=sample.location,
            activity=sample.activity,
            confidence=sample.confidence,
            user_id=self.user_id,
        )
        self._collect_automation(decision)
        command = self.morning_water.update(sample, self.water_dispenser_available)
        if command is not None:
            self.device_commands.append(command)
            self.routine_manager.record(
                timestamp=sample.timestamp,
                location=sample.location,
                activity=sample.activity,
                confidence=sample.confidence,
                device=command.device,
                action=command.command_type,
                user_id=self.user_id,
            )
        bedtime_action = self.bedtime_light.update(sample)
        if bedtime_action is not None:
            self.scenario_actions.append(bedtime_action)
        self.bathroom_decision = self.bathroom_fall.update(
            sample, induction_on=self._induction_is_on(sample.timestamp)
        )
        self.scenario_actions.extend(self.bathroom_fall.drain_actions())
        return decision

    def update_appliance(self, sample: ApplianceUpdate) -> RealtimeDecision:
        decision = self.realtime_engine.update_appliance(sample)
        self._last_induction_update = sample
        self.bathroom_fall.update_induction_state(sample.timestamp, sample.active)
        self._collect_automation(decision)
        self._tick_scenarios(sample.timestamp)
        return decision

    def tick(self, timestamp: float) -> RealtimeDecision:
        decision = self.realtime_engine.tick(timestamp)
        self._collect_automation(decision)
        self._tick_scenarios(timestamp)
        return decision

    def _tick_scenarios(self, timestamp: float) -> None:
        self.morning_water.tick(timestamp)
        bedtime_action = self.bedtime_light.tick(timestamp)
        if bedtime_action is not None:
            self.scenario_actions.append(bedtime_action)
        self.bathroom_decision = self.bathroom_fall.tick(timestamp)
        self.scenario_actions.extend(self.bathroom_fall.drain_actions())

    def _induction_is_on(self, timestamp: float) -> bool:
        sample = self._last_induction_update
        return bool(
            sample is not None
            and sample.active
            and timestamp - sample.timestamp < self.realtime_engine.config.APPLIANCE_TIMEOUT
        )

    def update_fall_backend_signal(self, signal: FallBackendSignal) -> BathroomFallDecision:
        self.bathroom_decision = self.bathroom_fall.receive_backend_signal(signal)
        self.scenario_actions.extend(self.bathroom_fall.drain_actions())
        return self.bathroom_decision

    def drain_device_commands(self) -> list[DeviceCommand]:
        commands = self.device_commands[:]
        self.device_commands.clear()
        return commands

    def drain_scenario_actions(self) -> list[ScenarioAction]:
        actions = self.scenario_actions[:]
        self.scenario_actions.clear()
        return actions

    def drain_backend_requests(self) -> list[DeviceCommand | ScenarioAction]:
        """Drain all rule-based scenario output in timestamp order."""
        requests: list[DeviceCommand | ScenarioAction] = [
            *self.drain_device_commands(), *self.drain_scenario_actions()
        ]
        return sorted(requests, key=lambda request: request.timestamp)

    def _collect_automation(self, decision: RealtimeDecision) -> None:
        scored = self.realtime_engine.last_confidence_decision
        if scored is None or scored.action is None:
            return
        self.automation_actions.append(scored.action)
        self.routine_manager.record(
            timestamp=scored.timestamp,
            location=decision.user_location,
            activity=None,
            confidence=scored.confidence,
            device=scored.action.device,
            action=scored.action.action,
            user_id=self.user_id,
        )

    def drain_automation_actions(self) -> list[AutomationAction]:
        actions = self.automation_actions[:]
        self.automation_actions.clear()
        return actions

    # Alias for backends that already call all device operations "commands".
    drain_control_actions = drain_automation_actions

    def apply_feedback(
        self, action_id: str, feedback: str, *, user_id: str | None = None
    ) -> dict:
        return self.feedback_manager.apply_feedback(action_id, feedback, user_id)

    def apply_natural_language_feedback(
        self,
        action_id: str | None,
        user_text: str,
        *,
        user_id: str | None = None,
    ) -> dict:
        return self.natural_language_feedback_service.apply_natural_language_feedback(
            action_id, user_text, user_id
        )

    def evaluate_light(
        self, context: LightContext, *, user_id: str | None = None
    ) -> AutomationDecision:
        target_user = user_id or self.user_id
        scenario, features = self.feature_extractor.light(
            context, self.feedback_manager.feedback_score(target_user, (
                "light_auto_on" if context.user_present else "light_auto_off"
            ))
        )
        if scenario == "light_auto_on":
            device_action = "turn_on"
            guard = "already_on" if context.light_on else None
        else:
            device_action = "turn_off"
            guard = "already_off" if not context.light_on else None
        decision = self.confidence_service.score(
            scenario=scenario,
            features=features,
            timestamp=context.timestamp,
            device=f"{context.room}_light",
            action_name=device_action,
            user_id=target_user,
            guard_reason=guard,
        )
        if decision.action is not None:
            self.automation_actions.append(decision.action)
            self.routine_manager.record(
                timestamp=context.timestamp,
                location=context.room,
                activity=None,
                confidence=decision.confidence,
                device=decision.action.device,
                action=decision.action.action,
                user_id=target_user,
            )
        return decision
