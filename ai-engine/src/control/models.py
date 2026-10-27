from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.control.policy import map_control_risk
from src.models import RiskDecision


class UserLocation(str, Enum):
    STOVE_AREA = "STOVE_AREA"
    KITCHEN = "KITCHEN"
    OTHER_ROOM = "OTHER_ROOM"
    OUTSIDE_HOME = "OUTSIDE_HOME"
    UNKNOWN = "UNKNOWN"


class ControlRisk(str, Enum):
    SAFE = "SAFE"
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Situation(str, Enum):
    STOVE_OFF = "STOVE_OFF"
    COOKING = "COOKING"
    TEMP_AWAY = "TEMP_AWAY"
    IN_HOME_AWAY = "IN_HOME_AWAY"
    HOME_EXIT_WITH_STOVE_ON = "HOME_EXIT_WITH_STOVE_ON"
    LOCATION_UNKNOWN = "LOCATION_UNKNOWN"


@dataclass(frozen=True)
class SensingState:
    location: UserLocation | str
    activity: str | None = None
    away_duration: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "location", UserLocation(self.location))
        if self.away_duration is not None and self.away_duration < 0:
            raise ValueError("away_duration must be 0 or greater")


@dataclass(frozen=True)
class DeviceState:
    stove_on: bool
    heat_level: str | None = None


@dataclass(frozen=True)
class ControlDecision:
    situation: Situation | str
    risk: ControlRisk | str
    location: UserLocation | str
    activity: str | None
    stove_on: bool
    heat_level: str | None
    away_duration: int | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "situation", Situation(self.situation))
        object.__setattr__(self, "risk", ControlRisk(self.risk))
        object.__setattr__(self, "location", UserLocation(self.location))

    def to_risk_decision(self) -> RiskDecision:
        if self.location is UserLocation.OUTSIDE_HOME:
            user_state = "OUT"
        elif self.location is UserLocation.UNKNOWN:
            user_state = "UNKNOWN"
        else:
            user_state = "IN"
        return RiskDecision(
            risk_level=map_control_risk(self.risk),
            situation=self.situation.value,
            user_state=user_state,
            user_location=self.location.value,
            device="stove",
            heat_level=self.heat_level,
            duration=self.away_duration,
        )
