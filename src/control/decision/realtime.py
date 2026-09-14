"""Stateful event-time evaluator. Call tick even when no sensor event arrives."""
from src.control.realtime_config import RealtimeConfig, STATE_OUTPUT
from src.control.realtime_models import (
    ApplianceUpdate, RealtimeDecision, RealtimeState, SensingUpdate, finite,
)


class RealtimeDecisionEngine:
    def __init__(self, config=None):
        self.config = config or RealtimeConfig()
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
        self.last_sensor_update = sample.timestamp
        uncertain = sample.confidence < c.MIN_CONFIDENCE or (sample.detected and sample.location == "unknown")
        if uncertain:
            if self._unknown_since is None:
                self._unknown_since = sample.timestamp
            self._candidate = None
            self.outside_start_time = None
        else:
            self._unknown_since = None
            location = sample.location if sample.detected else "outside"
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
        return RealtimeDecision(
            self.current_state, self.previous_state, reason, self.last_user_location,
            self.current_absence_duration, None if a is None else a.active,
            score, action, timestamp, sensor_uncertain, stale,
            None if a is None else a.power_watts, None if a is None else a.temperature_c,
            None if stale else self._power_rate, None if stale else self._temperature_rate,
        )

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
