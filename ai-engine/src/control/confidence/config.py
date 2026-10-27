from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from math import isfinite


DEFAULT_USER_ID = "default"


def _default_weights() -> dict[str, dict[str, float]]:
    return {
        "kitchen_leave_reduce_power": {
            "location": 0.16,
            "duration": 0.23,
            "stove_power": 0.20,
            "outside_home": 0.14,
            "consistency": 0.12,
            "activity": 0.05,
            "previous_action": 0.05,
            "feedback": 0.05,
        },
        "kitchen_return_restore": {
            "location": 0.30,
            "return_duration": 0.25,
            "consistency": 0.20,
            "stove_state": 0.10,
            "control_state": 0.10,
            "feedback": 0.05,
        },
        "light_auto_on": {
            "location": 0.35,
            "presence_duration": 0.25,
            "consistency": 0.20,
            "activity": 0.10,
            "feedback": 0.10,
        },
        "light_auto_off": {
            "location": 0.30,
            "leave_duration": 0.30,
            "consistency": 0.20,
            "activity": 0.10,
            "feedback": 0.10,
        },
        "bathroom_fall_alert": {
            "fall_signal": 0.35,
            "still_duration": 0.25,
            "location": 0.15,
            "consistency": 0.15,
            "feedback": 0.10,
        },
    }


def _thresholds() -> dict[str, float]:
    return {
        "kitchen_leave_reduce_power": 0.82,
        "kitchen_return_restore": 0.80,
        "light_auto_on": 0.72,
        "light_auto_off": 0.78,
        "bathroom_fall_alert": 0.90,
    }


SCENARIO_WEIGHTS = _default_weights()
SCENARIO_THRESHOLDS = _thresholds()
MEDIUM_CONFIDENCE_THRESHOLD = 0.60
FEEDBACK_LEARNING_RATE = 0.02
FEEDBACK_APPLY_THRESHOLD = 0.80
FEEDBACK_REVIEW_THRESHOLD = 0.50
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.50


