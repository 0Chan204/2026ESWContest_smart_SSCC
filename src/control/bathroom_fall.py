from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import SensingUpdate
from src.control.scenario_config import ScenarioConfig
from src.control.scenario_models import BathroomFallDecision, BathroomFallState as State
from src.models import RiskLevel


class BathroomFallScenario:
    def __init__(self, config: ScenarioConfig, sensing_config: RealtimeConfig) -> None:
        self.config = config
        self.sensing_config = sensing_config
        self.state = State.NORMAL_BATHROOM_USE
        self._active = False
        self._last = None
        self._previous_activity = None
        self._still_since = None
        self._moving_since = None
        self._duration = 0.0
        self._uncertain = False

    def _interrupt(self) -> None:
        self._still_since = self._moving_since = None
        self._previous_activity = None
        self._uncertain = True

    def tick(self, timestamp: float) -> BathroomFallDecision:
        if self._last is None or timestamp - self._last >= self.sensing_config.UNKNOWN_TIMEOUT:
            self._interrupt()
        # Silence never confirms stillness or recovery, and never clears risk.
        return self._decision(timestamp)

    def _decision(self, timestamp: float) -> BathroomFallDecision:
        risk = RiskLevel.NORMAL
        if self.state in {State.FALL_SUSPECTED, State.FALL_CONFIRMED}:
            risk = RiskLevel.WARNING
        elif self.state in {State.FALL_WARNING, State.FALL_EMERGENCY}:
            risk = RiskLevel.HIGH
        return BathroomFallDecision(self.state, risk, timestamp, self._duration,
                                    self._uncertain,
                                    self._duration >= self.config.LONG_UNRESPONSIVE_SECONDS)

    def update(self, sample: SensingUpdate) -> BathroomFallDecision:
        self.tick(sample.timestamp)
        self._last = sample.timestamp
        if (not sample.detected or sample.confidence < self.sensing_config.MIN_CONFIDENCE
                or sample.location != "bathroom"):
            self._interrupt()
            return self._decision(sample.timestamp)
        self._uncertain = False
        fall = sample.fall_detected is True or (
            self._previous_activity in {"standing", "walking"} and sample.activity == "lying"
        )
        self._previous_activity = sample.activity
        if fall and not self._active:
            self._active = True
            self.state = State.FALL_SUSPECTED
            self._duration = 0.0
            self._still_since = self._moving_since = None
        if not self._active:
            return self._decision(sample.timestamp)
        c = self.config
        if sample.motion_state == "moving" and sample.fall_detected is not True:
            self._still_since = None
            if self._moving_since is None:
                self._moving_since = sample.timestamp
            if sample.timestamp - self._moving_since >= c.RECOVERY_CONFIRM_SECONDS:
                self.state = State.RECOVERED
                self._active = False
                self._duration = 0.0
                self._moving_since = None
        elif sample.motion_state == "still":
            self._moving_since = None
            if self._still_since is None:
                self._still_since = sample.timestamp
            duration = sample.timestamp - self._still_since
            self._duration = max(self._duration, duration)
            if duration >= c.FALL_EMERGENCY_SECONDS:
                self.state = State.FALL_EMERGENCY
            elif duration >= c.FALL_WARNING_SECONDS and self.state != State.FALL_EMERGENCY:
                self.state = State.FALL_WARNING
            elif duration >= c.FALL_CONFIRM_SECONDS and self.state == State.FALL_SUSPECTED:
                self.state = State.FALL_CONFIRMED
        else:
            self._still_since = self._moving_since = None
        return self._decision(sample.timestamp)
