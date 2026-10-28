import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import pty
import re
import socket
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import pytest
from serial.tools.list_ports_common import ListPortInfo

from csi_capture.processing import export_processed, process_session
from local.collector import LocalCoordinator
from local.devices import DeviceRegistry


def packet(timestamp):
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerow(
        [timestamp, json.dumps([5, 30] * 64), -42, "aa:bb:cc:dd:ee:ff", 0, 128])
    return stream.getvalue().encode()


def until(predicate, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(.02)
    raise AssertionError("Local capture timed out")


class Feed:
    def __init__(self, interval=.01, noise=False):
        self.master, self.slave = pty.openpty()
        self.port = os.ttyname(self.slave)
        self.stop = threading.Event()
        self.thread = None
        self.interval, self.noise = interval, noise

    def start(self):
        os.set_blocking(self.master, False)
        def send():
            while not self.stop.is_set():
                raw = packet(int(time.monotonic() * 1e6) % 2**32)
                if self.noise:
                    raw = b"debug [not CSI]\n" + raw
                try:
                    os.write(self.master, raw[:41])
                    time.sleep(.0003)
                    os.write(self.master, raw[41:])
                except BlockingIOError:
                    pass
                self.stop.wait(self.interval)
        self.thread = threading.Thread(target=send)
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass


def coordinator(tmp_path, feeds):
    devices = [{"id": f"esp-{i:02d}", "port": feed.port, "baud": 115200}
               for i, feed in enumerate(feeds, 1)]
    return LocalCoordinator(tmp_path / "data", devices=devices, bindings=tmp_path / "bindings.json")


def completed(c, job):
    until(lambda: not c.busy)
    return c.snapshot()["jobs"][job["id"]]


def test_four_direct_usb_readers_have_independent_packet_quotas(tmp_path, monkeypatch):
    # The local path must work without opening an HTTP/TCP server or reading a token.
    def no_socket(*_args, **_kwargs):
        raise AssertionError("Direct USB collection attempted to open a network socket")
    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.delenv("CSI_TOKEN", raising=False)
    feeds = [Feed(interval, noise=True).start() for interval in (.003, .006, .01, .016)]
    c = None
    try:
        c = coordinator(tmp_path, feeds)
        job = c.create_job([("local", f"esp-{i:02d}") for i in range(1, 5)], .3, sample_count=30)
        done = completed(c, job)
        assert done["status"] == "completed", done["message"]
        assert done["capture_count"] == 80 and done["sample_count"] == 30
        assert re.fullmatch(r"none_\d{6}_\d{6}", done["id"])
        assert done["action"] == "none"
        reports = done["results"]["local"]["devices"]
        assert reports["esp-04"]["last_host_timestamp"] - reports["esp-01"]["last_host_timestamp"] > .5
        folder = c.root / job["id"]
        for i in range(1, 5):
            name = f"esp-{i:02d}"
            with (folder / f"{name}.raw.csv").open() as stream:
                raw = list(csv.DictReader(stream))
            with (folder / f"{name}.csv").open() as stream:
                kept = list(csv.DictReader(stream))
            assert len(raw) == 80 and len(kept) == 30
            first = next(csv.reader([raw[25]["raw_line"]]))[0]
            last = next(csv.reader([raw[54]["raw_line"]]))[0]
            assert kept[0]["local_timestamp"] == first and kept[-1]["local_timestamp"] == last
            assert all(float(row["host_timestamp"]) >= done["start_at"] for row in raw)
            assert reports[name]["rejected_rows"] > 0
        result = process_session(folder)
        assert len(result["series"]) == 4
        processed = export_processed(folder, result)
        for i in range(1, 5):
            with (processed / f"esp-{i:02d}.csv").open() as stream:
                assert len(list(csv.DictReader(stream))) == 30
    finally:
        if c:
            c.shutdown()
        for feed in feeds:
            feed.close()


def test_cancel_wait_preserves_empty_raw_files(tmp_path):
    feed = Feed().start()
    c = None
    try:
        c = coordinator(tmp_path, [feed])
        job = c.create_job([("local", "esp-01")], 5)
        until(lambda: c.snapshot()["jobs"][job["id"]]["status"] == "waiting")
        c.cancel(job["id"])
        done = completed(c, job)
        assert done["status"] == "cancelled"
        assert done["uploads"]["local/esp-01"]["accepted_rows"] == 0
        assert done["uploads"]["local/esp-01"]["retained_rows"] == 0
    finally:
        if c:
            c.shutdown()
        feed.close()


def test_local_no_csi_is_partial_not_fabricated_samples(tmp_path):
    feed = Feed()
    c = None
    try:
        c = coordinator(tmp_path, [feed])
        job = c.create_job([("local", "esp-01")], 0, sample_count=10,
                           timeout_seconds=2, idle_timeout_seconds=.3)
        done = completed(c, job)
        assert done["status"] == "partial"
        assert done["uploads"]["local/esp-01"]["retained_rows"] == 0
        assert done["results"]["local"]["devices"]["esp-01"]["error"]
    finally:
        if c:
            c.shutdown()
        feed.close()


def test_disconnected_board_does_not_stop_healthy_board(tmp_path):
    feeds = [Feed(.01).start(), Feed(.01).start()]
    c = None
    try:
        c = coordinator(tmp_path, feeds)
        job = c.create_job([("local", "esp-01"), ("local", "esp-02")], .2, sample_count=50)
        until(lambda: c.snapshot()["jobs"][job["id"]]["progress"]["local/esp-01"]["captured"] >= 5)
        feeds[0].close()
        done = completed(c, job)
        assert done["status"] == "partial"
        assert done["uploads"]["local/esp-02"]["retained_rows"] == 50
        assert done["results"]["local"]["devices"]["esp-01"]["error"]
    finally:
        if c:
            c.shutdown()
        for feed in feeds:
            feed.close()


def usb_info(port, serial):
    info = ListPortInfo(port)
    info.serial_number, info.vid, info.pid, info.location = serial, 0x303A, 0x1001, "1-1"
    return info


def test_auto_usb_names_survive_reconnection_and_tty_renumbering(tmp_path):
    present = [usb_info(f"/dev/ttyACM{i}", f"serial-{i}") for i in range(4)]
    registry = DeviceRegistry(tmp_path / "bindings.json", provider=lambda: present)
    before = registry.refresh()
    assert [d["id"] for d in before] == [f"esp-{i:02d}" for i in range(1, 5)]
    present[:] = [usb_info("/dev/ttyACM8", "serial-0"), usb_info("/dev/ttyACM0", "serial-3")]
    after = registry.refresh()
    by_name = {d["id"]: d for d in after}
    assert by_name["esp-01"]["port"] == "/dev/ttyACM8"
    assert by_name["esp-04"]["port"] == "/dev/ttyACM0"
    assert by_name["esp-02"]["online"] is False
    restarted = DeviceRegistry(tmp_path / "bindings.json", provider=lambda: present)
    assert {d["id"]: d["port"] for d in restarted.refresh()} == {d["id"]: d["port"] for d in after}


def test_duplicate_local_port_and_missing_board_are_rejected(tmp_path):
    feed = Feed()
    try:
        with pytest.raises(ValueError, match="동일한 USB"):
            LocalCoordinator(tmp_path / "data", devices=[{"id": "a", "port": feed.port},
                                                         {"id": "b", "port": feed.port}],
                             bindings=tmp_path / "bindings.json")
        c = LocalCoordinator(tmp_path / "other", devices=[{"id": "esp-01", "port": "/no/usb/device"}],
                             bindings=tmp_path / "other-bindings.json")
        with pytest.raises(ValueError, match="USB 연결"):
            c.create_job([("local", "esp-01")])
    finally:
        feed.close()


def test_local_headless_command_saves_named_files(tmp_path):
    feeds = [Feed(.004).start() for _ in range(4)]
    try:
        base = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-m", "local", "--headless", "--ports",
                                 *[feed.port for feed in feeds], "--samples", "10", "--wait", "0",
                                 "--action", "lie_down",
                                 "--data-dir", str(tmp_path / "data"),
                                 "--bindings", str(tmp_path / "bindings.json")],
                                cwd=base, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr + result.stdout
        folder = next((tmp_path / "data").glob("*/session.json")).parent
        assert re.fullmatch(r"lie_down_\d{6}_\d{6}", folder.name)
        assert json.loads((folder / "session.json").read_text())["action"] == "lie_down"
        assert len(list(folder.glob("esp-*.csv"))) == 8
        assert len(list((folder / "processed").glob("esp-*.csv"))) == 4
        assert "completed:" in result.stdout
    finally:
        for feed in feeds:
            feed.close()


