import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from csi_capture.processing import process_session
from csi_capture.serial_format import HEADER, normalize_capture, parse_line
from csi_capture.server import Coordinator, make_server
from csi_capture.vendor.ai_wifi_pipeline import CSIDataProcessor, ProcessingConfig

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "pi_agent/csi-agent"


def line(timestamp=100000, rssi=-42):
    stream = io.StringIO()
    csv.writer(stream, lineterminator="").writerow([timestamp, json.dumps([5, 30] * 64), rssi, "AA:BB:CC:DD:EE:FF", 0, 128])
    return stream.getvalue()


def until(predicate, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(.025)
    raise AssertionError("Timed out")


@contextlib.contextmanager
def running_server(tmp_path, port=0):
    c = Coordinator(tmp_path / "sessions")
    s = make_server(c, "127.0.0.1", port, "test-token")
    thread = threading.Thread(target=s.serve_forever, daemon=True)
    thread.start()
    try:
        yield c, s
    finally:
        s.shutdown()
        s.server_close()
        thread.join()


@contextlib.contextmanager
def agent(tmp_path, server, pi_id="pi-01", ports=None, config_path=None, env_file=None, extra_env=None):
    if config_path is None:
        config_path = tmp_path / (pi_id + ".json")
        config_path.write_text(json.dumps({
            "server": f"http://127.0.0.1:{server.server_port}", "token": "test-token", "pi_id": pi_id,
            "spool_dir": str(tmp_path / ("spool-" + pi_id)),
            "devices": [{"id": f"esp-{i+1:02d}", "port": p, "baud": 115200}
                        for i, p in enumerate(ports or ["sim1", "sim2"])]}))
    log = (tmp_path / (pi_id + ".log")).open("a")
    env = dict(os.environ, CSI_TOKEN="test-token")
    if env_file is not None:
        env.pop("CSI_TOKEN", None)
        env["CSI_ENV_FILE"] = str(env_file)
    env.update(extra_env or {})
    process = subprocess.Popen([str(BINARY), str(config_path), *([] if ports else ["--simulate"])],
                               stderr=log, env=env)
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


def test_both_firmware_formats_and_invalid_lines():
    parsed = parse_line(line())
    assert parsed[0] == 100000 and parsed[3] == "aa:bb:cc:dd:ee:ff"
    standard = ["0"] * 25
    for index, value in {0: "CSI_DATA", 2: parsed[3], 3: "-42", 18: "100000", 22: "128", 23: "0", 24: parsed[1]}.items():
        standard[index] = value
    stream = io.StringIO()
    csv.writer(stream).writerow(standard)
    assert parse_line(stream.getvalue()) == parsed
    assert parse_line("booting ESP32...") is None
    assert parse_line(line().replace("128", "126")) is None
    assert parse_line(line(rssi="nan")) is None
    assert parse_line(line(timestamp=-1)) is None


def test_normalize_preserves_quotes_and_counts():
    raw = io.StringIO()
    writer = csv.writer(raw)
    writer.writerow(["host_timestamp", "raw_line"])
    writer.writerow([123.5, line()])
    writer.writerow([124, "broken packet ["])
    data, counts = normalize_capture(raw.getvalue().encode())
    rows = list(csv.reader(io.StringIO(data.decode())))
    assert rows[0] == HEADER and len(rows) == 2
    assert counts == {"accepted_rows": 1, "skipped_rows": 1}


def test_pipeline_snapshot_is_exact():
    # Verify the reference snapshot even in a standalone collection checkout.
    snapshot = (ROOT / "csi_capture/vendor/ai_wifi_pipeline.py").read_bytes()
    assert hashlib.sha256(snapshot).hexdigest() == "ef3a40b85855774ce7b8d003808ddb8efa63038d55998334446f113a7336180c"


def test_selection_defaults_and_validation(tmp_path):
    c = Coordinator(tmp_path)
    c.heartbeat({"pi_id": "pi-01", "devices": [{"id": "esp-01"}], "busy": False, "capture_protocol": 2})
    with pytest.raises(ValueError):
        c.create_job([])
    with pytest.raises(ValueError):
        c.create_job([("pi-01", "missing")])
    with pytest.raises(ValueError):
        c.create_job([("pi-01", "esp-01")], float("nan"), 5)
    job = c.create_job([("pi-01", "esp-01")])
    assert job["wait_seconds"] == 5 and job["duration_seconds"] is None
    assert job["sample_count"] == 500 and job["capture_count"] == 550 and job["trim_each"] == 25
    with pytest.raises(ValueError):
        c.create_job([("pi-01", "esp-01")])


def test_upload_authentication(tmp_path):
    with running_server(tmp_path) as (_c, s):
        request = urllib.request.Request(f"http://127.0.0.1:{s.server_port}/api/heartbeat", data=b"{}")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request)
        assert exc.value.code == 401


