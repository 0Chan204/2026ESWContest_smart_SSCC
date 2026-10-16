"""Single-process durable outbox. Save before acknowledging controller output."""
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .decision_mapper import MappedDecision


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class Outbox:
    def __init__(self, path: Path, mode: str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions (
                source_id TEXT PRIMARY KEY, payload TEXT, source TEXT NOT NULL,
                status TEXT NOT NULL, diagnostic TEXT, created_at REAL NOT NULL,
                expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, response TEXT, http_status INTEGER
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, at REAL NOT NULL, detail TEXT NOT NULL
            );
        """)
        current = self.db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
        if current and current[0] != mode:
            self.db.close()
            raise ValueError("mock/live outbox mismatch")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('mode', ?)", (mode,))
            # Crash after transmission is ambiguous: retain the exact ID/body and attempt count.
            self.db.execute("UPDATE decisions SET status='pending' WHERE status='sending'")

    def close(self):
        self.db.close()

    def audit(self, kind, at, detail):
        with self.db:
            self.db.execute("INSERT INTO audit(kind, at, detail) VALUES (?, ?, ?)", (kind, at, encode(detail)))

    def audits(self, kind):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT detail FROM audit WHERE kind=? ORDER BY id", (kind,))]

    def save_batch(self, mapped: list[MappedDecision], now: float, ttl: float):
        # An exception rolls back the entire batch; the controller queue is still intact.
        with self.db:
            for result in mapped:
                self.db.execute("""INSERT OR IGNORE INTO decisions
                    (source_id,payload,source,status,diagnostic,created_at,expires_at)
                    VALUES (?,?,?,?,?,?,?)""", (
                        result.source_id, None if result.payload is None else encode(result.payload),
                        encode(result.source), "blocked" if result.payload is None else "pending",
                        result.diagnostic, now, result.source["timestamp"] + ttl))

    def rows(self):
        records = []
        for row in self.db.execute("SELECT * FROM decisions ORDER BY rowid"):
            record = dict(row)
            for name in ("payload", "source", "response"):
                if record[name] is not None:
                    record[name] = json.loads(record[name])
            records.append(record)
        return records

    def update(self, identity, **values):
        permitted = {"status", "diagnostic", "attempts", "next_attempt", "response", "http_status"}
        if not values or not set(values) <= permitted:
            raise ValueError("invalid outbox update")
        values = {k: encode(v) if k == "response" else v for k, v in values.items()}
        with self.db:
            self.db.execute("UPDATE decisions SET " + ",".join(f"{k}=?" for k in values)
                            + " WHERE source_id=?", (*values.values(), identity))

    def reserve_water(self, local_date, count):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('water_reservation', ?)",
                            (encode({"date": str(local_date), "count": count}),))

    def water_reservation(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='water_reservation'").fetchone()
        return None if row is None else json.loads(row[0])

    def latch_fall(self, timestamp):
        """One durable unresolved incident until a real backend reconciliation contract exists."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('fall_incident', ?)",
                            (encode({"local_incident_id": "fall-" + uuid4().hex,
                                     "started_at": timestamp, "status": "start_contract_unconfirmed",
                                     "decisionId": None, "fallIncidentId": None}),))

    def fall_incident(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='fall_incident'").fetchone()
        return None if row is None else json.loads(row[0])
