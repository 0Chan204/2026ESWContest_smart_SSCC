"""Laptop coordinator. The desktop and optional headless mode share this server."""
import argparse
import copy
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .serial_format import normalize_capture
from .config import load_token, validate_token

ACTIVE = {"preparing", "waiting", "collecting", "uploading"}
IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}$")


def identifier(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("IDs must contain 1–64 ASCII letters, digits, _ or -")
    return value


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


class Coordinator:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.agents = {}
        self.jobs = {}
        for path in sorted(self.root.glob("*/session.json")):
            job = json.loads(path.read_text())
            if job["status"] in ACTIVE:
                job["status"] = "interrupted"
                job["message"] = "Laptop server restarted; pending Pi uploads can still be recovered."
            self.jobs[job["id"]] = job
            self.save(job)

    def save(self, job):
        atomic_write(self.root / job["id"] / "session.json", json.dumps(job, indent=2).encode())

    def refresh(self):
        now = time.time()
        for job in self.jobs.values():
            old = job["status"]
            if old == "preparing" and now - job["created_at"] > 30:
                job.update(status="failed", message="Pi preparation timed out (30 seconds).")
            elif old in {"waiting", "collecting", "uploading"}:
                if now > job["end_at"] + 60:
                    job.update(status="partial", message="Some Pi results are missing; late uploads are accepted.")
                elif job.get("capture_mode") == "samples":
                    if now >= job["start_at"]:
                        job["status"] = "collecting"
                        finished = all(job.get("progress", {}).get(f'{d["pi_id"]}/{d["id"]}', {}).get("finished")
                                       for d in job["devices"])
                        if finished or now >= job["end_at"]:
                            job["status"] = "uploading"
                elif now >= job["end_at"]:
                    job["status"] = "uploading"
                elif now >= job["start_at"]:
                    job["status"] = "collecting"
            if job["status"] != old:
                self.save(job)

    def snapshot(self):
        with self.lock:
            self.refresh()
            return copy.deepcopy({"agents": self.agents, "jobs": self.jobs, "server_time": time.time()})

    def create_job(self, selected, wait_seconds=5, duration_seconds=None, *, sample_count=500,
                   trim_each=25, timeout_seconds=600, idle_timeout_seconds=10):
        with self.lock:
            self.refresh()
            if any(j["status"] in ACTIVE for j in self.jobs.values()):
                raise ValueError("A collection is already active")
            wait_seconds = float(wait_seconds)
            if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 3600:
                raise ValueError("Wait: 0–3600 seconds")
            sample_mode = duration_seconds is None
            if sample_mode:
                if (isinstance(sample_count, bool) or int(sample_count) != sample_count
                        or not 2 <= sample_count <= 20000 or trim_each != 25):
                    raise ValueError("Final sample count: integer 2–20000; trim: 25 per end")
                sample_count = int(sample_count)
                if not (math.isfinite(timeout_seconds) and 1 <= timeout_seconds <= 7200
                        and math.isfinite(idle_timeout_seconds) and .2 <= idle_timeout_seconds <= timeout_seconds):
                    raise ValueError("Invalid failure timeout")
            else:
                duration_seconds = float(duration_seconds)
                if not math.isfinite(duration_seconds) or not .1 <= duration_seconds <= 600:
                    raise ValueError("Legacy collection duration: 0.1–600 seconds")
            if not selected or len(set(selected)) != len(selected):
                raise ValueError("Select at least one distinct ESP32")
            devices = []
            for pi_id, device_id in selected:
                agent = self.agents.get(pi_id)
                if not agent or time.time() - agent["last_seen"] > 5 or agent["busy"]:
                    raise ValueError(f"{pi_id} is offline or still uploading")
                device = next((d for d in agent["devices"] if d["id"] == device_id), None)
                if not device:
                    raise ValueError(f"Unknown device: {pi_id}/{device_id}")
                if sample_mode and agent.get("capture_protocol", 0) < 2:
                    raise ValueError(f"{pi_id}: Pi 에이전트를 업데이트하고 다시 빌드하세요 (패킷 개수 수집 지원 필요).")
                devices.append({**device, "pi_id": pi_id})
            job = {"id": secrets.token_hex(12), "created_at": time.time(), "status": "preparing",
                   "wait_seconds": wait_seconds, "duration_seconds": duration_seconds,
                   "devices": devices, "ready": {}, "results": {}, "uploads": {},
                   "start_at": None, "end_at": None, "message": "", "progress": {}}
            if sample_mode:
                job.update(capture_mode="samples", sample_count=sample_count, trim_each=trim_each,
                           capture_count=sample_count + 2 * trim_each, timeout_seconds=timeout_seconds,
                           idle_timeout_seconds=idle_timeout_seconds)
            self.jobs[job["id"]] = job
            self.save(job)
            return copy.deepcopy(job)

    def heartbeat(self, data):
        with self.lock:
            self.refresh()
            pi_id = identifier(data["pi_id"])
            devices = data["devices"]
            if not isinstance(devices, list) or not 1 <= len(devices) <= 64:
                raise ValueError("Configure 1–64 devices per Pi")
            seen = set()
            for d in devices:
                identifier(d["id"])
                if d["id"] in seen:
                    raise ValueError("Duplicate device ID")
                seen.add(d["id"])
            self.agents[pi_id] = {"devices": devices, "last_seen": time.time(), "busy": bool(data.get("busy")),
                                  "capture_protocol": data.get("capture_protocol", 0)}
            progress = data.get("progress") or {}
            if progress.get("job_id") in self.jobs:
                job = self.get_job_pi(progress["job_id"], pi_id)
                for device_id, state in progress.get("devices", {}).items():
                    if any(d["pi_id"] == pi_id and d["id"] == device_id for d in job["devices"]):
                        count = int(state.get("captured", 0))
                        job.setdefault("progress", {})[f"{pi_id}/{device_id}"] = {
                            "captured": max(0, count), "finished": bool(state.get("finished"))}
            command = None
            for job in reversed(list(self.jobs.values())):
                if any(d["pi_id"] == pi_id for d in job["devices"]):
                    if job["status"] in ACTIVE or data.get("job_id") == job["id"]:
                        command = {k: job[k] for k in ("id", "status", "start_at", "end_at", "duration_seconds")}
                        for key in ("capture_mode", "sample_count", "trim_each", "capture_count", "idle_timeout_seconds"):
                            if key in job:
                                command[key] = job[key]
                        command["devices"] = [d for d in job["devices"] if d["pi_id"] == pi_id]
                        break
            return {"server_time": time.time(), "command": command}

    def get_job_pi(self, job_id, pi_id):
        job = self.jobs[identifier(job_id)]
        if pi_id not in {d["pi_id"] for d in job["devices"]}:
            raise ValueError("Pi is not part of this session")
        return job

    def ready(self, data):
        with self.lock:
            job = self.get_job_pi(data["job_id"], data["pi_id"])
            if job["status"] == "preparing":
                job["ready"][data["pi_id"]] = data
                if data.get("error"):
                    job.update(status="failed", message=str(data["error"]))
                elif set(job["ready"]) == {d["pi_id"] for d in job["devices"]}:
                    # For zero delay, 0.5 seconds is a command-distribution guard.
                    job["start_at"] = time.time() + max(job["wait_seconds"], 0.5)
                    limit = job["timeout_seconds"] if job.get("capture_mode") == "samples" else job["duration_seconds"]
                    job["end_at"] = job["start_at"] + limit
                    job["status"] = "waiting"
                self.save(job)
            return {"ok": True}

    def upload(self, job_id, pi_id, device_id, raw):
        identifier(pi_id)
        identifier(device_id)
        digest = hashlib.sha256(raw).hexdigest()
        with self.lock:
            job = self.get_job_pi(job_id, pi_id)
            if not any(d["pi_id"] == pi_id and d["id"] == device_id for d in job["devices"]):
                raise ValueError("ESP32 is not selected")
            key = f"{pi_id}/{device_id}"
            prior = job["uploads"].get(key)
            if prior:
                if prior["sha256"] != digest:
                    raise ValueError("Conflicting repeat upload")
                return {"ok": True, **prior}
            if job.get("capture_mode") == "samples":
                normalized, quality = normalize_capture(raw, trim_each=job["trim_each"], sample_count=job["sample_count"])
                job.setdefault("progress", {})[key] = {"captured": quality["accepted_rows"], "finished": True}
            else:
                normalized, quality = normalize_capture(raw)
            path = self.root / job_id / pi_id
            atomic_write(path / f"{device_id}.raw.csv", raw)
            atomic_write(path / f"{device_id}.csv", normalized)
            job["uploads"][key] = {"sha256": digest, **quality}
            self.save(job)
            return {"ok": True, **quality}

    def complete(self, data):
        with self.lock:
            job = self.get_job_pi(data["job_id"], data["pi_id"])
            expected = {d["id"] for d in job["devices"] if d["pi_id"] == data["pi_id"]}
            if set(data["devices"]) != expected:
                raise ValueError("Incomplete device report")
            if any(f'{data["pi_id"]}/{device}' not in job["uploads"]
                   and not data["devices"][device].get("error") for device in expected):
                raise ValueError("Upload every device file before completing")
            job["results"][data["pi_id"]] = data
            if set(job["results"]) == {d["pi_id"] for d in job["devices"]}:
                errors = any(d.get("error") for r in job["results"].values() for d in r["devices"].values())
                enough = len(job["uploads"]) == len(job["devices"]) and all(u["accepted_rows"] >= 2 for u in job["uploads"].values())
                if job.get("capture_mode") == "samples":
                    enough = len(job["uploads"]) == len(job["devices"]) and all(
                        u.get("retained_rows") == job["sample_count"]
                        and u["accepted_rows"] == job["capture_count"] for u in job["uploads"].values())
                if job["status"] not in {"cancelled", "failed"}:
                    job["status"] = "completed" if enough and not errors else "partial"
                job["received_at"] = time.time()
            self.save(job)
            return {"ok": True}

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job["status"] in ACTIVE:
                job.update(status="cancelled", message="Cancelled by user; partial data will be uploaded.")
                self.save(job)


def make_server(coordinator, host="0.0.0.0", port=8765, token=None):
    token = load_token() if token is None else validate_token(token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.connection.settimeout(30)
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.reply(401, {"error": "Invalid access token"})
                return
            try:
                route = urlsplit(self.path).path
                limit = 64 * 1024 * 1024 if route.startswith("/api/upload/") else 128 * 1024
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= limit:
                    raise ValueError("Request size out of range")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Truncated request")
                if route.startswith("/api/upload/"):
                    parts = route.split("/")
                    if len(parts) != 6:
                        raise ValueError("Invalid upload route")
                    result = coordinator.upload(*parts[3:], body)
                else:
                    data = json.loads(body)
                    routes = {"/api/heartbeat": coordinator.heartbeat, "/api/ready": coordinator.ready,
                              "/api/complete": coordinator.complete}
                    if route not in routes:
                        self.reply(404, {"error": "Unknown endpoint"})
                        return
                    result = routes[route](data)
                self.reply(200, result)
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                self.reply(400, {"error": str(exc)})
            except OSError as exc:
                self.reply(503, {"error": str(exc)})

        def reply(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.token = token
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    try:
        server = make_server(Coordinator(args.data_dir), args.host, args.port)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"CSI server {args.host}:{server.server_port}; token: {server.token}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
