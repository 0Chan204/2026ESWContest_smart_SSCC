"""Prototype thresholds: watts, Celsius, seconds. Calibrate for the appliance."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class RealtimeConfig:
    SENSING_CONFIRM_TIME: float = 5
    KITCHEN_SHORT_ABSENCE: float = 20
    KITCHEN_WARNING_TIME: float = 40
    KITCHEN_DANGER_TIME: float = 60
    ENTRANCE_CONFIRM_TIME: float = 10
    OUTSIDE_CONFIRM_TIME: float = 10
    RETURN_CONFIRM_TIME: float = 5
    UNKNOWN_TIMEOUT: float = 20
    APPLIANCE_TIMEOUT: float = 20
    MIN_CONFIDENCE: float = 0.6
    HIGH_POWER_WATTS: float = 1800
    HIGH_TEMPERATURE_C: float = 200
    RISING_POWER_WATTS_PER_SECOND: float = 100
    RISING_TEMPERATURE_C_PER_SECOND: float = 1
    RAPID_TEMPERATURE_C_PER_SECOND: float = 10

    def __post_init__(self):
        for name, value in vars(self).items():
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.MIN_CONFIDENCE > 1:
            raise ValueError("MIN_CONFIDENCE must be <= 1")
        if not self.KITCHEN_SHORT_ABSENCE < self.KITCHEN_WARNING_TIME < self.KITCHEN_DANGER_TIME:
            raise ValueError("Absence thresholds must be increasing")
        if self.RISING_TEMPERATURE_C_PER_SECOND >= self.RAPID_TEMPERATURE_C_PER_SECOND:
            raise ValueError("Rapid temperature threshold must exceed rising threshold")


# Scores express policy severity, not calibrated accident probabilities.
STATE_OUTPUT = {
    "NORMAL": (0.0, "NONE", "NORMAL"),
    "TEMPORARY_ABSENCE": (0.15, "NONE", "NORMAL"),
    "CAUTION": (0.4, "VOICE_WARNING", "WARNING"),
    "WARNING": (0.68, "VOICE_WARNING", "WARNING"),
    "DANGER": (0.95, "EMERGENCY_WARNING", "HIGH"),
    "SENSOR_UNCERTAIN": (0.5, "CHECK_SENSOR", "WARNING"),
    "RECOVERED": (0.0, "NONE", "NORMAL"),
}
