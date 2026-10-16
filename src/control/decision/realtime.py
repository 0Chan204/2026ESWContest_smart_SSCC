"""Stateful event-time evaluator. Call tick even when no sensor event arrives."""
from collections import deque

from src.control.confidence.config import DEFAULT_USER_ID
from src.control.confidence.decision_service import ConfidenceDecisionService
from src.control.confidence.feature_extractor import FeatureExtractor
from src.control.realtime_config import RealtimeConfig, STATE_OUTPUT
from src.control.realtime_models import (
    ApplianceUpdate, RealtimeDecision, RealtimeState, SensingUpdate, finite,
)


class RealtimeDecisionEngine:
    def __init__(
        self,
        config=None,
        *,
        confidence_service: ConfidenceDecisionService | None = None,
        feature_extractor: FeatureExtractor | None = None,
        user_id: str = DEFAULT_USER_ID,
    ):
        self.config = config or RealtimeConfig()
        self.confidence_service = confidence_service
        self.feature_extractor = feature_extractor
        self.user_id = user_id
        self.current_state = RealtimeState.NORMAL
        self.previous_state = RealtimeState.NORMAL
        self.last_user_location = "unknown"
        self.kitchen_exit_time = None
        self.outside_start_time = None
        self.current_absence_duration = 0.0
        self.last_sensor_update = None
        self.last_appliance_update = None
        self.appliance_operating_duration = 0.0
        self._operating_since = None
        self._candidate = None
        self._candidate_since = None
        self._unknown_since = None
        self._location_since = None
        self._sensing = None
        self._appliance = None
        self._now = None
        self._power_rate = None
        self._temperature_rate = None
        history_size = 5 if feature_extractor is None else feature_extractor.config.SENSOR_HISTORY_SIZE
        self._sensor_history = deque(maxlen=history_size)
        self._homevis_reduced = False
        self._user_override = False
        self.last_confidence_decision = None

    def _validate_time(self, timestamp, last=None):
        finite("timestamp", timestamp)
        if self._now is not None and timestamp < self._now:
            raise ValueError("Events must not precede the last evaluation time")
        if last is not None and timestamp <= last:
            raise ValueError("Each input stream requires strictly increasing timestamps")

    def update_sensing(self, sample: SensingUpdate):
        self._validate_time(sample.timestamp, self.last_sensor_update)
        c = self.config
        if self.last_sensor_update is not None and sample.timestamp - self.last_sensor_update >= c.UNKNOWN_TIMEOUT:
            self._candidate = None
            self.outside_start_time = None
        self._sensing = sample
        self._sensor_history.append((sample.location, sample.confidence, sample.detected))
        self.last_sensor_update = sample.timestamp
        uncertain = not sample.detected or sample.confidence < c.MIN_CONFIDENCE or sample.location == "unknown"
        if uncertain:
            if self._unknown_since is None:
                self._unknown_since = sample.timestamp
            self._candidate = None
            self.outside_start_time = None
        else:
            self._unknown_since = None
            location = sample.location
            if location != self._candidate:
                self._candidate = location
                self._candidate_since = sample.timestamp
                self.outside_start_time = sample.timestamp if location == "outside" else None
            threshold = c.SENSING_CONFIRM_TIME
            if location == "kitchen":
                threshold = max(threshold, c.RETURN_CONFIRM_TIME)
            elif location == "outside":
                threshold = max(threshold, c.OUTSIDE_CONFIRM_TIME)
            elif location == "entrance":
                threshold = max(threshold, c.ENTRANCE_CONFIRM_TIME)
            if sample.timestamp - self._candidate_since >= threshold:
                if location != self.last_user_location:
                    self.last_user_location = location
                    self._location_since = self._candidate_since
                if location == "kitchen":
                    self.kitchen_exit_time = None
                elif self.kitchen_exit_time is None:
                    self.kitchen_exit_time = self._candidate_since
        return self.tick(sample.timestamp)

    def update_appliance(self, sample: ApplianceUpdate):
        self._validate_time(sample.timestamp, self.last_appliance_update)
        old = self._appliance
        self._power_rate = self._temperature_rate = None
        if old is not None and sample.timestamp - old.timestamp < self.config.APPLIANCE_TIMEOUT:
            dt = sample.timestamp - old.timestamp
            if old.power_watts is not None and sample.power_watts is not None:
                self._power_rate = (sample.power_watts - old.power_watts) / dt
            if old.temperature_c is not None and sample.temperature_c is not None:
                self._temperature_rate = (sample.temperature_c - old.temperature_c) / dt
        if sample.active:
            if old is None or not old.active:
                self._operating_since = sample.timestamp
        else:
            self._operating_since = None
        self._appliance = sample
        if sample.control_state == "HOMEVIS_REDUCED":
            self._homevis_reduced = True
            self._user_override = False
        elif sample.control_state == "USER_OVERRIDE":
            self._user_override = True
        elif sample.control_state == "NONE":
            self._homevis_reduced = False
            self._user_override = False
        if not sample.active:
            self._homevis_reduced = False
            self._user_override = False
        self.last_appliance_update = sample.timestamp
        return self.tick(sample.timestamp)

    def tick(self, timestamp):
        self._validate_time(timestamp)
        self._now = timestamp
        c = self.config
        a = self._appliance
        sensor_uncertain = (
            self.last_sensor_update is None
            or timestamp - self.last_sensor_update >= c.UNKNOWN_TIMEOUT
            or (self._unknown_since is not None and timestamp - self._unknown_since >= c.UNKNOWN_TIMEOUT)
            or self.last_user_location == "unknown"
        )
        stale = a is None or timestamp - a.timestamp >= c.APPLIANCE_TIMEOUT
        self.current_absence_duration = 0.0 if self.kitchen_exit_time is None else timestamp - self.kitchen_exit_time
        self.appliance_operating_duration = 0.0 if self._operating_since is None else timestamp - self._operating_since
        high = a is not None and (
            (a.power_watts is not None and a.power_watts >= c.HIGH_POWER_WATTS)
            or (a.temperature_c is not None and a.temperature_c >= c.HIGH_TEMPERATURE_C)
        )
        rising = not stale and (
            (self._power_rate is not None and self._power_rate >= c.RISING_POWER_WATTS_PER_SECOND)
            or (self._temperature_rate is not None and self._temperature_rate >= c.RISING_TEMPERATURE_C_PER_SECOND)
        )
        emergency = a is not None and (a.smoke or a.fire or a.abnormal or (
            not stale and self._temperature_rate is not None
            and self._temperature_rate >= c.RAPID_TEMPERATURE_C_PER_SECOND
        ))
        state, reason = self._classify(sensor_uncertain, stale, high, rising, emergency)
        # Uncertain telemetry cannot silently clear an established warning/danger.
        if (sensor_uncertain or stale) and not (a is not None and not stale and not a.active and not emergency):
            if self.current_state == RealtimeState.DANGER:
                state, reason = "DANGER", "기존 위험 상태에서 데이터가 불확실하여 위험을 유지함"
            elif self.current_state == RealtimeState.WARNING and state == "SENSOR_UNCERTAIN":
                state, reason = "WARNING", "기존 경고 상태에서 데이터가 불확실하여 경고를 유지함"
        if state == "NORMAL" and self.current_state in {RealtimeState.WARNING, RealtimeState.DANGER}:
            state, reason = "RECOVERED", "주방 복귀 또는 조리기기 종료로 위험 상태가 해제됨"
        self.previous_state = self.current_state
        self.current_state = RealtimeState(state)
        score, action, _ = STATE_OUTPUT[state]
        confidence_decision = self._evaluate_automation(
            timestamp, sensor_uncertain=sensor_uncertain, appliance_stale=stale
        )
        return RealtimeDecision(
            self.current_state, self.previous_state, reason, self.last_user_location,
            self.current_absence_duration, None if a is None else a.active,
            score, action, timestamp, sensor_uncertain, stale,
            None if a is None else a.power_watts, None if a is None else a.temperature_c,
            None if stale else self._power_rate, None if stale else self._temperature_rate,
            None if confidence_decision is None else confidence_decision.to_dict(),
        )

    def _evaluate_automation(self, timestamp, *, sensor_uncertain, appliance_stale):
        service, extractor, sensing, appliance = (
            self.confidence_service, self.feature_extractor, self._sensing, self._appliance
        )
        if service is None or extractor is None or sensing is None or appliance is None:
            self.last_confidence_decision = None
            return None
        if self.last_user_location == "kitchen" and self._homevis_reduced:
            scenario = "kitchen_return_restore"
            consistency = extractor.sensor_consistency(self._sensor_history, "kitchen")
            return_duration = 0.0 if self._location_since is None else timestamp - self._location_since
            features = extractor.kitchen_return(
                location_confidence=0.0 if sensor_uncertain else sensing.confidence,
                return_duration=return_duration,
                sensor_consistency=consistency,
                stove_on=appliance.active,
                homevis_reduced=self._homevis_reduced,
                feedback_score=service.feedback_score(self.user_id, scenario),
            )
            guard = None
            if not appliance.active:
                guard = "stove_off"
            elif self._user_override or appliance.control_state == "USER_OVERRIDE":
                guard = "user_override"
            decision = service.score(
                scenario=scenario, features=features, timestamp=timestamp,
                device="stove", action_name="restore_power", user_id=self.user_id,
                guard_reason=guard,
            )
            if decision.action is not None:
                self._homevis_reduced = False
            self.last_confidence_decision = decision
            return decision
        if self.last_user_location in {"unknown", "kitchen"}:
            self.last_confidence_decision = None
            return None
        scenario = "kitchen_leave_reduce_power"
        consistency = extractor.sensor_consistency(self._sensor_history, self.last_user_location)
        features = extractor.kitchen_leave(
            location_confidence=0.0 if sensor_uncertain else sensing.confidence,
            activity_confidence=(sensing.confidence if sensing.activity_confidence is None
                                 else sensing.activity_confidence),
            leave_duration=self.current_absence_duration,
            current_stove_power=appliance.power_watts,
            outside_home=self.last_user_location == "outside",
            sensor_consistency=consistency,
            previous_homevis_action=self._homevis_reduced,
            feedback_score=service.feedback_score(self.user_id, scenario),
        )
        guard = None
        if not appliance.active:
            guard = "stove_off"
        elif appliance_stale:
            guard = "appliance_stale"
        elif self._homevis_reduced:
            guard = "already_reduced"
        decision = service.score(
            scenario=scenario, features=features, timestamp=timestamp,
            device="stove", action_name="reduce_power", user_id=self.user_id,
            guard_reason=guard,
        )
        if decision.action is not None:
            self._homevis_reduced = True
        self.last_confidence_decision = decision
        return decision

    def _classify(self, uncertain, stale, high, rising, emergency):
        a, c = self._appliance, self.config
        if emergency:
            return "DANGER", "연기·화재·기기 이상 또는 급격한 온도 상승이 감지됨"
        if a is not None and not stale and not a.active:
            return "NORMAL", "조리기기가 종료됨"
        if a is not None and a.active:
            if self.last_user_location == "outside":
                return "DANGER", "집 밖 이탈이 확인되었지만 조리기기가 계속 동작 중임"
            if self.current_absence_duration >= c.KITCHEN_DANGER_TIME:
                return "DANGER", "조리기기 동작 중 주방 장시간 이탈 기준에 도달함"
        if uncertain or stale:
            if a is not None and a.active and high:
                return "WARNING", "센싱 또는 기기 데이터가 불확실하며 마지막 기기 출력/온도가 높음"
            return "SENSOR_UNCERTAIN", "센싱 또는 조리기기 데이터가 없거나 불확실함"
        if self.last_user_location == "kitchen":
            return "NORMAL", "사용자가 주방에 있으며 긴급 위험 신호가 없음"
        if self.last_user_location == "entrance":
            return "WARNING", "현관 체류가 확인되었으며 조리기기가 동작 중임"
        duration = self.current_absence_duration
        reason = f"사용자가 주방을 {duration:g}초 동안 이탈했지만 조리기기가 계속 동작 중임"
        if duration >= c.KITCHEN_WARNING_TIME:
            return ("DANGER" if high and rising else "WARNING"), reason
        if duration >= c.KITCHEN_SHORT_ABSENCE:
            return ("WARNING" if high and rising else "CAUTION"), reason
        return "TEMPORARY_ABSENCE", reason
