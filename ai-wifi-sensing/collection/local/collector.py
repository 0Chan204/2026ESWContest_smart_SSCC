"""Parallel USB collection directly on the laptop; no network server is opened."""
import copy
import csv
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

import serial

from csi_capture.serial_format import normalize_capture, parse_line
from csi_capture.server import ACTIVE, atomic_write
from .devices import DeviceRegistry

BASE = Path(__file__).resolve().parent
ACTIONS = ("fall", "lie_down", "get_up", "none")
MAX_LINE_BYTES = 32768
MAX_CAPTURE_BYTES = 48 * 1024 * 1024


class USBReader(threading.Thread):
    def __init__(self, owner, job, device, schedule, cancel):
        super().__init__(name=f'USB-{device["id"]}', daemon=True)
        self.owner, self.job, self.device = owner, job, device
        self.schedule, self.cancel = schedule, cancel
        self.ready = threading.Event()
        self.error = ""
        self.captured = self.rejected = 0
        self.first = self.last = 0.0
        self.mac = device.get("target_mac", "").strip().lower()
        self.raw_path = owner.root / job["id"] / f'{device["id"]}.raw.csv'

    def run(self):
        port = None
        try:
            with self.raw_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["host_timestamp", "raw_line"])
                try:
                    port = serial.Serial(self.device.get("open_port", self.device["port"]),
                                         baudrate=self.device.get("baud", 115200), timeout=.05,
                                         exclusive=True)
                    port.reset_input_buffer()
                    self.ready.set()
                    buffer = bytearray()
                    dropping = recording = False
                    last_packet = last_flush = time.monotonic()
                    while not self.cancel.is_set() and self.captured < self.job["capture_count"]:
                        now = time.monotonic()
                        start = self.schedule.get("start_mono")
                        if start is not None and now >= start:
                            if now >= start + self.job["timeout_seconds"]:
                                self.error = "전체 수집 제한 시간 내 목표 개수를 채우지 못했습니다."
                                break
                            if now - max(start, last_packet) >= self.job["idle_timeout_seconds"]:
                                self.error = "유효 CSI가 수신되지 않아 대기 제한 시간을 초과했습니다."
                                break
                            if not recording:
                                # Start at a new USB line after continuously draining during the wait.
                                port.reset_input_buffer()
                                buffer.clear()
                                recording = True
                        chunk = port.read(min(max(port.in_waiting, 1), 16384))
                        if not recording:
                            buffer.clear()
                            continue
                        buffer.extend(chunk)
                        while b"\n" in buffer:
                            raw, _, remainder = buffer.partition(b"\n")
                            buffer = bytearray(remainder)
                            if dropping or len(raw) > MAX_LINE_BYTES:
                                self.rejected += 1
                                dropping = False
                                continue
                            line = raw.decode("utf-8", errors="replace").rstrip("\r")
                            packet = parse_line(line)
                            if packet is None or (self.mac and packet[3] != self.mac):
                                self.rejected += 1
                                continue
                            if not self.mac:
                                self.mac = packet[3]
                            now = time.monotonic()
                            stamp = self.schedule["epoch_offset"] + now
                            writer.writerow([f"{stamp:.6f}", line])
                            self.captured += 1
                            if self.captured == 1:
                                self.first = stamp
                            self.last, last_packet = stamp, now
                            with self.owner.lock:
                                self.job["progress"][f'local/{self.device["id"]}']["captured"] = self.captured
                            if stream.tell() > MAX_CAPTURE_BYTES:
                                self.error = "장치당 원본 저장 크기 48 MiB를 초과했습니다."
                                break
                            if self.captured >= self.job["capture_count"]:
                                break
                        if len(buffer) > MAX_LINE_BYTES:
                            buffer.clear()
                            dropping = True
                        if self.error:
                            break
                        if time.monotonic() - last_flush >= 1:
                            stream.flush()
                            last_flush = time.monotonic()
                finally:
                    stream.flush()
                    os.fsync(stream.fileno())
        except (OSError, serial.SerialException, ValueError) as exc:
            self.error = f'{self.device["id"]} ({self.device["port"]}): {exc}'
        finally:
            if port is not None:
                port.close()
            self.ready.set()
            with self.owner.lock:
                self.job["progress"][f'local/{self.device["id"]}']["finished"] = True

    def report(self):
        return {"raw_rows": self.captured, "rejected_rows": self.rejected,
                "first_host_timestamp": self.first, "last_host_timestamp": self.last,
                "target_mac": self.mac, "error": self.error}


