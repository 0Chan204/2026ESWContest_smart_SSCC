from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from typing import Any

from src.models import RiskDecision, RiskLevel
from src.control.identifiers import canonical_device, device_target


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
    device: str = "water_purifier"
    water_temperature: str = "room_temp"
    event: str = "water_dispensed"
    request_weather_info: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "device", canonical_device(self.device))

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
    room: str | None = None

    def __post_init__(self) -> None:
        target, room = device_target(self.target, self.room)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "room", room)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["details"] is None:
            data.pop("details")
        if data["room"] is None:
            data.pop("room")
        return data


@dataclass(frozen=True)
class FallBackendSignal:
    """Host-supplied caregiver result; the boolean gate is legacy direct-call support."""

    timestamp: float
    allow_emergency_report: bool = False
    caregiver_status: str | None = None
    incident_id: str | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.timestamp, bool)
                or not isinstance(self.timestamp, (int, float))
                or not isfinite(self.timestamp)):
            raise ValueError("timestamp must be a finite number")
        if type(self.allow_emergency_report) is not bool:
            raise ValueError("allow_emergency_report must be boolean")
        if self.caregiver_status not in {None, "safe", "no_response"}:
            raise ValueError("caregiver_status must be safe or no_response")
        if self.caregiver_status == "safe" and self.allow_emergency_report:
            raise ValueError("safe caregiver response cannot authorize a report")
        if self.incident_id is not None and (not isinstance(self.incident_id, str)
                                             or not self.incident_id.strip()):
            raise ValueError("incident_id must be a non-empty string")
        if self.caregiver_status is not None and self.incident_id is None:
            raise ValueError("caregiver_status requires an incident_id")


class BathroomFallState(str, Enum):
    NORMAL_BATHROOM_USE = "NORMAL_BATHROOM_USE"
    FALL_SUSPECTED = "FALL_SUSPECTED"
    FALL_CONFIRMED = "FALL_CONFIRMED"
    FALL_WARNING = "FALL_WARNING"
    FALL_EMERGENCY = "FALL_EMERGENCY"
    RECOVERED = "RECOVERED"
    RESOLVED_BY_CAREGIVER = "RESOLVED_BY_CAREGIVER"


@dataclass(frozen=True)
class BathroomFallDecision:
    state: BathroomFallState
    risk: RiskLevel
    timestamp: float
    unresponsive_seconds: float = 0
    sensor_uncertain: bool = False
    long_unresponsive: bool = False
    incident_id: str | None = None
    candidate_only: bool = False
    evidence: dict[str, Any] | None = None

    def to_risk_decision(self) -> RiskDecision:
        return RiskDecision(
            risk_level=self.risk, situation=self.state.value,
            user_location="toilet", user_state="UNKNOWN" if self.sensor_uncertain else "IN",
            duration=int(self.unresponsive_seconds),
            decision_context={"scenario": "bathroom_fall", "state": self.state.value,
                              "risk": self.risk.value, "timestamp": self.timestamp,
                              "sensor_uncertain": self.sensor_uncertain,
                              "long_unresponsive": self.long_unresponsive,
                              "incident_id": self.incident_id},
        )
