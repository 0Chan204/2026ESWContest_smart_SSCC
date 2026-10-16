from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class DecisionHistoryStorage:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: dict[str, dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        if self.path is None or not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            action_id = record.get("action_id")
            if action_id:
                self._records[action_id] = record

    def save(self, decision: Mapping[str, Any]) -> None:
        record = dict(decision)
        action_id = record.get("action_id")
        if not action_id:
            raise ValueError("decision history requires action_id")
        self._records[str(action_id)] = record
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get(self, action_id: str) -> dict[str, Any] | None:
        record = self._records.get(action_id)
        return None if record is None else dict(record)

