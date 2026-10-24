"""Subscribe-only MQTT input. Callback threads never touch the controller or SQLite."""
from collections import deque
from dataclasses import dataclass
import json
from queue import Empty, Full, Queue
import time

from .schemas import ContractError, measured_time
from .sensing import BehaviorObservation
from .settings import MQTTSettings


def _reject_nonfinite(value):
    raise ContractError("nonfinite JSON number")


@dataclass(frozen=True)
class Incoming:
    topic: str
    payload: bytes
    received_at: float
    retained: bool = False


def parse_behavior(payload):
    if not isinstance(payload, dict):
        raise ContractError("behavior must be an object")
    for key in ("activity", "motion_state", "location", "reason"):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise ContractError(f"behavior {key} must be a string")
    if not isinstance(payload.get("location"), str):
        raise ContractError("behavior location is required")
    return BehaviorObservation(
        measured_at=measured_time(payload.get("time")),
        valid_until=measured_time(payload.get("valid_until")),
        location=payload["location"], confidence=payload.get("confidence"),
        activity=payload.get("activity"), motion_state=payload.get("motion_state"),
        fall_detected=payload.get("fall_detected"), valid=payload.get("valid", True),
        reason=payload.get("reason"))


class MQTTSource:
    def __init__(self, settings: MQTTSettings, *, clock=time.time, client=None):
        self.settings, self.clock = settings, clock
        if client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError as exc:
                raise RuntimeError("MQTT needs: python -m pip install -r requirements-runtime.txt") from exc
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.client_id)
        self.client = client
        self.inbox = Queue(maxsize=settings.queue_size)
        self.connected = False
        self.subscribed = False
        self.received = self.dropped = self.rejected = 0
        self.last_received_at = None
        self.error = None
        client.on_connect = self._connect
        client.on_disconnect = self._disconnect
        client.on_connect_fail = self._connect_fail
        client.on_message = self._message
        client.on_subscribe = self._subscribe
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.username:
            client.username_pw_set(settings.username, settings.password or None)
        if settings.tls:
            client.tls_set(ca_certs=settings.ca_file)

    def start(self):
        self.client.connect_async(self.settings.host, self.settings.port, keepalive=30)
        self.client.loop_start()

    def _connect(self, client, userdata, flags, reason_code, properties):
        self.connected = reason_code == 0
        self.subscribed = False
        self.error = None if self.connected else "mqtt_connection_rejected"
        if self.connected:
            topics = [x for x in (self.settings.location_topic, self.settings.behavior_topic,
                                  self.settings.fall_status_topic) if x]
            result, _ = client.subscribe([(topic, 1) for topic in topics])
            if result != 0:
                self.connected = False
                self.error = "mqtt_subscribe_failed"

    def _subscribe(self, client, userdata, mid, reason_codes, properties):
        self.subscribed = bool(reason_codes) and all(not code.is_failure for code in reason_codes)
        if not self.subscribed:
            self.error = "mqtt_subscription_rejected"

    def _disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        self.subscribed = False
        self.error = "mqtt_disconnected"

    def _connect_fail(self, client, userdata):
        self.connected = False
        self.error = "mqtt_connection_failed"

    def _message(self, client, userdata, message):
        if len(message.payload) > self.settings.max_payload_bytes:
            self.rejected += 1
            return
        try:
            self.inbox.put_nowait(Incoming(message.topic, bytes(message.payload), self.clock(), bool(message.retain)))
            self.received += 1
            self.last_received_at = self.clock()
        except Full:
            self.dropped += 1

    def drain(self, limit=200):
        for _ in range(limit):
            try:
                yield self.inbox.get_nowait()
            except Empty:
                break

    def health(self):
        return {"connected": self.connected, "subscribed": self.subscribed, "received": self.received, "dropped": self.dropped,
                "rejected": self.rejected, "queued": self.inbox.qsize(), "error": self.error,
                "last_received_at": self.last_received_at}

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


class InputRouter:
    """Bounded join buffer accepts a combined envelope or separate measured behavior."""
    def __init__(self, settings: MQTTSettings, runtime):
        self.settings, self.runtime = settings, runtime
        self.behaviors = deque(maxlen=1000)
        self.pending = deque()

    def accept(self, message: Incoming):
        try:
            if len(message.payload) > self.settings.max_payload_bytes:
                raise ContractError("input payload too large")
            if message.retained:
                raise ContractError("retained observations are not live evidence")
            payload = json.loads(message.payload.decode("utf-8"), parse_constant=_reject_nonfinite)
            if not isinstance(payload, dict):
                raise ContractError("input must be a JSON object")
            if message.topic == self.settings.location_topic:
                if "observedAt" in payload:
                    from .backend_sensing import normalize_result
                    payload = normalize_result(payload)
                if len(self.pending) >= self.settings.queue_size:
                    raise ContractError("location join buffer full")
                # Validate now so malformed input invalidates the current sensing cache.
                from .sensing import location_observation
                location_observation(payload, message.received_at, self.runtime.config)
                behavior = parse_behavior(payload["behavior"]) if "behavior" in payload else None
                if behavior is not None and behavior.measured_at > message.received_at:
                    raise ContractError("future behavior measurement")
                self.pending.append((message, payload, behavior))
            elif self.settings.behavior_topic and message.topic == self.settings.behavior_topic:
                behavior = parse_behavior(payload)
                if behavior.measured_at > message.received_at:
                    raise ContractError("future behavior measurement")
                # Conflicting same-time behavior invalidates that measurement.
                for previous in self.behaviors:
                    if previous.location == behavior.location and previous.measured_at == behavior.measured_at:
                        if previous != behavior:
                            from dataclasses import replace
                            behavior = replace(behavior, valid=False, reason="conflicting_behavior")
                        else:
                            return
                self.behaviors.append(behavior)
            elif self.settings.fall_status_topic and message.topic == self.settings.fall_status_topic:
                self.runtime.receive_backend_fall_status(payload)
            else:
                raise ContractError("unconfigured input topic")
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            if message.topic == self.settings.location_topic:
                self.runtime.controller.realtime_engine.sensing_invalid = True
                self.runtime._interrupt_bedtime(message.received_at)
            self.runtime.diagnostic("input_rejected", error=type(exc).__name__)

    def flush(self, now):
        while self.pending and now - self.pending[0][0].received_at >= self.settings.join_wait_seconds:
            message, payload, behavior = self.pending.popleft()
            if behavior is None:
                from src.control.identifiers import canonical_room
                at = measured_time(payload["time"])
                candidates = [b for b in self.behaviors if b.location == canonical_room(payload["location"])
                              and b.measured_at <= at]
                if candidates:
                    # Prefer the last received copy on a tie (including a conflict tombstone).
                    behavior = max(enumerate(candidates), key=lambda x: (x[1].measured_at, x[0]))[1]
            self.runtime.ingest_location(payload, received_at=message.received_at, behavior=behavior)
        self.behaviors = deque((b for b in self.behaviors if now - b.valid_until < 30), maxlen=1000)
