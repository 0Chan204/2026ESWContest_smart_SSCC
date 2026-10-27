from uuid import uuid4
from collections import deque

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
        self._behavior_valid_until = None
        self._previous_activity = None
        self._still_since = None
        self._moving_since = None
        self._duration = 0.0
        self._uncertain = False
        self._report_authorized = False
        self._incident_id: str | None = None
        self._await_clear = False
        self._resolved_at = None
        self._emitted: set[str] = set()
        self._actions: list[ScenarioAction] = []
        self.backend_response_managed = False
        self._candidate = False
        self._candidate_live = False
        self._candidate_still_since = None
        self._candidate_origin = None
        self._basis = None
        self._evidence = None
        self._last_behavior_at = None
        self._interrupted_at = None
        self._seen_event_ids = deque(maxlen=1000)

    def _interrupt(self) -> None:
        self._still_since = self._moving_since = None
        self._previous_activity = None
        self._uncertain = True
        self._candidate_live = False
        self._candidate_still_since = None

    def tick(self, timestamp: float) -> BathroomFallDecision:
        if (self._last is None or timestamp - self._last >= self.sensing_config.UNKNOWN_TIMEOUT
                or (self._behavior_valid_until is not None and timestamp >= self._behavior_valid_until)):
            self._interrupt()
        # Silence never confirms stillness or recovery, and never clears risk.
        return self._decision(timestamp)

    def interrupt_observation(self, timestamp: float) -> None:
        """Malformed input breaks evidence, but never resolves an existing incident."""
        self._interrupted_at = max(timestamp, self._interrupted_at if self._interrupted_at is not None else timestamp)
        self._interrupt()

    def _decision(self, timestamp: float) -> BathroomFallDecision:
        risk = RiskLevel.NORMAL
        if self.state in {State.FALL_SUSPECTED, State.FALL_CONFIRMED}:
            risk = RiskLevel.WARNING
        elif self.state in {State.FALL_WARNING, State.FALL_EMERGENCY}:
            risk = RiskLevel.HIGH
        return BathroomFallDecision(self.state, risk, timestamp, self._duration,
                                    self._uncertain,
                                    self._duration >= self.config.LONG_UNRESPONSIVE_SECONDS,
                                    self._incident_id, self._candidate and not self._active,
                                    None if self._evidence is None else {
                                        **self._evidence, "basis": self._basis,
                                        "candidate_origin": self._candidate_origin,
                                        "confirm_seconds": self.config.FALL_CONFIRM_SECONDS,
                                        "observed_still_seconds": self._duration,
                                    })

    def drain_actions(self) -> list[ScenarioAction]:
        actions = self._actions[:]
        self._actions.clear()
        return actions

    def receive_backend_signal(self, signal: FallBackendSignal) -> BathroomFallDecision:
        if self._last is not None and signal.timestamp < self._last:
            raise ValueError("Backend signal cannot precede the last fall observation")
        if signal.incident_id is not None and signal.incident_id != self._incident_id:
            raise ValueError("Backend signal incident_id does not match the active fall incident")
        if signal.caregiver_status == "safe" and self._incident_id is not None:
            if not self.backend_response_managed and "caregiver_alert" not in self._emitted:
                raise ValueError("Caregiver response arrived before the caregiver alert request")
            self.state = State.RESOLVED_BY_CAREGIVER
            self._active = False
            self._candidate = self._candidate_live = False
            self._await_clear = True
            self._resolved_at = signal.timestamp
            self._report_authorized = False
            self._still_since = self._moving_since = None
            self._duration = 0.0
            self._actions = [action for action in self._actions if action.event not in {
                "fall_user_alert_requested", "fall_caregiver_alert_requested",
                "fall_emergency_report_requested",
            }]
        elif not self.backend_response_managed and self._active and (signal.caregiver_status == "no_response"
                               or signal.allow_emergency_report):
            if "caregiver_alert" not in self._emitted:
                raise ValueError("Caregiver response arrived before the caregiver alert request")
            self._report_authorized = True
            self._emit_staged_actions(signal.timestamp)
        return self._decision(signal.timestamp)

    def resolve_persisted_incident(self, signal: FallBackendSignal) -> BathroomFallDecision:
        """Close an outbox-validated older incident after process restart."""
        if signal.caregiver_status != "safe" or signal.incident_id is None:
            raise ValueError("Persisted fall resolution requires a confirmed safe response")
        if self._incident_id is not None or self._active:
            raise ValueError("A current fall incident cannot be replaced by a persisted incident")
        if self._last is not None and signal.timestamp < self._last:
            raise ValueError("Backend signal cannot precede the last fall observation")
        self._incident_id = signal.incident_id
        self.state = State.RESOLVED_BY_CAREGIVER
        self._candidate = self._candidate_live = False
        self._await_clear = True
        self._resolved_at = signal.timestamp
        self._report_authorized = False
        self._duration = 0.0
        return self._decision(signal.timestamp)

    def update_induction_state(self, timestamp: float, induction_on: bool) -> None:
        """Apply a fresh appliance observation while a fall incident is active."""
        if self._active and induction_on:
            self._emit_once(
                "induction_off", timestamp,
                event="fall_detected", action="turn_off", target="stove", room="kitchen",
                reason="Stove is on during an active toilet fall incident",
            )

    def _emit_once(
        self, key: str, timestamp: float, *, event: str, action: str, target: str,
        reason: str, details: dict | None = None, room: str | None = None,
    ) -> None:
        if key in self._emitted:
            return
        self._emitted.add(key)
        action_details = {"incident_id": self._incident_id,
                          "evidence": None if self._evidence is None else dict(self._evidence),
                          "basis": self._basis, **(details or {})}
        if self._candidate_origin is not None:
            action_details["candidate_origin"] = dict(self._candidate_origin)
        self._actions.append(ScenarioAction(
            timestamp=timestamp,
            scenario="bathroom_fall",
            event=event,
            action=action,
            target=target,
            reason=reason,
            details=action_details,
            room=room,
        ))

    def _start_fall_actions(self, timestamp: float, induction_on: bool) -> None:
        self._emitted.clear()
        self._report_authorized = False
        self._incident_id = uuid4().hex
        if induction_on:
            self._emit_once(
                "induction_off", timestamp,
                event="fall_detected", action="turn_off", target="stove", room="kitchen",
                reason="Stove was on when a toilet fall was detected",
            )
        self._emit_once(
            "light_blink", timestamp,
            event="fall_detected", action="blink", target="light", room="toilet",
            reason="Make the fall alert visible in the toilet",
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
        if not self.backend_response_managed and self._duration >= c.FALL_WARNING_SECONDS:
            self._emit_once(
                "caregiver_alert", timestamp,
                event="fall_caregiver_alert_requested", action="notify", target="caregiver",
                reason="No movement after the configured caregiver escalation time",
                details={"unresponsive_seconds": self._duration, "stage": 2},
            )
        if not self.backend_response_managed and self._duration >= c.FALL_EMERGENCY_SECONDS and self._report_authorized:
            self._emit_once(
                "emergency_report", timestamp,
                event="fall_emergency_report_requested", action="report", target="emergency_service",
                reason="Emergency threshold reached and caregiver did not respond",
                details={"unresponsive_seconds": self._duration, "stage": 3},
            )

    def update(self, sample: SensingUpdate, induction_on: bool = False) -> BathroomFallDecision:
        observed_at = sample.activity_timestamp if sample.activity_timestamp is not None else sample.timestamp
        if self._behavior_valid_until is not None and observed_at > self._behavior_valid_until:
            self._interrupt()
        self._behavior_valid_until = sample.activity_valid_until
        self.tick(sample.timestamp)
        self._last = sample.timestamp
        if (sample.observation_valid is False or sample.activity_observed is False
                or (sample.activity_valid_until is not None and sample.timestamp >= sample.activity_valid_until)
                or (sample.activity_confidence is not None
                    and sample.activity_confidence < self.sensing_config.MIN_CONFIDENCE)
                or not sample.detected or sample.confidence < self.sensing_config.MIN_CONFIDENCE
                or sample.location != "toilet"):
            self._interrupt()
            return self._decision(sample.timestamp)
        if (self._last_behavior_at is not None and observed_at <= self._last_behavior_at
                or sample.activity_event_id is not None and sample.activity_event_id in self._seen_event_ids):
            return self._decision(sample.timestamp)
        self._last_behavior_at = observed_at
        if sample.activity_event_id is not None:
            self._seen_event_ids.append(sample.activity_event_id)
        self._evidence = {
            "observed_at": observed_at, "received_at": sample.received_at,
            "location_observed_at": sample.timestamp, "location": sample.location,
            "location_confidence": sample.confidence, "location_reason": sample.location_reason,
            "activity": sample.activity, "activity_event": sample.activity_event,
            "activity_event_id": sample.activity_event_id, "raw_activity": sample.raw_activity,
            "activity_confidence": sample.activity_confidence, "activity_reason": sample.activity_reason,
            "fall_detected": sample.fall_detected, "motion_state": sample.motion_state,
            "valid_until": sample.activity_valid_until,
        }
        self._uncertain = False
        if self._await_clear:
            # Only AFTER the backend has confirmed safety: a fresh none window
            # releases the old detection latch, without inventing physical recovery.
            # Otherwise an event-only classifier could never arm for a later fall.
            if (self.backend_response_managed and self._resolved_at is not None
                    and observed_at > self._resolved_at and sample.raw_activity == "none"
                    and sample.activity_event is None and sample.fall_detected is not True):
                self._await_clear = False
                return self._decision(sample.timestamp)
            clear = sample.activity_event not in {"fall", "lie_down"} and (
                sample.fall_detected is False or (self.backend_response_managed and sample.fall_detected is not True
                                                  and sample.activity in {"walking", "standing"}))
            if clear and sample.motion_state == "moving":
                self._await_clear = False
                self._previous_activity = sample.activity
            return self._decision(sample.timestamp)
        explicit = sample.fall_detected is True or sample.activity_event == "fall"
        transition = sample.activity_event is None and (
            self._previous_activity in {"standing", "walking"} and sample.activity == "lying"
        )
        fall = explicit or transition
        self._previous_activity = sample.activity
        if fall and not self._active:
            if not self._candidate:
                self._candidate_origin = None
            self._candidate = self._candidate_live = False
            self._basis = "explicit_fall" if explicit else "observed_posture_transition"
            self._active = True
            self.state = State.FALL_SUSPECTED
            self._duration = 0.0
            self._still_since = self._moving_since = None
            self._start_fall_actions(sample.timestamp, induction_on)
        if not self._active:
            self._update_lying_candidate(sample, observed_at, induction_on)
        if not self._active:
            return self._decision(sample.timestamp)
        c = self.config
        if sample.motion_state == "moving" and not explicit:
            self._still_since = None
            if self._moving_since is None:
                self._moving_since = observed_at
            if observed_at - self._moving_since >= c.RECOVERY_CONFIRM_SECONDS:
                self.state = State.RECOVERED
                self._active = False
                self._duration = 0.0
                self._moving_since = None
                self._report_authorized = False
        elif sample.motion_state == "still":
            self._moving_since = None
            if self._still_since is None:
                self._still_since = observed_at
            duration = observed_at - self._still_since
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

    def _update_lying_candidate(self, sample, observed_at, induction_on):
        """A local suspicion has no incident ID and emits no backend actions.

        Only fresh, distinct, high-confidence observations of stillness across the
        confirmation interval promote it. Repeated lying or silence is insufficient.
        """
        c = self.config
        if self._interrupted_at is not None and observed_at <= self._interrupted_at:
            self._interrupt()
            return
        high_confidence = (sample.confidence >= c.TOILET_LYING_MIN_LOCATION_CONFIDENCE
                           and sample.activity_confidence is not None
                           and sample.activity_confidence >= c.TOILET_LYING_MIN_ACTIVITY_CONFIDENCE)
        if not c.TOILET_LYING_SUSPICION_ENABLED or not high_confidence:
            if self._candidate:
                self._interrupt()
            return
        lying = sample.activity_event == "lie_down" or sample.activity == "lying"
        if lying and (not self._candidate or not self._candidate_live):
            self._candidate = self._candidate_live = True
            self._candidate_still_since = self._moving_since = None
            self._duration = 0.0
            self._incident_id = None
            self._basis = "lying_suspicion"
            self._candidate_origin = dict(self._evidence)
            self.state = State.FALL_SUSPECTED
        if not self._candidate:
            return
        if not self._candidate_live and sample.motion_state != "moving":
            self._uncertain = True
            return
        if sample.motion_state == "moving":
            self._candidate_still_since = None
            self._duration = 0.0
            if self._moving_since is None:
                self._moving_since = observed_at
            if observed_at - self._moving_since >= c.RECOVERY_CONFIRM_SECONDS:
                self._candidate = self._candidate_live = False
                self.state = State.RECOVERED
        elif sample.motion_state == "still":
            self._moving_since = None
            if self._candidate_still_since is None:
                self._candidate_still_since = observed_at
            self._duration = observed_at - self._candidate_still_since
            if self._duration >= c.FALL_CONFIRM_SECONDS:
                self._candidate = self._candidate_live = False
                self._active = True
                self._basis = "lying_with_observed_stillness"
                self._still_since = self._candidate_still_since
                self.state = State.FALL_CONFIRMED
                self._start_fall_actions(sample.timestamp, induction_on)
        else:
            self._candidate_still_since = self._moving_since = None
            self._duration = 0.0
