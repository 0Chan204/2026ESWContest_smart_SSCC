from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class RoutineStorage:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: list[dict[str, Any]] = []

    def save(self, record: Mapping[str, Any]) -> None:
        data = dict(record)
        self._records.append(data)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(data, ensure_ascii=False) + "\n")

    def list_records(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self._records]

