"""Subscribe-only MQTT input. Callback threads never touch the controller or SQLite."""
from collections import deque
from dataclasses import dataclass
import json
from queue import Empty, Full, Queue
import time

from .schemas import ContractError, measured_time
from .behavior_labels import BEHAVIOR_LABELS, OBSERVED_STATES, observation_id
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


@dataclass(frozen=True)
class SensingFault:
    """Internal transport failure, never a fabricated sensor/MQTT observation."""
    received_at: float
    reason: str


def parse_behavior(payload, *, allow_mock_events=False):
    if not isinstance(payload, dict):
        raise ContractError("behavior must be an object")
    for key in ("activity", "motion_state", "location", "reason"):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise ContractError(f"behavior {key} must be a string")
    if not isinstance(payload.get("location"), str):
        raise ContractError("behavior location is required")
    if payload.get("event") is not None and not allow_mock_events:
        raise ContractError("behavior event wire contract is not verified")
    reason = payload.get("reason")
    activity = payload.get("activity")
    measured_at = measured_time(payload.get("time"))
    event, event_id = payload.get("event"), payload.get("event_id")
    raw_activity = payload.get("raw_activity")
    if activity in BEHAVIOR_LABELS:
        if event is not None:
            raise ContractError("classifier label cannot also supply an internal event")
        from src.control.identifiers import canonical_room
        event = BEHAVIOR_LABELS[activity]
        event_id = observation_id(canonical_room(payload["location"]), measured_at)
        raw_activity, activity = activity, None
    elif activity is not None and activity not in OBSERVED_STATES:
        reason = reason or "unverified_activity_label"
    return BehaviorObservation(
        measured_at=measured_at,
        valid_until=measured_time(payload.get("valid_until")),
        location=payload["location"], confidence=payload.get("confidence"),
        activity=activity, motion_state=payload.get("motion_state"),
        fall_detected=payload.get("fall_detected"), valid=payload.get("valid", True),
        reason=reason, explanation=payload.get("explanation"),
        event=event, event_id=event_id, raw_activity=raw_activity)


class MQTTSource:
    def __init__(self, settings: MQTTSettings, *, clock=time.time, client=None, voice_only=False):
        self.settings, self.clock = settings, clock
        self.voice_only = voice_only
        self.topics = ((settings.voice_topic,) if voice_only else tuple(x for x in (
            settings.location_topic, settings.behavior_topic, settings.fall_status_topic, settings.voice_topic) if x))
        if not all(self.topics):
            raise ValueError("voice-only MQTT requires an enabled voice topic")
        self.connection_generation = 0
        if client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError as exc:
                raise RuntimeError("MQTT needs: python -m pip install -r requirements-runtime.txt") from exc
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.client_id,
                                 protocol=mqtt.MQTTv311, clean_session=not bool(settings.voice_topic))
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
            self.connection_generation += 1
            result, _ = client.subscribe([(topic, 1) for topic in self.topics])
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
        # A persistent broker session may retain old subscriptions after switching
        # sensing to HTTP. Never feed those MQTT observations into the core twice.
        if message.topic not in self.topics or len(message.payload) > self.settings.max_payload_bytes:
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
                "connection_generation": self.connection_generation,
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
        if isinstance(message, SensingFault):
            # A later transport failure must not erase an explicit fall already
            # validated into the join buffer. Normal automation evidence is dropped.
            for pending_message, payload, behavior in self.pending:
                if behavior is not None and (behavior.event == "fall" or behavior.fall_detected is True):
                    self.runtime.ingest_location(payload, received_at=pending_message.received_at, behavior=behavior)
            self.pending.clear()
            self.behaviors.clear()
            self.runtime.invalidate_sensing(message.received_at, message.reason)
            return
        try:
            if len(message.payload) > self.settings.max_payload_bytes:
                raise ContractError("input payload too large")
            if message.retained:
                raise ContractError("retained observations are not live evidence")
            payload = json.loads(message.payload.decode("utf-8"), parse_constant=_reject_nonfinite)
            if not isinstance(payload, dict):
                raise ContractError("input must be a JSON object")
            if self.settings.voice_topic and message.topic == self.settings.voice_topic:
                self.runtime.receive_voice_request(payload, received_at=message.received_at)
            elif message.topic == self.settings.location_topic:
                if "observedAt" in payload:
                    from .backend_sensing import normalize_result
                    payload = normalize_result(payload, allow_mock_events=self.runtime.config.mock_behavior_contract)
                if len(self.pending) >= self.settings.queue_size:
                    raise ContractError("location join buffer full")
                # Validate now so malformed input invalidates the current sensing cache.
                from .sensing import location_observation
                location_observation(payload, message.received_at, self.runtime.config)
                behavior = parse_behavior(payload["behavior"], allow_mock_events=self.runtime.config.mock_behavior_contract) if "behavior" in payload else None
                if behavior is not None and behavior.measured_at > message.received_at:
                    raise ContractError("future behavior measurement")
                self.pending.append((message, payload, behavior))
            elif self.settings.behavior_topic and message.topic == self.settings.behavior_topic:
                behavior = parse_behavior(payload, allow_mock_events=self.runtime.config.mock_behavior_contract)
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
                self.accept(SensingFault(message.received_at, "sensing_input_rejected"))
            elif self.settings.behavior_topic and message.topic == self.settings.behavior_topic:
                self.runtime.interrupt_behavior(message.received_at)
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


class CombinedSource:
    """HTTP sensing plus the one voice MQTT connection; both retain bounded queues."""
    def __init__(self, sensing, voice):
        self.sensing, self.voice = sensing, voice

    @property
    def connection_generation(self):
        return self.voice.connection_generation

    def start(self):
        self.sensing.start()
        self.voice.start()

    def drain(self, limit=200):
        yield from self.voice.drain(min(limit, 20))
        yield from self.sensing.drain()

    def health(self):
        return {"sensing": self.sensing.health(), "voice": self.voice.health()}

    def close(self):
        try:
            self.voice.close()
        finally:
            self.sensing.close()
