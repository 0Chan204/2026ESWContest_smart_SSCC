from __future__ import annotations

import json
from pathlib import Path

from src.models import AlertOutput


class OutputWriter:
    def save_json(self, output: AlertOutput, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(output.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
