from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from src.control.identifiers import canonical_room, device_target


@dataclass(frozen=True)
class AutomationAction:
    """A device command emitted by the confidence decision layer."""

    action_id: str
    timestamp: float
    scenario: str
    confidence: float
    device: str
    action: str
    reason: dict[str, float]
    room: str | None = None

    def __post_init__(self) -> None:
        device, room = device_target(self.device, self.room)
        object.__setattr__(self, "device", device)
        object.__setattr__(self, "room", room)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutomationDecision:
    action_id: str
    timestamp: float
    user_id: str
    scenario: str
    confidence: float
    threshold: float
    medium_threshold: float
    outcome: str
    features: dict[str, float]
    weights: dict[str, float]
    contributions: dict[str, float]
    action: AutomationAction | None = None
    guard_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = None if self.action is None else self.action.to_dict()
        return data


@dataclass(frozen=True)
class LightContext:
    room: str
    light_on: bool
    user_present: bool
    timestamp: float
    presence_duration: float = 0.0
    absence_duration: float = 0.0
    location_confidence: float = 1.0
    activity_confidence: float = 0.0
    sensor_consistency: float = 1.0

    def __post_init__(self) -> None:
        if not self.room or not isinstance(self.room, str):
            raise ValueError("room must be a non-empty string")
        object.__setattr__(self, "room", canonical_room(self.room))
        for name in ("light_on", "user_present"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, (int, float)) \
                or not isfinite(self.timestamp):
            raise ValueError("timestamp must be a finite number")
        for name in ("presence_duration", "absence_duration"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be nonnegative")
        for name in ("location_confidence", "activity_confidence", "sensor_consistency"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