def test_multi_pi_c_agents_and_exact_processing(tmp_path):
    with running_server(tmp_path) as (c, s), agent(tmp_path, s), agent(tmp_path, s, "pi-02"):
        until(lambda: len(c.snapshot()["agents"]) == 2)
        chosen = [(p, d) for p in ("pi-01", "pi-02") for d in ("esp-01", "esp-02")]
        job = c.create_job(chosen, .6, 1.4)
        done = until(lambda: (j if (j := c.snapshot()["jobs"][job["id"]])["status"] == "completed" else None))
        assert len(done["uploads"]) == 4
        assert done["end_at"] - done["start_at"] == pytest.approx(1.4)
        folder = c.root / job["id"]
        result = process_session(folder)
        assert len(result["series"]) == 4
        for key, series in result["series"].items():
            assert len(series["time"]) >= 28
            assert series["amp"].shape[1] == 52
            assert np.all(series["time"] >= 0) and np.all(series["time"] < 1.4)
            report = done["results"][key.split("/")[0]]["devices"][key.split("/")[1]]
            assert report["first_host_timestamp"] >= done["start_at"]
            assert report["last_host_timestamp"] < done["end_at"]
        # Identical repeat accepted, altered repeat rejected.
        raw = (folder / "pi-01/esp-01.raw.csv").read_bytes()
        assert c.upload(job["id"], "pi-01", "esp-01", raw)["ok"]
        with pytest.raises(ValueError):
            c.upload(job["id"], "pi-01", "esp-01", raw + b"\n")


def test_usb_pty_reader_split_lines_and_wait_boundary(tmp_path):
    master, slave = pty.openpty()
    stopped = threading.Event()
    def writer():
        while not stopped.is_set():
            text = (line(int(time.monotonic() * 1e6) % 2**32) + "\r\n").encode()
            os.write(master, text[:37])
            time.sleep(.001)
            os.write(master, text[37:])
            time.sleep(.019)
    thread = threading.Thread(target=writer)
    thread.start()
    try:
        with running_server(tmp_path) as (c, s), agent(tmp_path, s, ports=[os.ttyname(slave)]):
            until(lambda: c.snapshot()["agents"])
            job = c.create_job([("pi-01", "esp-01")], .6, 1)
            done = until(lambda: (j if (j := c.snapshot()["jobs"][job["id"]])["status"] == "completed" else None))
            assert done["uploads"]["pi-01/esp-01"]["accepted_rows"] >= 30
            rows = list(csv.DictReader((c.root / job["id"] / "pi-01/esp-01.csv").open()))
            assert all(done["start_at"] <= float(r["host_timestamp"]) < done["end_at"] for r in rows)
    finally:
        stopped.set()
        thread.join()
        os.close(master)
        os.close(slave)


def test_cancel_during_wait_uploads_empty_result(tmp_path):
    with running_server(tmp_path) as (c, s), agent(tmp_path, s):
        until(lambda: c.snapshot()["agents"])
        job = c.create_job([("pi-01", "esp-01")], 5, 1)
        until(lambda: c.snapshot()["jobs"][job["id"]]["status"] == "waiting")
        c.cancel(job["id"])
        until(lambda: c.snapshot()["jobs"][job["id"]]["results"])
        done = c.snapshot()["jobs"][job["id"]]
        assert done["status"] == "cancelled"
        assert done["uploads"]["pi-01/esp-01"]["accepted_rows"] == 0


def test_usb_open_failure_reports_all_selected_devices(tmp_path):
    with running_server(tmp_path) as (c, s), agent(tmp_path, s, ports=["/no/device1", "/no/device2"]):
        until(lambda: c.snapshot()["agents"])
        job = c.create_job([("pi-01", "esp-01"), ("pi-01", "esp-02")])
        until(lambda: c.snapshot()["jobs"][job["id"]]["results"])
        done = c.snapshot()["jobs"][job["id"]]
        assert done["status"] == "failed"
        assert len(done["results"]["pi-01"]["devices"]) == 2


