"""Scenario thresholds in seconds; timestamps are Unix seconds in configured local time."""
from dataclasses import dataclass
from datetime import time
from math import isfinite


@dataclass(frozen=True)
class ScenarioConfig:
    MORNING_START: time = time(6)
    MORNING_END: time = time(10)
    UTC_OFFSET_HOURS: float = 9
    WAKE_CONFIRM_SECONDS: float = 5
    KITCHEN_CONFIRM_SECONDS: float = 5
    WAKE_TO_KITCHEN_TIMEOUT_SECONDS: float = 1800
    MORNING_WATER_AMOUNT_ML: int = 250
    MAX_MORNING_AUTO_DISPENSE: int = 1
    FALL_CONFIRM_SECONDS: float = 5
    FALL_WARNING_SECONDS: float = 10
    FALL_EMERGENCY_SECONDS: float = 30
    LONG_UNRESPONSIVE_SECONDS: float = 60
    RECOVERY_CONFIRM_SECONDS: float = 5

    def __post_init__(self) -> None:
        if not self.MORNING_START < self.MORNING_END:
            raise ValueError("Morning start must precede end")
        if not isfinite(self.UTC_OFFSET_HOURS) or not -24 < self.UTC_OFFSET_HOURS < 24:
            raise ValueError("Invalid UTC offset")
        for name, value in vars(self).items():
            if name in {"MORNING_START", "MORNING_END", "UTC_OFFSET_HOURS"}:
                continue
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("MORNING_WATER_AMOUNT_ML", "MAX_MORNING_AUTO_DISPENSE"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if not (self.FALL_CONFIRM_SECONDS < self.FALL_WARNING_SECONDS
                < self.FALL_EMERGENCY_SECONDS < self.LONG_UNRESPONSIVE_SECONDS):
            raise ValueError("Fall thresholds must be increasing")
