"""Backend v0.5 final results, not raw node features or inferred activities."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import time

from .backend_client import BackendError
from .mqtt_source import Incoming
from .schemas import ContractError, iso_time, measured_time, number


def normalize_result(raw):
    if not isinstance(raw, dict):
        raise ContractError("sensing result must be an object")
    observed = measured_time(raw.get("observedAt"))
    validity = raw.get("validSec")
    if validity is not None and (type(validity) is not int or validity < 0):
        raise ContractError("validSec must be a nonnegative integer")
    if raw.get("present") is not None and type(raw["present"]) is not bool:
        raise ContractError("present must be boolean or null")
    confidence = number(raw.get("confidence"), "confidence", nullable=True, confidence=True)
    location = raw.get("room") or "unknown"
    if raw.get("present") is False:
        location = "empty"
    payload = {"time": raw["observedAt"], "location": location,
               "location_confidence": confidence, "backend_result": raw}
    if raw.get("reason"):
        payload["reason"] = raw["reason"]
    if validity is not None:
        payload["valid_until"] = iso_time(observed + validity)
    # No invented behavior validity/confidence, no mapping lying -> motion=still.
    if validity and raw.get("activityConfidence") is not None and location in {"room", "kitchen", "toilet"}:
        payload["behavior"] = {"time": raw["observedAt"], "valid_until": iso_time(observed + validity),
            "location": location, "confidence": raw["activityConfidence"], "activity": raw.get("activity"),
            "motion_state": raw.get("motion_state"), "fall_detected": raw.get("fall_detected")}
    return payload


class BackendSensingSource:
    def __init__(self, settings, client, *, clock=time.time):
        self.settings, self.client, self.clock = settings, client, clock
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="homevis-sensing")
        self.future = None
        self.next_poll = 0
        self.cursor = clock() - settings.integration.allowed_lateness
        self.pending = deque(maxlen=settings.mqtt.queue_size)
        self.connected = False
        self.error = None
        self.received = self.rejected = self.dropped = 0

    def start(self):
        pass

    def drain(self):
        now = self.clock()
        if self.future is not None and self.future.done():
            try:
                items = self.future.result()
                self.connected = True
                self.error = None
                for raw in items:
                    try:
                        observed = measured_time(raw.get("observedAt"))
                        normalize_result(raw)
                        if observed > now:
                            raise ContractError("future sensing result")
                        self.cursor = max(self.cursor, observed)
                        # Old results after downtime cannot become new live evidence.
                        if observed < now - self.settings.integration.allowed_lateness:
                            self.dropped += 1
                            continue
                        if len(self.pending) >= self.pending.maxlen:
                            self.dropped += 1
                        self.pending.append(Incoming(self.settings.mqtt.location_topic,
                                                     json.dumps(raw).encode(), now))
                        self.received += 1
                    except (ValueError, TypeError, AttributeError):
                        self.rejected += 1
            except (BackendError, ContractError) as exc:
                self.connected = False
                self.error = type(exc).__name__
            finally:
                self.future = None
                self.next_poll = now + self.settings.sensing_poll_interval
        if self.future is None and now >= self.next_poll:
            self.future = self.executor.submit(self.client.fetch_sensing_results, self.cursor)
        result = []
        for _ in range(min(len(self.pending), 200)):
            result.append(self.pending.popleft())
        return result

    def health(self):
        return {"transport": "backend_http", "connected": self.connected, "received": self.received,
                "rejected": self.rejected, "dropped": self.dropped, "error": self.error}

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
