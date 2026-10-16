from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from typing import Any

from src.models import RiskDecision, RiskLevel


class MorningWaterState(str, Enum):
    IDLE = "IDLE"
    SLEEPING = "SLEEPING"
    WAKE_UP_DETECTED = "WAKE_UP_DETECTED"
    MORNING_MOVING = "MORNING_MOVING"
    MORNING_KITCHEN_ENTRY = "MORNING_KITCHEN_ENTRY"
    WATER_DISPENSE_REQUEST = "WATER_DISPENSE_REQUEST"


@dataclass(frozen=True)
class DeviceCommand:
    timestamp: float
    amount_ml: int
    reason: str = "Confirmed morning wake-up and kitchen stay"
    command_type: str = "DISPENSE_WATER"
    device: str = "water_dispenser"
    water_temperature: str = "room_temp"
    event: str = "water_dispensed"
    request_weather_info: bool = True

    def to_dict(self):
        return asdict(self)


class BedtimeLightState(str, Enum):
    AWAKE = "AWAKE"
    LYING = "LYING"
    BEDTIME_CONFIRMED = "BEDTIME_CONFIRMED"
    LIGHT_OFF_REQUESTED = "LIGHT_OFF_REQUESTED"


@dataclass(frozen=True)
class ScenarioAction:
    """A rule-based request for the backend or a connected device."""

    timestamp: float
    scenario: str
    event: str
    action: str
    target: str
    reason: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["details"] is None:
            data.pop("details")
        return data


@dataclass(frozen=True)
class FallBackendSignal:
    timestamp: float
    allow_emergency_report: bool = True

    def __post_init__(self) -> None:
        if (isinstance(self.timestamp, bool)
                or not isinstance(self.timestamp, (int, float))
                or not isfinite(self.timestamp)):
            raise ValueError("timestamp must be a finite number")
        if type(self.allow_emergency_report) is not bool:
            raise ValueError("allow_emergency_report must be boolean")


class BathroomFallState(str, Enum):
    NORMAL_BATHROOM_USE = "NORMAL_BATHROOM_USE"
    FALL_SUSPECTED = "FALL_SUSPECTED"
    FALL_CONFIRMED = "FALL_CONFIRMED"
    FALL_WARNING = "FALL_WARNING"
    FALL_EMERGENCY = "FALL_EMERGENCY"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True)
class BathroomFallDecision:
    state: BathroomFallState
    risk: RiskLevel
    timestamp: float
    unresponsive_seconds: float = 0
    sensor_uncertain: bool = False
    long_unresponsive: bool = False

    def to_risk_decision(self) -> RiskDecision:
        return RiskDecision(
            risk_level=self.risk, situation=self.state.value,
            user_location="bathroom", user_state="UNKNOWN" if self.sensor_uncertain else "IN",
            duration=int(self.unresponsive_seconds),
            decision_context={"scenario": "bathroom_fall", "state": self.state.value,
                              "risk": self.risk.value, "timestamp": self.timestamp,
                              "sensor_uncertain": self.sensor_uncertain,
                              "long_unresponsive": self.long_unresponsive},
        )
