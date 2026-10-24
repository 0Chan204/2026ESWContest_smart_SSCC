"""Real local sockets only: MQTT subscription/reconnect -> controller -> HTTP POST."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
from threading import Event, Thread
import time

import pytest

from src.alert_service import AlertService
from src.control import CentralController
from src.control.confidence.config import ConfidenceConfig
from src.control.realtime_config import RealtimeConfig
from src.control.scenario_models import DeviceCommand, ScenarioAction
from src.integration import IntegrationRuntime
from src.integration.backend_client import BackendClient
from src.integration.backend_sensing import BackendSensingSource
from src.integration.host import ContinuousHost
from src.integration.mqtt_source import MQTTSource
from src.integration.schemas import decision_response, iso_time
from src.integration.settings import load_settings
from src.integration.simulation import SimulationBackend
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS


def mqtt_packet(kind, body):
    size = len(body)
    encoded = bytearray()
    while True:
        digit, size = size % 128, size // 128
        encoded.append(digit | (128 if size else 0))
        if not size:
            return bytes([kind]) + encoded + body


def read_packet(sock):
    def read(size):
        result = b""
        while len(result) < size:
            chunk = sock.recv(size - len(result))
            if not chunk:
                raise EOFError
            result += chunk
        return result
    kind = read(1)[0]
    size = 0
    factor = 1
    while True:
        digit = read(1)[0]
        size += (digit & 127) * factor
        if not digit & 128:
            break
        factor *= 128
    return kind, read(size)


class TestBroker:
    __test__ = False

    def __init__(self, *, disconnect_first=False, location_only=False):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(2)
        self.socket.settimeout(.1)
        self.port = self.socket.getsockname()[1]
        self.stop = Event()
        self.sessions = 0
        self.topics = []
        self.errors = []
        self.disconnect_first = disconnect_first
        self.location_only = location_only
        self.thread = Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.socket.accept()
            except socket.timeout:
                continue
            try:
                with conn:
                    conn.settimeout(1)
                    assert read_packet(conn)[0] == 0x10
                    conn.sendall(b"\x20\x02\x00\x00")
                    kind, body = read_packet(conn)
                    assert kind == 0x82
                    pos = 2
                    topics = []
                    while pos < len(body):
                        size = struct.unpack("!H", body[pos:pos + 2])[0]
                        pos += 2
                        topics.append(body[pos:pos + size].decode())
                        pos += size + 1
                    self.topics.append(topics)
                    self.sessions += 1
                    conn.sendall(mqtt_packet(0x90, body[:2] + bytes([1] * len(topics))))
                    for _ in range(80):
                        now = time.time()
                        payload = {"time": iso_time(now), "location": "room", "location_confidence": .99,
                            "behavior": {"time": iso_time(now), "valid_until": iso_time(now + 3),
                                         "location": "room", "confidence": .99, "activity": "walking"}}
                        if self.location_only:
                            payload.pop("behavior")
                        topic = topics[0].encode()
                        conn.sendall(mqtt_packet(0x30, struct.pack("!H", len(topic)) + topic + json.dumps(payload).encode()))
                        if self.disconnect_first and self.sessions == 1 or self.stop.wait(.05):
                            break
            except (EOFError, OSError):
                pass
            except Exception as exc:
                self.errors.append(exc)

    def close(self):
        self.stop.set()
        self.thread.join(2)
        self.socket.close()


@pytest.fixture
def http_backend():
    backend = SimulationBackend()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self): self.respond("GET")
        def do_POST(self): self.respond("POST")
        def respond(self, method):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))) or None
            received.append((method, self.path, body))
            if self.path.startswith("/api/v1/sensing/results?"):
                response_body = {"items": [{"resultId": "one", "observedAt": iso_time(time.time()),
                    "room": "kitchen", "present": True, "confidence": .9, "validSec": 5}], "total": 1}
                status = 200
            else:
                response = backend.request(method, self.path, dict(self.headers), body, 1)
                response_body, status = response.body, response.status
            raw = json.dumps(response_body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args): pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", backend, received
    server.shutdown()
    server.server_close()
    thread.join(2)


def test_real_mqtt_reconnect_resubscribes_without_publishing_commands():
    pytest.importorskip("paho.mqtt.client")
    broker = TestBroker(disconnect_first=True)
    settings = load_settings(environ={}, mode="mock")
    source = MQTTSource(replace(settings.mqtt, host="127.0.0.1", port=broker.port))
    try:
        source.start()
        deadline = time.monotonic() + 5
        while broker.sessions < 2 and time.monotonic() < deadline:
            time.sleep(.02)
        assert broker.sessions >= 2
        assert broker.topics[:2] == [["wifi/occupancy/state"], ["wifi/occupancy/state"]]
        assert list(source.drain())
        assert not broker.errors
    finally:
        source.close()
        broker.close()


def test_real_mqtt_to_engine_to_http_light_control(tmp_path, http_backend):
    pytest.importorskip("paho.mqtt.client")
    url, backend, received = http_backend
    broker = TestBroker(location_only=True)
    settings = load_settings(environ={}, mode="live", base_url=url, data_dir=tmp_path)
    settings = replace(settings, integration=replace(settings.integration, allowed_lateness=.1, poll_interval=.1, light_on_seconds=.1),
                       mqtt=replace(settings.mqtt, host="127.0.0.1", port=broker.port, join_wait_seconds=0),
                       tick_interval=.02)
    source = MQTTSource(settings.mqtt)
    controller = CentralController(config=RealtimeConfig(SENSING_CONFIRM_TIME=.1),
        confidence_config=ConfidenceConfig.for_profile("location_level_v1", light_on_seconds=.1),
        confidence_data_dir=tmp_path / "controller")
    runtime = IntegrationRuntime(settings.integration, BackendClient(settings.integration), controller=controller,
        fall_alert_service=AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio"))
    host = ContinuousHost(settings, runtime, source)
    try:
        host.run(Event(), duration=2)
        posts = [json.loads(body) for method, _, body in received if method == "POST"]
        assert posts, "no device command traversed the real MQTT and HTTP sockets"
        assert posts[0]["actions"] == [{"device": "light", "deviceId": "light-01", "action": "on"}]
        assert sum(p["scenario"] == "light_auto_on" for p in posts) == 1
        assert all(path == "/api/v1/ai/decisions" for method, path, _ in received if method == "POST")
        assert backend.snapshot["items"][1]["is_on"]
        assert controller.realtime_engine._sensing.activity_observed is False
        assert not broker.errors
    finally:
        broker.close()


def test_backend_sensing_http_source_uses_confirmed_api(tmp_path, http_backend):
    url, _, received = http_backend
    settings = load_settings(environ={}, mode="live", base_url=url, data_dir=tmp_path)
    source = BackendSensingSource(settings, BackendClient(settings.integration))
    try:
        deadline = time.monotonic() + 3
        messages = []
        while not messages and time.monotonic() < deadline:
            messages = source.drain()
            time.sleep(.01)
        assert messages and json.loads(messages[0].payload)["room"] == "kitchen"
        assert any(path.startswith("/api/v1/sensing/results?since=") and "%2B" in path for _, path, _ in received)
    finally:
        source.close()


def test_requests_validate_against_actual_team_backend_models(tmp_path):
    checkout = os.environ.get("HOMEVIS_BACKEND_CHECKOUT")
    if not checkout:
        pytest.skip("optional: HOMEVIS_BACKEND_CHECKOUT points to the team's backend checkout")
    pytest.importorskip("pydantic")
    spec = importlib.util.spec_from_file_location("verified_backend_schemas", Path(checkout) / "app" / "schemas.py")
    schemas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schemas)
    settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
    backend = SimulationBackend()
    runtime = IntegrationRuntime(settings.integration, BackendClient(settings.integration, backend),
        fall_alert_service=AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio"))
    try:
        for output in [DeviceCommand(time.time(), 120), ScenarioAction(time.time(), "bathroom_fall", "fall_detected",
                        "blink", "light", "Observed fall", {"incident_id": "schema-check"}, room="toilet")]:
            mapped = runtime.decision_mapper.map(output, evidence_confidence=.85)
            request = schemas.AiDecisionRequest.model_validate(mapped.payload)
            assert request.confidence == .85
            response = backend.request("POST", "/api/v1/ai/decisions", {}, json.dumps(mapped.payload).encode(), 1)
            wire = schemas.AiDecisionAccepted.model_validate(response.body).model_dump()
            assert decision_response(202, wire, mapped.payload)["decisionId"] == request.decisionId
    finally:
        runtime.close()
