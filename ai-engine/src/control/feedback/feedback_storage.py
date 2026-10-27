from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from src.control.confidence.weight_manager import NEGATIVE_FEEDBACK, POSITIVE_FEEDBACK


class FeedbackStorage:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: list[dict[str, Any]] = []
        if self.path is not None and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        self._records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    def save(self, feedback: Mapping[str, Any]) -> None:
        record = dict(feedback)
        self._records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def score(self, user_id: str, scenario: str) -> float:
        relevant = [record for record in self._records
                    if record.get("user_id") == user_id
                    and record.get("scenario") == scenario
                    and record.get("weight_updated", True)]
        positive = sum(record.get("feedback") in POSITIVE_FEEDBACK for record in relevant)
        negative = sum(record.get("feedback") in NEGATIVE_FEEDBACK for record in relevant)
        # Laplace smoothing gives an unseen scenario a neutral score of 0.5.
        return (positive + 1.0) / (positive + negative + 2.0)

    def has_action(self, action_id: str) -> bool:
        return any(record.get("action_id") == action_id and record.get("weight_updated", True)
                   for record in self._records)

    def list_records(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self._records]