def test_network_outage_retains_spool_and_recovers(tmp_path):
    # Restart the laptop server while the C reader keeps collecting on its own clock.
    c = Coordinator(tmp_path / "sessions")
    s = make_server(c, "127.0.0.1", 0, "test-token")
    port = s.server_port
    thread = threading.Thread(target=s.serve_forever, daemon=True)
    thread.start()
    try:
        with agent(tmp_path, s) as process:
            until(lambda: c.snapshot()["agents"])
            job = c.create_job([("pi-01", "esp-01")], .6, 1)
            until(lambda: c.snapshot()["jobs"][job["id"]]["status"] == "collecting")
            s.shutdown()
            s.server_close()
            thread.join()
            manifest = tmp_path / "spool-pi-01" / job["id"] / "result.json"
            until(manifest.exists)
            # Agent restart exercises durable spool discovery too.
            process.terminate()
            process.wait(timeout=6)
        with running_server(tmp_path, port) as (restarted, s2), agent(tmp_path, s2):
            until(lambda: restarted.snapshot()["jobs"][job["id"]]["status"] == "completed")
            assert (manifest.parent / "uploaded").exists() or until((manifest.parent / "uploaded").exists)
    finally:
        s.shutdown()
        s.server_close()


def test_gap_mask_and_first_word_repair(tmp_path):
    from csi_capture.vendor.ai_wifi_pipeline import parse_csi_amplitude
    values = [3, 4] * 64
    values[2:4] = [120, 120]
    assert parse_csi_amplitude(json.dumps(values), True)[26] == 5
    t = np.r_[np.arange(0, .5, .04), np.arange(1.5, 2, .04)]
    result = CSIDataProcessor(ProcessingConfig()).preprocess(t, np.ones((len(t), 52)), np.full(len(t), -40.0))
    assert not result["valid"][(result["ticks"] / 25 > .5) & (result["ticks"] / 25 < 1.5)].any()


def test_reject_unselected_pi_and_path_traversal(tmp_path):
    c = Coordinator(tmp_path)
    c.heartbeat({"pi_id": "pi-01", "devices": [{"id": "esp-01"}], "capture_protocol": 2})
    job = c.create_job([("pi-01", "esp-01")])
    with pytest.raises(ValueError):
        c.upload(job["id"], "../other", "esp-01", b"bad")
    with pytest.raises(ValueError):
        c.ready({"job_id": job["id"], "pi_id": "pi-02"})


