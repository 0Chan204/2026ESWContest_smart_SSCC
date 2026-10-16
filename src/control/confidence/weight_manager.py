from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping

from src.control.confidence.config import ConfidenceConfig, DEFAULT_USER_ID


LOGGER = logging.getLogger(__name__)

POSITIVE_FEEDBACK = {"positive", "too_late"}
NEGATIVE_FEEDBACK = {"unnecessary", "too_sensitive", "cancel", "user_override"}
SUPPORTED_FEEDBACK = POSITIVE_FEEDBACK | NEGATIVE_FEEDBACK


class WeightManager:
    def __init__(
        self,
        config: ConfidenceConfig | None = None,
        storage_path: str | Path | None = None,
    ) -> None:
        self.config = config or ConfidenceConfig()
        self.storage_path = Path(storage_path) if storage_path is not None else None
        self._user_weights = self._load()

    def _load(self) -> dict[str, dict[str, dict[str, float]]]:
        if self.storage_path is None or not self.storage_path.exists():
            return {}
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to load user weights: {self.storage_path}") from exc
        if not isinstance(data, dict):
            raise ValueError("user weight storage must contain an object")
        return data

    def get_weights(self, user_id: str, scenario: str) -> dict[str, float]:
        if scenario not in self.config.SCENARIO_WEIGHTS:
            raise ValueError(f"Unsupported confidence scenario: {scenario}")
        stored = self._user_weights.get(user_id, {}).get(scenario)
        if stored is None:
            return dict(self.config.SCENARIO_WEIGHTS[scenario])
        expected = set(self.config.SCENARIO_WEIGHTS[scenario])
        if set(stored) != expected:
            raise ValueError(f"Stored weights for {user_id}/{scenario} do not match config")
        return {name: float(value) for name, value in stored.items()}

    def update_from_feedback(
        self,
        user_id: str,
        scenario: str,
        contributions: Mapping[str, float],
        feedback: str,
    ) -> tuple[dict[str, float], dict[str, float]]:
        if feedback not in SUPPORTED_FEEDBACK:
            raise ValueError(f"Unsupported feedback: {feedback}")
        before = self.get_weights(user_id, scenario)
        if set(contributions) != set(before):
            raise ValueError("contributions must match scenario weights")
        direction = 1.0 if feedback in POSITIVE_FEEDBACK else -1.0
        learning_rate = self.config.FEEDBACK_LEARNING_RATE
        adjusted = {
            name: weight + direction * learning_rate * max(0.0, float(contributions[name]))
            for name, weight in before.items()
        }
        after = self._bounded_normalize(adjusted)
        self._user_weights.setdefault(user_id, {})[scenario] = after
        self._save()
        LOGGER.info("[%s/%s] feedback=%s weights: %s -> %s",
                    user_id, scenario, feedback, before, after)
        return before, dict(after)

    def _bounded_normalize(self, values: Mapping[str, float]) -> dict[str, float]:
        minimum, maximum = self.config.MIN_WEIGHT, self.config.MAX_WEIGHT
        names = list(values)
        if len(names) * minimum > 1 or len(names) * maximum < 1:
            raise ValueError("weight bounds cannot produce a unit sum")
        source = {name: max(0.0, float(values[name])) for name in names}
        result: dict[str, float] = {}
        active = list(names)
        remaining = 1.0
        while active:
            total = sum(source[name] for name in active)
            tentative = {
                name: (remaining / len(active) if total == 0 else source[name] * remaining / total)
                for name in active
            }
            low = [name for name, value in tentative.items() if value < minimum]
            high = [name for name, value in tentative.items() if value > maximum]
            if not low and not high:
                result.update(tentative)
                break
            for name in low:
                result[name] = minimum
                remaining -= minimum
                active.remove(name)
            for name in high:
                result[name] = maximum
                remaining -= maximum
                active.remove(name)
        # Remove harmless floating point drift while respecting the configured bounds.
        drift = 1.0 - sum(result.values())
        for name in names:
            candidate = result[name] + drift
            if minimum - 1e-12 <= candidate <= maximum + 1e-12:
                result[name] = candidate
                break
        return result

    def _save(self) -> None:
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._user_weights, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.storage_path)

    @property
    def default_user_id(self) -> str:
        return DEFAULT_USER_ID
