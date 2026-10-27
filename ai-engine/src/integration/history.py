"""Disk-backed implementations of the existing history interfaces for continuous use."""
import json
from pathlib import Path

from src.control.confidence.history_storage import DecisionHistoryStorage
from src.control.routine.routine_storage import RoutineStorage


class SQLiteDecisionHistory(DecisionHistoryStorage):
    def __init__(self, outbox, legacy_path):
        self.db = outbox.db
        self.path = Path(legacy_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS decision_history (action_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        if not outbox.get_metadata("decision_history_imported"):
            with self.db:
                if self.path.exists():
                    with self.path.open(encoding="utf-8") as stream:
                        for line in stream:
                            try:
                                record = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(record, dict) and record.get("action_id"):
                                self.db.execute("INSERT OR REPLACE INTO decision_history VALUES (?, ?)",
                                                (str(record["action_id"]), json.dumps(record, ensure_ascii=False)))
            outbox.set_metadata("decision_history_imported", True)

    def save(self, decision):
        record = dict(decision)
        if not record.get("action_id"):
            raise ValueError("decision history requires action_id")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO decision_history VALUES (?, ?)",
                            (str(record["action_id"]), json.dumps(record, ensure_ascii=False, allow_nan=False)))

    def get(self, action_id):
        row = self.db.execute("SELECT record FROM decision_history WHERE action_id=?", (action_id,)).fetchone()
        return None if row is None else json.loads(row[0])


class SQLiteRoutineStorage(RoutineStorage):
    def __init__(self, outbox):
        self.db = outbox.db
        self.db.execute("CREATE TABLE IF NOT EXISTS routine_history (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")

    def save(self, record):
        with self.db:
            self.db.execute("INSERT INTO routine_history(record) VALUES (?)",
                            (json.dumps(dict(record), ensure_ascii=False, allow_nan=False),))

    def list_records(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT record FROM routine_history ORDER BY id")]
