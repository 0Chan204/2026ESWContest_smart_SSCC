"""Python 3.11 TOML settings; environment overrides never enter status/log files."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib

from .config import IntegrationConfig


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "homevis.toml"


@dataclass(frozen=True)
class MQTTSettings:
    host: str = "localhost"
    port: int = 1883
    client_id: str = "homevis-ai"
    location_topic: str = "wifi/occupancy/state"
    behavior_topic: str = ""
    fall_status_topic: str = ""
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    tls: bool = False
    ca_file: str | None = None
    queue_size: int = 1000
    max_payload_bytes: int = 65536
    join_wait_seconds: float = 0.25

    def __post_init__(self):
        if not self.host or not self.client_id or not self.location_topic:
            raise ValueError("MQTT host, client_id and location_topic are required")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("MQTT port must be 1..65535")
        topics = [x for x in (self.location_topic, self.behavior_topic, self.fall_status_topic) if x]
        if len(set(topics)) != len(topics) or any("#" in x or "+" in x for x in topics):
            raise ValueError("MQTT input topics must be distinct exact topics")
        if any(x.startswith("home/") and x.endswith("/command") for x in topics):
            raise ValueError("device command topics are not sensing inputs")
        if type(self.queue_size) is not int or self.queue_size < 1:
            raise ValueError("MQTT queue_size must be positive")
        if type(self.max_payload_bytes) is not int or self.max_payload_bytes < 1:
            raise ValueError("MQTT max_payload_bytes must be positive")
        if not 0 <= self.join_wait_seconds <= 10:
            raise ValueError("invalid MQTT join_wait_seconds")
        if self.password and not self.username:
            raise ValueError("MQTT password requires username")


@dataclass(frozen=True)
class RunnerSettings:
    integration: IntegrationConfig
    mqtt: MQTTSettings
    tick_interval: float = 0.1
    status_interval: float = 5.0
    audit_retention_days: int = 7
    sensing_source: str = "mqtt"
    sensing_poll_interval: float = 1.0

    def __post_init__(self):
        if not 0 < self.tick_interval <= 1 or not 0 < self.status_interval <= 300:
            raise ValueError("invalid runner interval")
        if type(self.audit_retention_days) is not int or self.audit_retention_days < 1:
            raise ValueError("audit_retention_days must be a positive integer")
        if self.integration.allowed_lateness < self.mqtt.join_wait_seconds:
            raise ValueError("allowed_lateness must cover MQTT join_wait_seconds")
        if self.sensing_source not in {"mqtt", "backend"} or not 0 < self.sensing_poll_interval <= 10:
            raise ValueError("invalid sensing source/poll interval")


def load_settings(path=DEFAULT_CONFIG, *, environ=None, mode=None, base_url=None, data_dir=None):
    env = os.environ if environ is None else environ
    with Path(path).open("rb") as stream:
        raw = tomllib.load(stream)
    if set(raw) - {"backend", "mqtt", "runtime", "actions"}:
        raise ValueError("unknown configuration section")
    backend, mqtt, runtime = (dict(raw.get(key, {})) for key in ("backend", "mqtt", "runtime"))
    # TOML table keys are strings; the existing mapper expects integer levels.
    if "level_to_watts" in backend:
        backend["level_to_watts"] = {int(key): value for key, value in backend["level_to_watts"].items()}
    routes = {}
    for internal, spec in raw.get("actions", {}).items():
        routes[(internal, spec.get("internal_action", spec["action"]))] = (spec["scenario"], spec["device"], spec["action"], spec["room"])
    backend.update(mode=mode or env.get("HOMEVIS_MODE", backend.pop("mode", "live")),
                   base_url=base_url or env.get("HOMEVIS_BACKEND_URL", backend.pop("base_url", "http://localhost:8000")),
                   data_dir=Path(data_dir or env.get("HOMEVIS_DATA_DIR", backend.pop("data_dir", "output/integration"))),
                   action_routes=routes, async_alerts=True)
    # Authentication is supplied only by environment, never a logged TOML value.
    if "headers" in backend:
        raise ValueError("put backend credentials in HOMEVIS_BACKEND_TOKEN, not TOML")
    if env.get("HOMEVIS_BACKEND_TOKEN"):
        backend["headers"] = {"Authorization": "Bearer " + env["HOMEVIS_BACKEND_TOKEN"]}
    for key, variable in (("host", "HOMEVIS_MQTT_HOST"), ("port", "HOMEVIS_MQTT_PORT"),
                          ("location_topic", "HOMEVIS_LOCATION_TOPIC"), ("behavior_topic", "HOMEVIS_BEHAVIOR_TOPIC"),
                          ("fall_status_topic", "HOMEVIS_FALL_STATUS_TOPIC")):
        if variable in env:
            mqtt[key] = int(env[variable]) if key == "port" else env[variable]
    if "username" in mqtt or "password" in mqtt:
        raise ValueError("put MQTT credentials in environment, not TOML")
    mqtt.update(username=env.get("HOMEVIS_MQTT_USERNAME", ""), password=env.get("HOMEVIS_MQTT_PASSWORD", ""))
    if env.get("HOMEVIS_SENSING_SOURCE"):
        runtime["sensing_source"] = env["HOMEVIS_SENSING_SOURCE"]
    return RunnerSettings(IntegrationConfig(**backend), MQTTSettings(**mqtt), **runtime)
