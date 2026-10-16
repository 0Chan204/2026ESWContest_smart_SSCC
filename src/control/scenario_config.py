"""Scenario thresholds in seconds; timestamps are Unix seconds in configured local time."""
from dataclasses import dataclass
from datetime import time
from math import isfinite


@dataclass(frozen=True)
class ScenarioConfig:
    # Used only until enough wake-pattern samples have been collected.
    MORNING_START: time = time(6)
    MORNING_END: time = time(10)
    WAKE_RECORD_START: time = time(3)
    WAKE_RECORD_END: time = time(13)
    UTC_OFFSET_HOURS: float = 9
    WAKE_CONFIRM_SECONDS: float = 5
    KITCHEN_CONFIRM_SECONDS: float = 5
    WAKE_TO_KITCHEN_TIMEOUT_SECONDS: float = 1800
    WAKE_PATTERN_MIN_SAMPLES: int = 3
    WAKE_PATTERN_HISTORY_SIZE: int = 14
    WAKE_WINDOW_MARGIN_SECONDS: float = 1800
    MORNING_WATER_AMOUNT_ML: int = 250
    MAX_MORNING_AUTO_DISPENSE: int = 1
    BEDTIME_LYING_SECONDS: float = 600
    FALL_CONFIRM_SECONDS: float = 5
    FALL_WARNING_SECONDS: float = 10
    FALL_EMERGENCY_SECONDS: float = 30
    LONG_UNRESPONSIVE_SECONDS: float = 60
    RECOVERY_CONFIRM_SECONDS: float = 5

    def __post_init__(self) -> None:
        if not self.MORNING_START < self.MORNING_END:
            raise ValueError("Morning start must precede end")
        if not self.WAKE_RECORD_START < self.WAKE_RECORD_END:
            raise ValueError("Wake record start must precede end")
        if not isfinite(self.UTC_OFFSET_HOURS) or not -24 < self.UTC_OFFSET_HOURS < 24:
            raise ValueError("Invalid UTC offset")
        for name, value in vars(self).items():
            if name in {
                "MORNING_START", "MORNING_END", "WAKE_RECORD_START", "WAKE_RECORD_END",
                "UTC_OFFSET_HOURS",
            }:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "WAKE_PATTERN_MIN_SAMPLES", "WAKE_PATTERN_HISTORY_SIZE",
            "MORNING_WATER_AMOUNT_ML", "MAX_MORNING_AUTO_DISPENSE",
        ):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.WAKE_PATTERN_MIN_SAMPLES > self.WAKE_PATTERN_HISTORY_SIZE:
            raise ValueError("Wake pattern minimum samples cannot exceed history size")
        if not (self.FALL_CONFIRM_SECONDS < self.FALL_WARNING_SECONDS
                < self.FALL_EMERGENCY_SECONDS < self.LONG_UNRESPONSIVE_SECONDS):
            raise ValueError("Fall thresholds must be increasing")