@dataclass(frozen=True)
class ConfidenceConfig:
    """Tunable policy for scoring and conservative online adaptation."""

    SCENARIO_WEIGHTS: dict[str, dict[str, float]] = field(
        default_factory=lambda: {name: dict(weights) for name, weights in SCENARIO_WEIGHTS.items()}
    )
    SCENARIO_THRESHOLDS: dict[str, float] = field(
        default_factory=lambda: dict(SCENARIO_THRESHOLDS)
    )
    MEDIUM_CONFIDENCE_THRESHOLD: float = MEDIUM_CONFIDENCE_THRESHOLD
    FEEDBACK_LEARNING_RATE: float = FEEDBACK_LEARNING_RATE
    FEEDBACK_APPLY_THRESHOLD: float = FEEDBACK_APPLY_THRESHOLD
    FEEDBACK_REVIEW_THRESHOLD: float = FEEDBACK_REVIEW_THRESHOLD
    MIN_WEIGHT: float = MIN_WEIGHT
    MAX_WEIGHT: float = MAX_WEIGHT
    KITCHEN_LEAVE_FULL_SECONDS: float = 60.0
    KITCHEN_RETURN_FULL_SECONDS: float = 5.0
    LIGHT_PRESENCE_FULL_SECONDS: float = 5.0
    LIGHT_LEAVE_FULL_SECONDS: float = 30.0
    MAX_STOVE_POWER_WATTS: float = 1800.0
    SENSOR_HISTORY_SIZE: int = 5
    INPUT_PROFILE: str = "legacy"

    @classmethod
    def for_profile(cls, profile: str, *, absence_seconds=40.0, return_seconds=5.0,
                    light_on_seconds=5.0, light_off_seconds=30.0):
        if profile == "legacy":
            return cls()
        if profile != "location_level_v1":
            raise ValueError("unsupported automation profile")
        weights = _default_weights()
        weights["kitchen_leave_reduce_power"] = {
            "location": .30, "duration": .30, "stove_level": .10,
            "consistency": .20, "feedback": .10,
        }
        weights["light_auto_on"] = {
            "location": .40, "presence_duration": .30, "consistency": .20, "feedback": .10,
        }
        weights["light_auto_off"] = {
            "location": .35, "leave_duration": .35, "consistency": .20, "feedback": .10,
        }
        return cls(INPUT_PROFILE=profile, SCENARIO_WEIGHTS=weights,
                   KITCHEN_LEAVE_FULL_SECONDS=absence_seconds, KITCHEN_RETURN_FULL_SECONDS=return_seconds,
                   LIGHT_PRESENCE_FULL_SECONDS=light_on_seconds, LIGHT_LEAVE_FULL_SECONDS=light_off_seconds)

    def __post_init__(self) -> None:
        if self.INPUT_PROFILE not in {"legacy", "location_level_v1"}:
            raise ValueError("unsupported automation profile")
        scalars = (
            "MEDIUM_CONFIDENCE_THRESHOLD", "FEEDBACK_LEARNING_RATE",
            "FEEDBACK_APPLY_THRESHOLD", "FEEDBACK_REVIEW_THRESHOLD", "MIN_WEIGHT",
            "MAX_WEIGHT", "KITCHEN_LEAVE_FULL_SECONDS", "KITCHEN_RETURN_FULL_SECONDS",
            "LIGHT_PRESENCE_FULL_SECONDS", "LIGHT_LEAVE_FULL_SECONDS", "MAX_STOVE_POWER_WATTS",
        )
        for name in scalars:
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0 < self.MEDIUM_CONFIDENCE_THRESHOLD < 1:
            raise ValueError("MEDIUM_CONFIDENCE_THRESHOLD must be between 0 and 1")
        if not 0 <= self.FEEDBACK_REVIEW_THRESHOLD <= self.FEEDBACK_APPLY_THRESHOLD <= 1:
            raise ValueError("feedback thresholds must satisfy 0 <= review <= apply <= 1")
        if not 0 < self.MIN_WEIGHT < self.MAX_WEIGHT < 1:
            raise ValueError("weight bounds must satisfy 0 < min < max < 1")
        if type(self.SENSOR_HISTORY_SIZE) is not int or self.SENSOR_HISTORY_SIZE <= 0:
            raise ValueError("SENSOR_HISTORY_SIZE must be a positive integer")
        if set(self.SCENARIO_WEIGHTS) != set(self.SCENARIO_THRESHOLDS):
            raise ValueError("weights and thresholds must define the same scenarios")
        for scenario, weights in self.SCENARIO_WEIGHTS.items():
            if not weights or abs(sum(weights.values()) - 1.0) > 1e-9:
                raise ValueError(f"weights for {scenario} must sum to 1")
            if any(not isfinite(value) or value < self.MIN_WEIGHT or value > self.MAX_WEIGHT
                   for value in weights.values()):
                raise ValueError(f"weights for {scenario} are outside configured bounds")
            threshold = self.SCENARIO_THRESHOLDS[scenario]
            if not isfinite(threshold) or not self.MEDIUM_CONFIDENCE_THRESHOLD <= threshold <= 1:
                raise ValueError(f"invalid threshold for {scenario}")

    @property
    def weight_storage_suffix(self):
        """Keep learned weights for each operator baseline without deleting history."""
        suffix = "" if self.INPUT_PROFILE == "legacy" else "." + self.INPUT_PROFILE
        baseline = type(self).for_profile(self.INPUT_PROFILE)
        def signature(config):
            return {"weights": config.SCENARIO_WEIGHTS, "min": config.MIN_WEIGHT, "max": config.MAX_WEIGHT}
        if signature(self) != signature(baseline):
            encoded = json.dumps(signature(self), sort_keys=True, separators=(",", ":"), allow_nan=False)
            suffix += ".policy-" + hashlib.sha256(encoded.encode()).hexdigest()[:12]
        return suffix
