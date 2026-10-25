"""Long-running host, exclusive state ownership, shutdown, and status snapshots."""
import json
import os
from pathlib import Path
import tempfile
import time

from .mqtt_source import InputRouter


class InstanceLock:
    def __init__(self, directory):
        self.path = Path(directory) / "runner.lock"
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0, 2)
                if self.stream.tell() == 0:
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError("another HomeVIS runner owns this data directory") from exc
        return self

    def __exit__(self, *args):
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def write_status(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".status-", suffix=".tmp", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class ContinuousHost:
    def __init__(self, settings, runtime, source, *, clock=time.time, monotonic=time.monotonic):
        self.settings, self.runtime, self.source = settings, runtime, source
        self.clock, self.monotonic = clock, monotonic
        self.router = InputRouter(settings.mqtt, runtime)
        self.status_path = settings.integration.outbox_path.parent / "status.json"
        self._next_status = self._next_prune = 0
        self._now = None
        self._connection_generation = 0

    def status(self, now, running=True):
        counts = {row[0]: row[1] for row in self.runtime.outbox.db.execute(
            "SELECT status, count(*) FROM decisions GROUP BY status")}
        return {"running": running, "updated_at": now, "mode": self.settings.integration.mode,
                "mqtt": self.source.health(), "backend_available": self.runtime._backend_ok,
                "sensing": self.runtime.sensing_health(now), "missing_inputs": self.runtime.missing_inputs,
                "state": None if self.runtime.last_decision is None else self.runtime.last_decision.state.value,
                "fall_state": None if self.runtime.controller.bathroom_decision is None else self.runtime.controller.bathroom_decision.state.value,
                "outbox": counts, "fall_incident": self.runtime.outbox.fall_incident(),
                "home_automation": self.runtime.home_automation.health(),
                "stove_temperature_validity_verified": self.runtime.config.stove_temperature_validity_verified,
                "voice": self.runtime.voice.health() if self.runtime.voice is not None else {"enabled": False},
                "fall_status_configured": bool(self.settings.integration.fall_status_path or self.settings.mqtt.fall_status_topic),
                "recent_diagnostics": [d["code"] for d in self.runtime.diagnostics[-10:]]}

    def step(self):
        # NTP corrections must not move the engine's processing clock backwards.
        now = self.clock()
        self._now = max(now, self._now if self._now is not None else now)
        generation = getattr(self.source, "connection_generation", 0)
        if generation != self._connection_generation:
            self._connection_generation = generation
            if self.runtime.voice is not None:
                self.runtime.voice.reconnect()
        for message in self.source.drain():
            self.router.accept(message)
        self.router.flush(self._now)
        self.runtime.run_once(self._now)
        if now >= self._next_status:
            status = self.status(self._now)
            write_status(self.status_path, status)
            print(json.dumps({key: status[key] for key in ("mode", "state", "backend_available", "outbox")},
                             ensure_ascii=True), flush=True)
            self._next_status = now + self.settings.status_interval
        if now >= self._next_prune:
            self.runtime.outbox.prune_audit(now - self.settings.audit_retention_days * 86400)
            self._next_prune = now + 3600

    def run(self, stop_event, duration=None):
        deadline = None if duration is None else self.monotonic() + duration
        try:
            self.source.start()
            while not stop_event.is_set() and (deadline is None or self.monotonic() < deadline):
                self.step()
                stop_event.wait(self.settings.tick_interval)
        finally:
            try:
                self.source.close()
            finally:
                try:
                    write_status(self.status_path, self.status(self._now or self.clock(), running=False))
                finally:
                    self.runtime.close()
