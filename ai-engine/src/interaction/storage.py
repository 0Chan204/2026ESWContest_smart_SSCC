"""Voice state shares the outbox connection/owner; workers must never use this module."""
import hashlib
import json

from src.integration.outbox import encode
from src.integration.schemas import ContractError, measured_time


def identity(prefix, value):
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class VoiceStore:
    def __init__(self, outbox):
        self.db = outbox.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS voice_requests (
                voice_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE,
                request TEXT NOT NULL, received_at REAL NOT NULL, expires_at REAL NOT NULL,
                status TEXT NOT NULL, payload TEXT, response TEXT, error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                analysis TEXT, effect_status TEXT
            );
            CREATE INDEX IF NOT EXISTS voice_status ON voice_requests(status, received_at);
            CREATE TABLE IF NOT EXISTS voice_feedback_claims (
                action_id TEXT PRIMARY KEY, voice_id TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_instructions (
                instruction_id TEXT PRIMARY KEY, source_voice_id TEXT NOT NULL UNIQUE,
                user_id TEXT, original_text TEXT NOT NULL, intent TEXT NOT NULL,
                scenario TEXT, device TEXT, parameters TEXT NOT NULL,
                created_at REAL NOT NULL, confirmed_at REAL, effective_from REAL,
                status TEXT NOT NULL, policy_version TEXT NOT NULL, supersedes_instruction_id TEXT
            );
        """)
        with self.db:
            self.db.execute("UPDATE voice_requests SET status='received' WHERE status='processing'")
            self.db.execute("UPDATE voice_requests SET status='pending' WHERE status='sending'")

    @staticmethod
    def decode(row):
        if row is None:
            return None
        value = dict(row)
        for key in ("request", "payload", "response", "analysis"):
            if value[key] is not None:
                value[key] = json.loads(value[key])
        return value

    def get(self, voice_id):
        return self.decode(self.db.execute("SELECT * FROM voice_requests WHERE voice_id=?", (voice_id,)).fetchone())

    def receive(self, request, now, capacity):
        previous = self.get(request["voiceId"])
        if previous is not None:
            # Recovery includes optional defaults absent from the MQTT copy.
            fields = ("text", "expiresAt", "confidence", "recognizedAt", "receivedAt")
            if any(previous["request"].get(k) != request.get(k) for k in fields):
                raise ContractError("conflicting voiceId")
            return False
        count = self.db.execute("SELECT count(*) FROM voice_requests WHERE status IN ('received','processing','pending','sending')").fetchone()[0]
        if count >= capacity:
            raise ContractError("voice queue full")
        with self.db:
            self.db.execute("""INSERT INTO voice_requests
                (voice_id,decision_id,request,received_at,expires_at,status) VALUES (?,?,?,?,?,'received')""",
                (request["voiceId"], identity("dec-voice-", request["voiceId"]), encode(request), now,
                 measured_time(request["expiresAt"])))
        return True

    def rows(self, status, limit=100):
        return [self.decode(row) for row in self.db.execute(
            "SELECT * FROM voice_requests WHERE status=? ORDER BY next_attempt,received_at LIMIT ?", (status, limit))]

    def update(self, voice_id, **values):
        allowed = {"status", "payload", "response", "error", "attempts", "next_attempt", "analysis", "effect_status"}
        if not values or set(values) - allowed:
            raise ValueError("invalid voice update")
        for key in ("payload", "response", "analysis"):
            if key in values:
                values[key] = encode(values[key])
        if "payload" in values:
            old = self.get(voice_id)["payload"]
            if old is not None and encode(old) != values["payload"]:
                raise ValueError("voice body is immutable once prepared")
        with self.db:
            self.db.execute("UPDATE voice_requests SET " + ",".join(k + "=?" for k in values) + " WHERE voice_id=?",
                            (*values.values(), voice_id))

    def claim_feedback(self, action_id, voice_id):
        # Reserve BEFORE legacy weight/JSONL writes. After a crash, uncertainty is
        # explicitly not retried: at-most-once learning is safer than double training.
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO voice_feedback_claims VALUES (?,?,'started')", (action_id, voice_id))
        return cursor.rowcount == 1


class UserInstructionStorage:
    """No activation API: backend confirmation currently approves one device action only."""
    def __init__(self, store):
        self.db = store.db

    def propose(self, request, intent, user_id, policy_version, now):
        key = identity("instruction-", request["voiceId"])
        kind = "preference_change" if "preference_change" in intent["intents"] else "control_instruction"
        scenario = {("light", "on"): "light_auto_on", ("light", "turn_on"): "light_auto_on",
                    ("light", "off"): "light_auto_off", ("light", "turn_off"): "light_auto_off",
                    ("stove", "reduce_power"): "kitchen_leave_reduce_power",
                    ("stove", "restore_power"): "kitchen_return_restore"}.get((intent["device"], intent["action"]))
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO user_instructions
                (instruction_id,source_voice_id,user_id,original_text,intent,scenario,device,parameters,
                 created_at,status,policy_version) VALUES (?,?,?,?,?,?,?,?,?,'proposed',?)""",
                (key, request["voiceId"], user_id, request["text"], kind, scenario, intent["device"],
                 encode(intent["parameters"]), now, policy_version))
        return key

    def recent(self, user_id):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM user_instructions WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))]

    def get(self, key):
        row = self.db.execute("SELECT * FROM user_instructions WHERE instruction_id=?", (key,)).fetchone()
        return None if row is None else dict(row)