class LocalCoordinator:
    def __init__(self, root=BASE / "data", *, devices=None, baud=115200,
                 bindings=BASE / "device_bindings.json", port_provider=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.registry = DeviceRegistry(bindings, devices=devices, baud=baud, provider=port_provider)
        self.devices = []
        self.jobs = {}
        self.discovery_error = ""
        self._scan_at = 0.0
        self._thread = None
        self._cancel = threading.Event()
        self._active_id = None
        for path in self.root.glob("*/session.json"):
            job = json.loads(path.read_text())
            if job["status"] in ACTIVE:
                job.update(status="interrupted", message="이전 노트북 수집이 정상 종료되지 않았습니다.")
                self.save(job)
            self.jobs[job["id"]] = job
        self.refresh_devices()

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def save(self, job):
        atomic_write(self.root / job["id"] / "session.json",
                     json.dumps(job, ensure_ascii=False, indent=2).encode())

    def refresh_devices(self):
        with self.lock:
            if not self.busy:
                try:
                    self.devices = self.registry.refresh()
                    self.discovery_error = ""
                except OSError as exc:
                    self.discovery_error = f"USB 검색 오류: {exc}"
                self._scan_at = time.monotonic()
            return copy.deepcopy(self.devices)

    def snapshot(self):
        with self.lock:
            if not self.busy and time.monotonic() - self._scan_at >= 2:
                self.refresh_devices()
            return copy.deepcopy({"agents": {"local": {"devices": self.devices, "last_seen": time.time(),
                                                        "busy": self.busy, "capture_protocol": 2}},
                                  "jobs": self.jobs, "server_time": time.time()})

    def create_job(self, selected, wait_seconds=5, *, sample_count=500, timeout_seconds=600,
                   idle_timeout_seconds=10, action="none"):
        with self.lock:
            if self.busy:
                raise ValueError("이미 수집 중입니다.")
            if action not in ACTIONS:
                raise ValueError("행동은 fall, lie_down, get_up, none 중에서 선택하세요.")
            wait_seconds = float(wait_seconds)
            if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 3600:
                raise ValueError("대기 시간은 0–3600초로 지정하세요.")
            if isinstance(sample_count, bool) or int(sample_count) != sample_count or not 2 <= sample_count <= 20000:
                raise ValueError("최종 수집 길이는 2–20000 사이의 정수로 지정하세요.")
            if not (math.isfinite(timeout_seconds) and 1 <= timeout_seconds <= 7200
                    and math.isfinite(idle_timeout_seconds) and .2 <= idle_timeout_seconds <= timeout_seconds):
                raise ValueError("오류 방지 제한 시간이 올바르지 않습니다.")
            if not selected or len(set(selected)) != len(selected):
                raise ValueError("수집할 ESP32를 선택하세요.")
            self.refresh_devices()
            devices = []
            for host, name in selected:
                device = next((d for d in self.devices if d["id"] == name), None)
                if host != "local" or not device or not device["online"]:
                    raise ValueError(f"{name}: USB 연결을 확인하고 새로고침하세요.")
                devices.append({**device, "pi_id": "local", "file": f"{name}.csv"})
            now = time.time()
            stamp = datetime.fromtimestamp(now, ZoneInfo("Asia/Seoul")).strftime("%y%m%d_%H%M%S")
            job_id = f"{action}_{stamp}"
            if job_id in self.jobs or (self.root / job_id).exists():
                raise ValueError("같은 행동과 시각의 폴더가 이미 있습니다. 1초 후 다시 시작하세요.")
            job = {"id": job_id, "source": "local_usb", "action": action, "created_at": now, "status": "preparing",
                   "capture_mode": "samples", "duration_seconds": None, "wait_seconds": wait_seconds,
                   "sample_count": int(sample_count), "trim_each": 25, "capture_count": int(sample_count) + 50,
                   "timeout_seconds": timeout_seconds, "idle_timeout_seconds": idle_timeout_seconds,
                   "devices": devices, "start_at": None, "end_at": None, "message": "",
                   "results": {}, "uploads": {}, "progress": {
                       f'local/{d["id"]}': {"captured": 0, "finished": False} for d in devices}}
            self.jobs[job_id] = job
            self.save(job)
            self._cancel = threading.Event()
            self._active_id = job_id
            self._thread = threading.Thread(target=self._run_job, args=(job, self._cancel), daemon=True)
            self._thread.start()
            return copy.deepcopy(job)

    def _run_job(self, job, cancel):
        schedule = {"epoch_offset": time.time() - time.monotonic()}
        readers = [USBReader(self, job, device, schedule, cancel) for device in job["devices"]]
        preparation_error = ""
        try:
            for reader in readers:
                reader.start()
            deadline = time.monotonic() + 30
            while not all(reader.ready.is_set() for reader in readers) and not cancel.is_set():
                if time.monotonic() >= deadline:
                    preparation_error = "USB 연결 준비가 30초를 초과했습니다."
                    break
                time.sleep(.02)
            preparation_error = preparation_error or "; ".join(reader.error for reader in readers if reader.error)
            if preparation_error:
                cancel.set()
            elif not cancel.is_set():
                with self.lock:
                    schedule["start_mono"] = time.monotonic() + job["wait_seconds"]
                    job["start_at"] = schedule["epoch_offset"] + schedule["start_mono"]
                    job["end_at"] = job["start_at"] + job["timeout_seconds"]
                    job["status"] = "waiting"
                    self.save(job)
            while any(reader.is_alive() for reader in readers):
                with self.lock:
                    if job["start_at"] is not None and time.monotonic() >= schedule["start_mono"]:
                        if job["status"] == "waiting":
                            job["status"] = "collecting"
                            self.save(job)
                time.sleep(.02)
            for reader in readers:
                reader.join()
            with self.lock:
                job["status"] = "uploading"
                self.save(job)
            reports = {}
            for reader in readers:
                report = reader.report()
                try:
                    raw = reader.raw_path.read_bytes()
                    normalized, quality = normalize_capture(raw, trim_each=25, sample_count=job["sample_count"])
                    atomic_write(self.root / job["id"] / f'{reader.device["id"]}.csv', normalized)
                    with self.lock:
                        job["uploads"][f'local/{reader.device["id"]}'] = {
                            "sha256": hashlib.sha256(raw).hexdigest(), **quality}
                except (OSError, ValueError) as exc:
                    report["error"] = f"결과 저장 실패: {exc}"
                reports[reader.device["id"]] = report
            with self.lock:
                job["results"] = {"local": {"devices": reports}}
                enough = len(job["uploads"]) == len(readers) and all(
                    value["accepted_rows"] == job["capture_count"] and value["retained_rows"] == job["sample_count"]
                    for value in job["uploads"].values())
                errors = [report["error"] for report in reports.values() if report["error"]]
                if preparation_error:
                    job.update(status="failed", message=preparation_error)
                elif cancel.is_set():
                    job.update(status="cancelled", message="수집을 취소했습니다. 수집된 원본은 보존했습니다.")
                else:
                    job.update(status="completed" if enough and not errors else "partial", message="; ".join(errors))
                job["received_at"] = time.time()
                job["finished_at"] = max((reader.last for reader in readers), default=0) or time.time()
                self.save(job)
        except Exception as exc:
            cancel.set()
            for reader in readers:
                if reader.ident is not None:
                    reader.join(timeout=2)
            with self.lock:
                job.update(status="failed", message=f"노트북 수집 오류: {exc}")
                self.save(job)
        finally:
            with self.lock:
                self._active_id = None

    def cancel(self, job_id):
        with self.lock:
            if self._active_id == job_id and self.jobs[job_id]["status"] in ACTIVE:
                self.jobs[job_id]["message"] = "수집을 취소하고 결과를 저장하는 중입니다."
                self._cancel.set()

    def shutdown(self, wait=True):
        with self.lock:
            self._cancel.set()
            worker = self._thread
        if wait and worker is not None:
            worker.join(timeout=10)
