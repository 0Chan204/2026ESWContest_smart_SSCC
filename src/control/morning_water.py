from datetime import datetime, timedelta, timezone

from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import SensingUpdate
from src.control.scenario_config import ScenarioConfig
from src.control.scenario_models import DeviceCommand, MorningWaterState as State


class MorningWaterScenario:
    """Reserve the daily allowance when emitting a command; no hardware success is assumed."""

    def __init__(self, config: ScenarioConfig, sensing_config: RealtimeConfig) -> None:
        self.config = config
        self.sensing_config = sensing_config
        self.state = State.IDLE
        self.morning_water_dispensed = False
        self.dispense_count = 0
        self._date = None
        self._last = None
        self._wake_candidate = None
        self._wake_time = None
        self._kitchen_since = None

    def _reset_event(self) -> None:
        self.state = State.IDLE
        self._wake_candidate = self._wake_time = self._kitchen_since = None

    def tick(self, timestamp: float) -> None:
        c = self.config
        local = datetime.fromtimestamp(timestamp, timezone(timedelta(hours=c.UTC_OFFSET_HOURS)))
        if local.date() != self._date:
            self._date = local.date()
            self.dispense_count = 0
            self.morning_water_dispensed = False
            self._reset_event()
        if not c.MORNING_START <= local.time() < c.MORNING_END:
            self._reset_event()
        if self._wake_time is not None and timestamp - self._wake_time >= c.WAKE_TO_KITCHEN_TIMEOUT_SECONDS:
            self._reset_event()
        if self._last is not None and timestamp - self._last >= self.sensing_config.UNKNOWN_TIMEOUT:
            self._wake_candidate = self._kitchen_since = None
            if self._wake_time is None:
                self.state = State.IDLE

    def update(self, sample: SensingUpdate, available: bool) -> DeviceCommand | None:
        self.tick(sample.timestamp)
        self._last = sample.timestamp
        c = self.config
        local = datetime.fromtimestamp(sample.timestamp, timezone(timedelta(hours=c.UTC_OFFSET_HOURS)))
        if not c.MORNING_START <= local.time() < c.MORNING_END or self.dispense_count >= c.MAX_MORNING_AUTO_DISPENSE:
            return None
        if not sample.detected or sample.confidence < self.sensing_config.MIN_CONFIDENCE or sample.location == "unknown":
            self._wake_candidate = self._kitchen_since = None
            if self._wake_time is None:
                self.state = State.IDLE
            return None
        if self._wake_time is None:
            if sample.location == "bedroom" and sample.activity == "lying":
                self.state = State.SLEEPING
                self._wake_candidate = None
            elif (self.state == State.SLEEPING and sample.location == "bedroom"
                  and sample.activity in {"sitting", "standing", "walking"}):
                if self._wake_candidate is None:
                    self._wake_candidate = sample.timestamp
                if sample.timestamp - self._wake_candidate >= c.WAKE_CONFIRM_SECONDS:
                    self._wake_time = sample.timestamp
                    self.state = State.WAKE_UP_DETECTED
            else:
                self._reset_event()
            return None
        if sample.location != "kitchen":
            self._kitchen_since = None
            self.state = State.MORNING_MOVING
            return None
        if self._kitchen_since is None:
            self._kitchen_since = sample.timestamp
        self.state = State.MORNING_KITCHEN_ENTRY
        if sample.timestamp - self._kitchen_since < c.KITCHEN_CONFIRM_SECONDS or not available:
            return None
        self.state = State.WATER_DISPENSE_REQUEST
        self.dispense_count += 1
        self.morning_water_dispensed = True
        self._wake_time = self._kitchen_since = None
        return DeviceCommand(sample.timestamp, c.MORNING_WATER_AMOUNT_ML)