def test_fixed_env_token_survives_server_restart(tmp_path, monkeypatch):
    from csi_capture import config
    monkeypatch.delenv("CSI_TOKEN", raising=False)
    monkeypatch.delenv("CSI_ENV_FILE", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text('# team token\nexport CSI_TOKEN="fixed-team-token" # comment\n')
    monkeypatch.chdir(tmp_path.parent)
    tokens = []
    for _ in range(2):
        server = make_server(Coordinator(tmp_path / "data"), "127.0.0.1", 0)
        tokens.append(server.token)
        server.server_close()
    assert tokens == ["fixed-team-token", "fixed-team-token"]


def test_env_token_validation_and_precedence(tmp_path):
    from csi_capture.config import load_token
    path = tmp_path / ".env"
    with pytest.raises(ValueError, match="Set CSI_TOKEN"):
        load_token(path, environ={})
    path.write_text("CSI_TOKEN='file-token'\n")
    assert load_token(path, environ={}) == "file-token"
    assert load_token(path, environ={"CSI_TOKEN": "exported-token"}) == "exported-token"
    assert load_token(environ={"CSI_ENV_FILE": str(path)}) == "file-token"
    with pytest.raises(ValueError):
        load_token(path, environ={"CSI_TOKEN": ""})
    path.write_text("CSI_TOKEN='unfinished\n")
    with pytest.raises(ValueError):
        load_token(path, environ={})
    path.write_text("CSI_TOKEN=invalid token\n")
    with pytest.raises(ValueError):
        load_token(path, environ={})


@pytest.mark.parametrize("value", ["test-token", "'test-token'", '"test-token" # team'])
def test_c_agent_reads_shared_env_instead_of_old_json_token(tmp_path, value):
    from csi_capture.config import load_token
    env_file = tmp_path / ".env"
    env_file.write_text(f"# shared config\nexport CSI_TOKEN={value}\n")
    token = load_token(env_file, environ={})
    assert token == "test-token"
    with running_server(tmp_path) as (c, s):
        path = tmp_path / "env-pi.json"
        path.write_text(json.dumps({"server": f"http://127.0.0.1:{s.server_port}", "pi_id": "pi-01",
                                   "token": "old-json-token", "spool_dir": str(tmp_path / "spool-pi-01"),
                                   "devices": [{"id": "esp-01", "port": "sim"}]}))
        with agent(tmp_path, s, config_path=path, env_file=env_file):
            until(lambda: c.snapshot()["agents"])
            job = c.create_job([("pi-01", "esp-01")], .5, .5)
            until(lambda: c.snapshot()["jobs"][job["id"]]["status"] == "completed")


def test_c_agent_finds_project_env_from_another_working_directory(tmp_path):
    (tmp_path / "pi_agent").mkdir()
    executable = tmp_path / "pi_agent/csi-agent"
    shutil.copy2(BINARY, executable)
    (tmp_path / ".env").write_text("CSI_TOKEN=test-token\n")
    with running_server(tmp_path) as (c, s):
        config = tmp_path / "pi.json"
        config.write_text(json.dumps({"server": f"http://127.0.0.1:{s.server_port}", "pi_id": "pi-01",
                                     "spool_dir": str(tmp_path / "spool"),
                                     "devices": [{"id": "esp-01", "port": "sim"}]}))
        env = dict(os.environ)
        env.pop("CSI_TOKEN", None)
        env.pop("CSI_ENV_FILE", None)
        with (tmp_path / "auto-env.log").open("w") as log:
            process = subprocess.Popen([str(executable), str(config), "--simulate"],
                                       cwd=tmp_path.parent, env=env, stderr=log)
            try:
                until(lambda: c.snapshot()["agents"])
                job = c.create_job([("pi-01", "esp-01")], .5, .5)
                until(lambda: c.snapshot()["jobs"][job["id"]]["status"] == "completed")
            finally:
                process.terminate()
                process.wait(timeout=6)


def test_trim_550_packets_to_exact_middle_500():
    raw = io.StringIO()
    writer = csv.writer(raw)
    writer.writerow(["host_timestamp", "raw_line"])
    for i in range(550):
        if i % 30 == 0:
            writer.writerow([1000 + i / 25, "debug [not CSI]"])
        writer.writerow([1000 + i / 25, line(timestamp=i)])
    data, quality = normalize_capture(raw.getvalue().encode(), trim_each=25, sample_count=500)
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert quality["accepted_rows"] == 550 and quality["retained_rows"] == 500
    assert quality["trimmed_head"] == quality["trimmed_tail"] == 25
    assert len(rows) == 500
    assert rows[0]["local_timestamp"] == "25" and rows[-1]["local_timestamp"] == "524"


def test_short_capture_does_not_pad_missing_packets():
    raw = io.StringIO()
    writer = csv.writer(raw)
    writer.writerow(["host_timestamp", "raw_line"])
    for i in range(60):
        writer.writerow([1000 + i / 25, line(timestamp=i)])
    data, quality = normalize_capture(raw.getvalue().encode(), trim_each=25, sample_count=500)
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert quality["retained_rows"] == 10
    assert [int(row["local_timestamp"]) for row in rows] == list(range(25, 35))


def test_packet_mode_rejects_old_agent(tmp_path):
    c = Coordinator(tmp_path)
    c.heartbeat({"pi_id": "pi-01", "devices": [{"id": "esp-01"}]})
    with pytest.raises(ValueError, match="업데이트"):
        c.create_job([("pi-01", "esp-01")])


def test_packet_quotas_are_independent_for_fast_and_slow_usb(tmp_path):
    channels = [pty.openpty(), pty.openpty()]
    stopped = threading.Event()
    threads = []
    def writer(master, interval):
        os.set_blocking(master, False)
        while not stopped.is_set():
            text = (line(int(time.monotonic() * 1e6) % 2**32) + "\n").encode()
            try:
                os.write(master, b"boot debug [bad]\n" + text)
            except BlockingIOError:
                pass
            stopped.wait(interval)
    for channel, interval in zip(channels, (.008, .03)):
        thread = threading.Thread(target=writer, args=(channel[0], interval))
        thread.start()
        threads.append(thread)
    try:
        ports = [os.ttyname(slave) for _master, slave in channels]
        with running_server(tmp_path) as (c, s), agent(tmp_path, s, ports=ports):
            until(lambda: c.snapshot()["agents"])
            job = c.create_job([("pi-01", "esp-01"), ("pi-01", "esp-02")], .6, sample_count=30)
            done = until(lambda: (j if (j := c.snapshot()["jobs"][job["id"]])["status"] == "completed" else None))
            reports = done["results"]["pi-01"]["devices"]
            assert all(report["raw_rows"] == 80 for report in reports.values())
            assert reports["esp-02"]["last_host_timestamp"] - reports["esp-01"]["last_host_timestamp"] > .7
            assert all(report["rejected_rows"] > 0 for report in reports.values())
            for device in ("esp-01", "esp-02"):
                key = f"pi-01/{device}"
                assert done["uploads"][key]["retained_rows"] == 30
                with (c.root / job["id"] / f"pi-01/{device}.raw.csv").open() as stream:
                    raw = list(csv.DictReader(stream))
                with (c.root / job["id"] / f"pi-01/{device}.csv").open() as stream:
                    kept = list(csv.DictReader(stream))
                assert len(raw) == 80 and len(kept) == 30
                assert kept[0]["local_timestamp"] == str(parse_line(raw[25]["raw_line"])[0])
                assert kept[-1]["local_timestamp"] == str(parse_line(raw[54]["raw_line"])[0])
            result = process_session(c.root / job["id"])
            assert len(result["series"]) == 2
            assert all(len(series["sample"]) == 30 for series in result["series"].values())
    finally:
        stopped.set()
        for thread in threads:
            thread.join(timeout=3)
        for master, slave in channels:
            os.close(master)
            os.close(slave)


def test_no_csi_exits_as_partial_not_success(tmp_path):
    master, slave = pty.openpty()
    try:
        with running_server(tmp_path) as (c, s), agent(tmp_path, s, ports=[os.ttyname(slave)]):
            until(lambda: c.snapshot()["agents"])
            job = c.create_job([("pi-01", "esp-01")], .5, sample_count=5,
                               timeout_seconds=2, idle_timeout_seconds=.3)
            done = until(lambda: (j if (j := c.snapshot()["jobs"][job["id"]])["status"] == "partial" else None))
            assert done["uploads"]["pi-01/esp-01"]["retained_rows"] == 0
            assert "idle timeout" in done["results"]["pi-01"]["devices"]["esp-01"]["error"]
    finally:
        os.close(master)
        os.close(slave)


def test_short_usb_port_is_bound_and_remembered_after_restart(tmp_path):
    master, slave = pty.openpty()
    master2, slave2 = pty.openpty()
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    stable = by_id / "usb-ESP32-unique-id"
    stable.symlink_to(os.ttyname(slave))
    short = tmp_path / "ttyACM0"
    short.symlink_to(os.ttyname(slave))
    env = {"CSI_SERIAL_BY_ID_DIR": str(by_id)}
    try:
        with running_server(tmp_path) as (c, s):
            with agent(tmp_path, s, ports=[str(short)], extra_env=env):
                until(lambda: c.snapshot()["agents"].get("pi-01", {}).get("devices", [{}])[0].get("port") == str(stable))
            cache = tmp_path / "pi-01.json.ports.json"
            assert json.loads(cache.read_text())["esp-01"]["stable_port"] == str(stable)
            short.unlink()
            short.symlink_to(os.ttyname(slave2))
            restarted_at = time.time()
            with agent(tmp_path, s, ports=[str(short)], config_path=tmp_path / "pi-01.json", extra_env=env):
                until(lambda: c.snapshot()["agents"]["pi-01"]["last_seen"] > restarted_at)
                device = c.snapshot()["agents"]["pi-01"]["devices"][0]
                assert device["configured_port"] == str(short)
                assert device["port"] == str(stable)
    finally:
        for fd in (master, slave, master2, slave2):
            os.close(fd)