@pytest.mark.parametrize("action", ["fall", "lie_down", "get_up", "none"])
def test_action_labels_name_the_session_and_survive_capture(tmp_path, action):
    feed = Feed(.003).start()
    c = None
    try:
        c = coordinator(tmp_path, [feed])
        job = c.create_job([("local", "esp-01")], 0, sample_count=2, action=action)
        expected = action + "_" + datetime.fromtimestamp(job["created_at"], ZoneInfo("Asia/Seoul")).strftime("%y%m%d_%H%M%S")
        assert job["id"] == expected
        done = completed(c, job)
        assert done["status"] == "completed", done["message"]
        folder = c.root / expected
        saved = json.loads((folder / "session.json").read_text())
        assert saved["action"] == action and saved["id"] == expected
        with (folder / "esp-01.csv").open() as stream:
            assert len(list(csv.DictReader(stream))) == 2
        assert (folder / "esp-01.raw.csv").exists()
    finally:
        if c:
            c.shutdown()
        feed.close()


def test_invalid_action_is_rejected_before_creating_files(tmp_path):
    c = LocalCoordinator(tmp_path / "data", devices=[], bindings=tmp_path / "bindings.json")
    with pytest.raises(ValueError, match="행동"):
        c.create_job([("local", "esp-01")], action="../fall")
    assert not list(c.root.iterdir())


def test_same_action_timestamp_never_overwrites_an_existing_folder(tmp_path, monkeypatch):
    # Includes folders without session.json: a previous interrupted save may have left raw files.
    class FixedDateTime:
        @staticmethod
        def fromtimestamp(_timestamp, tz):
            return datetime(2026, 10, 24, 19, 41, 30, tzinfo=tz)
    monkeypatch.setattr("local.collector.datetime", FixedDateTime)
    feed = Feed()
    try:
        c = coordinator(tmp_path, [feed])
        folder = c.root / "lie_down_261024_194130"
        folder.mkdir()
        raw = folder / "esp-01.raw.csv"
        raw.write_text("keep existing capture\n")
        with pytest.raises(ValueError, match="1초"):
            c.create_job([("local", "esp-01")], action="lie_down")
        assert raw.read_text() == "keep existing capture\n"
        assert not (folder / "session.json").exists()
        assert not c.busy
    finally:
        feed.close()
