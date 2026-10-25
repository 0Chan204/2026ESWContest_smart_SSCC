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
            CREATE INDEX IF NOT EXISTS decisions_status ON decisions(status);
            CREATE INDEX IF NOT EXISTS audit_time ON audit(at);
            CREATE TABLE IF NOT EXISTS behavior_events (
                event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, observed_at REAL NOT NULL
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

    def rows(self, status=None):
        records = []
        query = "SELECT * FROM decisions" + (" WHERE status=?" if status else "") + " ORDER BY rowid"
        for row in self.db.execute(query, (status,) if status else ()):
            record = dict(row)
            for name in ("payload", "source", "response"):
                if record[name] is not None:
                    record[name] = json.loads(record[name])
            records.append(record)
        return records

    def get_metadata(self, key):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def set_metadata(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, encode(value)))

    def update_fall(self, **values):
        record = self.fall_incident()
        if record is not None:
            self.set_metadata("fall_incident", {**record, **values})

    def prune_audit(self, before):
        # Keep delivery identities for deduplication; trim high-volume telemetry only.
        with self.db:
            self.db.execute("DELETE FROM audit WHERE at < ? AND kind IN "
                            "('evaluation','device_received','location_received','location_applied','diagnostic')",
                            (before,))

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

    def claim_behavior_event(self, event_id, fingerprint, observed_at):
        """Durable deduplication; changed contents cannot reuse an event identity."""
        row = self.db.execute("SELECT fingerprint FROM behavior_events WHERE event_id=?", (event_id,)).fetchone()
        if row is not None:
            return "duplicate" if row[0] == fingerprint else "conflict"
        with self.db:
            self.db.execute("INSERT INTO behavior_events VALUES (?,?,?)", (event_id, fingerprint, observed_at))
        return "new"

    def water_reservation(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='water_reservation'").fetchone()
        return None if row is None else json.loads(row[0])

    def latch_fall(self, timestamp, incident_id=None):
        """One durable unresolved incident until a real backend reconciliation contract exists."""
        current = self.fall_incident()
        if current is not None:
            return current
        record = {"local_incident_id": incident_id or "fall-" + uuid4().hex,
                  "started_at": timestamp, "status": "start_contract_unconfirmed",
                  "decisionId": None, "fallIncidentId": None}
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('fall_incident', ?)",
                            (encode(record),))
        return record

    def fall_incident(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='fall_incident'").fetchone()
        record = None if row is None else json.loads(row[0])
        return None if record is None or record["status"] == "resolved" else record

    def resolve_fall(self, incident_id, timestamp):
        record = self.fall_incident()
        if record is None or record["local_incident_id"] != incident_id:
            raise ValueError("Cannot resolve an unknown fall incident")
        resolved = {**record, "status": "resolved", "resolved_at": timestamp,
                    "resolution": "caregiver_confirmed_safe"}
        with self.db:
            self.db.execute("UPDATE metadata SET value=? WHERE key='fall_incident'",
                            (encode(resolved),))
        return resolved

    def has_fall_action(self, incident_id, event):
        for row in self.db.execute("SELECT source FROM decisions"):
            source = json.loads(row[0])
            if (source.get("scenario") == "bathroom_fall" and source.get("event") == event
                    and (source.get("details") or {}).get("incident_id") == incident_id):
                return True
        return False
