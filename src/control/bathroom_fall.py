from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import SensingUpdate
from src.control.scenario_config import ScenarioConfig
from src.control.scenario_models import (
    BathroomFallDecision, BathroomFallState as State, FallBackendSignal, ScenarioAction,
)
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
        self._report_authorized = False
        self._emitted: set[str] = set()
        self._actions: list[ScenarioAction] = []

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

    def drain_actions(self) -> list[ScenarioAction]:
        actions = self._actions[:]
        self._actions.clear()
        return actions

    def receive_backend_signal(self, signal: FallBackendSignal) -> BathroomFallDecision:
        if self._last is not None and signal.timestamp < self._last:
            raise ValueError("Backend signal cannot precede the last fall observation")
        if self._active:
            self._report_authorized = signal.allow_emergency_report
            self._emit_staged_actions(signal.timestamp)
        return self._decision(signal.timestamp)

    def update_induction_state(self, timestamp: float, induction_on: bool) -> None:
        """Apply a fresh appliance observation while a fall incident is active."""
        if self._active and induction_on:
            self._emit_once(
                "induction_off", timestamp,
                event="fall_detected", action="turn_off", target="induction",
                reason="Induction is on during an active bathroom fall incident",
            )

    def _emit_once(
        self, key: str, timestamp: float, *, event: str, action: str, target: str,
        reason: str, details: dict | None = None,
    ) -> None:
        if key in self._emitted:
            return
        self._emitted.add(key)
        self._actions.append(ScenarioAction(
            timestamp=timestamp,
            scenario="bathroom_fall",
            event=event,
            action=action,
            target=target,
            reason=reason,
            details=details,
        ))

    def _start_fall_actions(self, timestamp: float, induction_on: bool) -> None:
        self._emitted.clear()
        self._report_authorized = False
        if induction_on:
            self._emit_once(
                "induction_off", timestamp,
                event="fall_detected", action="turn_off", target="induction",
                reason="Induction was on when a bathroom fall was detected",
            )
        self._emit_once(
            "light_blink", timestamp,
            event="fall_detected", action="blink", target="bathroom_light",
            reason="Make the fall alert visible in the bathroom",
        )

    def _emit_staged_actions(self, timestamp: float) -> None:
        c = self.config
        if self._duration >= c.FALL_CONFIRM_SECONDS:
            self._emit_once(
                "user_alert", timestamp,
                event="fall_user_alert_requested", action="notify", target="user",
                reason="No movement after the configured fall confirmation time",
                details={"unresponsive_seconds": self._duration, "stage": 1},
            )
        if self._duration >= c.FALL_WARNING_SECONDS:
            self._emit_once(
                "caregiver_alert", timestamp,
                event="fall_caregiver_alert_requested", action="notify", target="caregiver",
                reason="No movement after the configured caregiver escalation time",
                details={"unresponsive_seconds": self._duration, "stage": 2},
            )
        if self._duration >= c.FALL_EMERGENCY_SECONDS and self._report_authorized:
            self._emit_once(
                "emergency_report", timestamp,
                event="fall_emergency_report_requested", action="report", target="emergency_service",
                reason="Emergency threshold reached and backend authorized automatic reporting",
                details={"unresponsive_seconds": self._duration, "stage": 3},
            )

    def update(self, sample: SensingUpdate, induction_on: bool = False) -> BathroomFallDecision:
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
            self._start_fall_actions(sample.timestamp, induction_on)
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
                self._report_authorized = False
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
        self._emit_staged_actions(sample.timestamp)
        return self._decision(sample.timestamp)
