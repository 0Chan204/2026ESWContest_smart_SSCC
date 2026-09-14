from dataclasses import asdict, dataclass
from enum import Enum

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

    def to_dict(self):
        return asdict(self)


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
