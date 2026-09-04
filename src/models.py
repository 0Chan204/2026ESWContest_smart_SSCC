from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HIGH = "HIGH"


@dataclass(frozen=True)
class RiskDecision:
    """Output of the future situation/risk decision model.

    This class does NOT calculate risk. It only carries an already-decided
    risk level and optional context for message generation.
    """

    risk_level: RiskLevel | str
    situation: str | None = None
    user_state: str | None = None
    user_location: str | None = None
    device: str | None = None
    heat_level: str | None = None
    duration: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_level", RiskLevel(self.risk_level))

        if self.duration is not None and self.duration < 0:
            raise ValueError("duration must be 0 or greater")

        for field_name in (
            "situation",
            "user_state",
            "user_location",
            "device",
            "heat_level",
        ):
            value = getattr(self, field_name)
            if value is not None:
                normalized = str(value).strip()
                object.__setattr__(self, field_name, normalized or None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskDecision":
        return cls(
            risk_level=data["risk_level"],
            situation=data.get("situation"),
            user_state=data.get("user_state"),
            user_location=data.get("user_location"),
            device=data.get("device"),
            heat_level=data.get("heat_level"),
            duration=data.get("duration"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = self.risk_level.value
        return data


@dataclass(frozen=True)
class AlertOutput:
    """Final data handed to the equipment-side module."""

    risk_level: RiskLevel
    warning_sound: bool
    voice: bool
    message: str | None
    tts_file: str | None
    llm_name: str
    prompt_version: str
    fallback_used: bool
    llm_error: str | None = None
    tts_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = self.risk_level.value
        return data
