from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path
from statistics import median

from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import SensingUpdate
from src.control.scenario_config import ScenarioConfig
from src.control.scenario_models import DeviceCommand, MorningWaterState as State


class MorningWaterScenario:
    """Learn wake-to-kitchen times and reserve the daily allowance on command emission."""

    def __init__(
        self,
        config: ScenarioConfig,
        sensing_config: RealtimeConfig,
        history_path: str | Path | None = None,
        user_id: str = "default",
    ) -> None:
        self.config = config
        self.sensing_config = sensing_config
        self.history_path = Path(history_path) if history_path is not None else None
        self.user_id = user_id
        self.state = State.IDLE
        self.morning_water_dispensed = False
        self.dispense_count = 0
        self.reserve_allowance = None  # Optional durable reservation hook, before command emission.
        self._date: date | None = None
        self._last: float | None = None
        self._behavior_valid_until: float | None = None
        self._wake_candidate: float | None = None
        self._wake_time: float | None = None
        self._kitchen_since: float | None = None
        self._event_eligible: bool | None = None
        self._wake_records: list[tuple[date, float]] = []
        self._load_history()

    @property
    def wake_history(self) -> list[float]:
        size = self.config.WAKE_PATTERN_HISTORY_SIZE
        return [timestamp for _, timestamp in self._wake_records[-size:]]

    @property
    def uses_learned_wake_window(self) -> bool:
        return len(self.wake_history) >= self.config.WAKE_PATTERN_MIN_SAMPLES

    def current_wake_window(self) -> tuple[time, time]:
        """Return the active local-time window; the fixed range is bootstrap-only."""
        if not self.uses_learned_wake_window:
            return self.config.MORNING_START, self.config.MORNING_END
        seconds = [self._local_seconds(timestamp) for timestamp in self.wake_history]
        center = median(seconds)
        spread = max(center - min(seconds), max(seconds) - center)
        half_width = spread + self.config.WAKE_WINDOW_MARGIN_SECONDS
        start = max(0.0, center - half_width)
        end = min(24 * 3600 - 1, center + half_width)
        return self._seconds_to_time(start), self._seconds_to_time(end)

    def _local_datetime(self, timestamp: float) -> datetime:
        zone = timezone(timedelta(hours=self.config.UTC_OFFSET_HOURS))
        return datetime.fromtimestamp(timestamp, zone)

    def _local_seconds(self, timestamp: float) -> float:
        local = self._local_datetime(timestamp)
        return local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1_000_000

    @staticmethod
    def _time_seconds(value: time) -> float:
        return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000

    @staticmethod
    def _seconds_to_time(value: float) -> time:
        whole = int(value)
        return time(whole // 3600, (whole % 3600) // 60, whole % 60)

    def _in_time_range(self, timestamp: float, start: time, end: time) -> bool:
        seconds = self._local_seconds(timestamp)
        return self._time_seconds(start) <= seconds < self._time_seconds(end)

    def _in_dispense_window(self, timestamp: float) -> bool:
        start, end = self.current_wake_window()
        return self._in_time_range(timestamp, start, end)

    def _in_record_window(self, timestamp: float) -> bool:
        return self._in_time_range(
            timestamp, self.config.WAKE_RECORD_START, self.config.WAKE_RECORD_END
        )

    def _load_history(self) -> None:
        if self.history_path is None or not self.history_path.exists():
            return
        records_by_date: dict[date, float] = {}
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                timestamp = float(record["timestamp"])
                local_date = date.fromisoformat(record["local_date"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            if record.get("user_id", "default") != self.user_id or not isfinite(timestamp):
                continue
            records_by_date[local_date] = timestamp
        self._wake_records = sorted(records_by_date.items())

    def _record_wake_time(self, timestamp: float) -> None:
        if not self._in_record_window(timestamp):
            return
        local_date = self._local_datetime(timestamp).date()
        if any(record_date == local_date for record_date, _ in self._wake_records):
            return
        self._wake_records.append((local_date, timestamp))
        self._wake_records.sort()
        if self.history_path is not None:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "user_id": self.user_id,
                    "local_date": local_date.isoformat(),
                    "timestamp": timestamp,
                    "seconds_of_day": self._local_seconds(timestamp),
                }, ensure_ascii=False) + "\n")

    def _reset_event(self) -> None:
        self.state = State.IDLE
        self._wake_candidate = self._wake_time = self._kitchen_since = None
        self._event_eligible = None

    def tick(self, timestamp: float) -> None:
        local = self._local_datetime(timestamp)
        if local.date() != self._date:
            self._date = local.date()
            self.dispense_count = 0
            self.morning_water_dispensed = False
        if (self._wake_time is not None
                and timestamp - self._wake_time >= self.config.WAKE_TO_KITCHEN_TIMEOUT_SECONDS):
            self._reset_event()
        if self._last is not None and timestamp - self._last >= self.sensing_config.UNKNOWN_TIMEOUT:
            self._wake_candidate = self._kitchen_since = None
            if self._wake_time is None:
                self.state = State.IDLE
        if self._behavior_valid_until is not None and timestamp >= self._behavior_valid_until:
            self._wake_candidate = self._kitchen_since = None
            if self._wake_time is None:
                self.state = State.IDLE

    def update(self, sample: SensingUpdate, available: bool) -> DeviceCommand | None:
        observed_at = sample.activity_timestamp if sample.activity_timestamp is not None else sample.timestamp
        if self._behavior_valid_until is not None and observed_at > self._behavior_valid_until:
            self._wake_candidate = self._kitchen_since = None
            if self._wake_time is None:
                self.state = State.IDLE
        self._behavior_valid_until = sample.activity_valid_until
        self.tick(sample.timestamp)
        self._last = sample.timestamp
        c = self.config
        if (sample.observation_valid is False or sample.activity_observed is False
                or (sample.activity_valid_until is not None and sample.timestamp >= sample.activity_valid_until)
                or (sample.activity_confidence is not None
                    and sample.activity_confidence < self.sensing_config.MIN_CONFIDENCE)
                or not sample.detected or sample.confidence < self.sensing_config.MIN_CONFIDENCE
                or sample.location == "unknown"):
            if sample.activity_observed is False:
                self._reset_event()
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
                    self._wake_candidate = observed_at
                if observed_at - self._wake_candidate >= c.WAKE_CONFIRM_SECONDS:
                    self._wake_time = observed_at
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
        if sample.timestamp - self._kitchen_since < c.KITCHEN_CONFIRM_SECONDS:
            return None
        if self._event_eligible is None:
            # Decide against previous days first, then add today's observation for adaptation.
            self._event_eligible = self._in_dispense_window(self._kitchen_since)
            self._record_wake_time(self._kitchen_since)
        if not self._event_eligible:
            self._reset_event()
            return None
        if not available or self.dispense_count >= c.MAX_MORNING_AUTO_DISPENSE:
            return None
        self.state = State.WATER_DISPENSE_REQUEST
        if self.reserve_allowance is not None:
            self.reserve_allowance(str(self._date), self.dispense_count + 1)
        self.dispense_count += 1
        self.morning_water_dispensed = True
        self._wake_time = self._kitchen_since = None
        self._event_eligible = None
        return DeviceCommand(sample.timestamp, c.MORNING_WATER_AMOUNT_ML)
