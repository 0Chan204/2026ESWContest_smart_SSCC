from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite

from src.control.realtime_config import STATE_OUTPUT
from src.models import RiskDecision


class RealtimeState(str, Enum):
    NORMAL = "NORMAL"
    TEMPORARY_ABSENCE = "TEMPORARY_ABSENCE"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    DANGER = "DANGER"
    SENSOR_UNCERTAIN = "SENSOR_UNCERTAIN"
    RECOVERED = "RECOVERED"


def finite(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")


@dataclass(frozen=True)
class SensingUpdate:
    location: str
    timestamp: float
    activity: str = "unknown"
    confidence: float = 1.0
    detected: bool = True
    motion_state: str | None = None
    fall_detected: bool | None = None
    activity_confidence: float | None = None

    def __post_init__(self):
        if self.location not in {"kitchen", "bathroom", "living_room", "bedroom", "entrance", "outside", "unknown"}:
            raise ValueError("Unsupported realtime location")
        finite("timestamp", self.timestamp)
        finite("confidence", self.confidence)
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.activity_confidence is not None:
            finite("activity_confidence", self.activity_confidence)
            if not 0 <= self.activity_confidence <= 1:
                raise ValueError("activity_confidence must be between 0 and 1")
        if type(self.detected) is not bool:
            raise ValueError("detected must be boolean")
        if self.motion_state not in {None, "moving", "still", "unknown"}:
            raise ValueError("Unsupported motion state")
        if self.fall_detected is not None and type(self.fall_detected) is not bool:
            raise ValueError("fall_detected must be boolean or None")


@dataclass(frozen=True)
class ApplianceUpdate:
    power_on: bool
    timestamp: float
    power_watts: float | None = None
    temperature_c: float | None = None
    operating: bool | None = None
    smoke: bool = False
    fire: bool = False
    abnormal: bool = False
    control_state: str | None = None

    def __post_init__(self):
        finite("timestamp", self.timestamp)
        for name in ("power_on", "smoke", "fire", "abnormal"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if self.operating is not None and type(self.operating) is not bool:
            raise ValueError("operating must be boolean or None")
        if self.control_state not in {None, "NONE", "HOMEVIS_REDUCED", "USER_OVERRIDE"}:
            raise ValueError("Unsupported control_state")
        for name in ("power_watts", "temperature_c"):
            value = getattr(self, name)
            if value is not None:
                finite(name, value)
        if self.power_watts is not None and self.power_watts < 0:
            raise ValueError("power_watts must be nonnegative")

    @property
    def active(self):
        return self.power_on and self.operating is not False


@dataclass(frozen=True)
class RealtimeDecision:
    state: RealtimeState
    previous_state: RealtimeState
    reason: str
    user_location: str
    kitchen_absence_seconds: float
    appliance_on: bool | None
    risk_score: float
    action: str
    timestamp: float
    sensor_uncertain: bool
    appliance_stale: bool
    power_watts: float | None
    temperature_c: float | None
    power_rise_per_second: float | None
    temperature_rise_per_second: float | None
    confidence_decision: dict | None = None

    def to_dict(self):
        data = asdict(self)
        data["state"] = self.state.value
        data["previous_state"] = self.previous_state.value
        return data

    def to_risk_decision(self):
        return RiskDecision(
            risk_level=STATE_OUTPUT[self.state.value][2],
            situation=self.state.value,
            user_state="OUT" if self.user_location == "outside" else (
                "UNKNOWN" if self.sensor_uncertain else "IN"
            ),
            user_location=self.user_location,
            device="induction",
            duration=int(self.kitchen_absence_seconds),
            decision_context=self.to_dict(),
        )
