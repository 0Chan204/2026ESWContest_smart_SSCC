from __future__ import annotations

from collections.abc import Sequence

from src.control.automation_models import LightContext
from src.control.confidence.config import ConfidenceConfig


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


class FeatureExtractor:
    def __init__(self, config: ConfidenceConfig | None = None) -> None:
        self.config = config or ConfidenceConfig()

    @staticmethod
    def sensor_consistency(
        history: Sequence[tuple[str, float, bool]], target_location: str
    ) -> float:
        if not history:
            return 0.0
        scores = [confidence if detected and location == target_location else 0.0
                  for location, confidence, detected in history]
        return _clamp(sum(scores) / len(scores))

    def kitchen_leave(
        self,
        *,
        location_confidence: float,
        activity_confidence: float,
        leave_duration: float,
        current_stove_power: float | None,
        outside_home: bool,
        sensor_consistency: float,
        previous_homevis_action: bool,
        feedback_score: float,
        current_stove_level: int | None = None,
    ) -> dict[str, float]:
        if self.config.INPUT_PROFILE == "location_level_v1":
            return {
                "location": _clamp(location_confidence),
                "duration": _clamp(leave_duration / self.config.KITCHEN_LEAVE_FULL_SECONDS),
                # An observed ordinal stage, never a watts estimate.
                "stove_level": current_stove_level / 9 if type(current_stove_level) is int
                    and 1 <= current_stove_level <= 9 else 0.0,
                "consistency": _clamp(sensor_consistency), "feedback": _clamp(feedback_score),
            }
        return {
            "location": _clamp(location_confidence),
            "duration": _clamp(leave_duration / self.config.KITCHEN_LEAVE_FULL_SECONDS),
            "stove_power": _clamp((current_stove_power or 0.0) / self.config.MAX_STOVE_POWER_WATTS),
            "outside_home": 1.0 if outside_home else 0.0,
            "consistency": _clamp(sensor_consistency),
            "activity": _clamp(activity_confidence),
            "previous_action": 0.0 if previous_homevis_action else 1.0,
            "feedback": _clamp(feedback_score),
        }

    def kitchen_return(
        self,
        *,
        location_confidence: float,
        return_duration: float,
        sensor_consistency: float,
        stove_on: bool,
        homevis_reduced: bool,
        feedback_score: float,
    ) -> dict[str, float]:
        return {
            "location": _clamp(location_confidence),
            "return_duration": _clamp(return_duration / self.config.KITCHEN_RETURN_FULL_SECONDS),
            "consistency": _clamp(sensor_consistency),
            "stove_state": 1.0 if stove_on else 0.0,
            "control_state": 1.0 if homevis_reduced else 0.0,
            "feedback": _clamp(feedback_score),
        }

    def light(self, context: LightContext, feedback_score: float) -> tuple[str, dict[str, float]]:
        if self.config.INPUT_PROFILE == "location_level_v1":
            duration = context.presence_duration if context.user_present else context.absence_duration
            limit = self.config.LIGHT_PRESENCE_FULL_SECONDS if context.user_present else self.config.LIGHT_LEAVE_FULL_SECONDS
            return ("light_auto_on" if context.user_present else "light_auto_off"), {
                "location": _clamp(context.location_confidence),
                "presence_duration" if context.user_present else "leave_duration": _clamp(duration / limit),
                "consistency": _clamp(context.sensor_consistency), "feedback": _clamp(feedback_score),
            }
        common = {
            "location": _clamp(context.location_confidence),
            "consistency": _clamp(context.sensor_consistency),
            "activity": _clamp(context.activity_confidence),
            "feedback": _clamp(feedback_score),
        }
        if context.user_present:
            return "light_auto_on", {
                "location": common["location"],
                "presence_duration": _clamp(
                    context.presence_duration / self.config.LIGHT_PRESENCE_FULL_SECONDS
                ),
                "consistency": common["consistency"],
                "activity": common["activity"],
                "feedback": common["feedback"],
            }
        return "light_auto_off", {
            "location": common["location"],
            "leave_duration": _clamp(
                context.absence_duration / self.config.LIGHT_LEAVE_FULL_SECONDS
            ),
            "consistency": common["consistency"],
            "activity": common["activity"],
            "feedback": common["feedback"],
        }

