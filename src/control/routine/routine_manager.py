from __future__ import annotations

from typing import Any

from src.control.confidence.config import DEFAULT_USER_ID
from src.control.routine.routine_storage import RoutineStorage


class RoutineManager:
    def __init__(self, storage: RoutineStorage) -> None:
        self.storage = storage

    def record(
        self,
        *,
        timestamp: float,
        location: str,
        activity: str | None,
        confidence: float,
        device: str | None = None,
        action: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        record = {
            "timestamp": timestamp,
            "user_id": user_id,
            "location": location,
            "activity": activity,
            "device": device,
            "action": action,
            "confidence": confidence,
        }
        self.storage.save(record)
        return record

