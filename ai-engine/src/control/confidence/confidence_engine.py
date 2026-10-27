from __future__ import annotations

from typing import Mapping

from src.control.confidence.config import DEFAULT_USER_ID
from src.control.confidence.weight_manager import WeightManager


class ConfidenceEngine:
    def __init__(self, weight_manager: WeightManager | None = None) -> None:
        self.weight_manager = weight_manager or WeightManager()

    def calculate(
        self,
        scenario: str,
        features: Mapping[str, float],
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, object]:
        weights = self.weight_manager.get_weights(user_id, scenario)
        missing = set(weights) - set(features)
        unknown = set(features) - set(weights)
        if missing or unknown:
            raise ValueError(
                f"feature mismatch for {scenario}; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        normalized_features: dict[str, float] = {}
        for name, value in features.items():
            numeric = float(value)
            if not 0 <= numeric <= 1:
                raise ValueError(f"feature {name} must be between 0 and 1")
            normalized_features[name] = numeric
        contributions = {
            name: normalized_features[name] * weights[name] for name in weights
        }
        confidence = min(1.0, max(0.0, sum(contributions.values())))
        return {
            "confidence": confidence,
            "features": normalized_features,
            "weights": weights,
            "contributions": contributions,
        }
