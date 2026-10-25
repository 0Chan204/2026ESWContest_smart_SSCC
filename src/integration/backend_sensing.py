"""Backend final results, not raw node features or locally inferred activities."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import time

from .backend_client import BackendError
from .behavior_labels import BEHAVIOR_LABELS, OBSERVED_STATES
from .mqtt_source import Incoming, SensingFault
from .schemas import ContractError, iso_time, measured_time, number


# Deliberately synthetic labels retained for the separate mock envelope.
MOCK_EVENT_LABELS = {"mock_fall": "fall", "mock_wake": "wake", "mock_lie": "lie_down"}


def normalize_result(raw, *, allow_mock_events=False):
    if not isinstance(raw, dict):
        raise ContractError("sensing result must be an object")
    mock = raw.get("mockContract") == "homevis.behavior.v1"
    if "mockContract" in raw and (not mock or not allow_mock_events):
        raise ContractError("unverified/mock sensing contract is not permitted")
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
    if mock:
        # Explicit mock contract separates an explanation from a diagnostic.
        # A legacy reason remains a diagnostic even alongside the new fields.
        payload["location_explanation"] = raw.get("locationExplanation")
        payload["valid"] = raw.get("locationValid", True)
        payload["reason"] = raw.get("locationError") or raw.get("reason")
        if "mockBehavior" in raw:
            behavior = raw["mockBehavior"]
            if not isinstance(behavior, dict):
                raise ContractError("mockBehavior must be an object")
            label = behavior.get("label")
            if label is not None and label not in MOCK_EVENT_LABELS:
                raise ContractError("unverified behavior event label")
            payload["behavior"] = {
                "time": behavior.get("time"), "valid_until": behavior.get("valid_until"),
                "location": behavior.get("location"), "confidence": behavior.get("confidence"),
                "activity": behavior.get("activity"), "motion_state": behavior.get("motion_state"),
                "fall_detected": behavior.get("fall_detected"), "valid": behavior.get("valid", True),
                "reason": behavior.get("error"), "explanation": behavior.get("reason"),
                "event": MOCK_EVENT_LABELS.get(label), "event_id": behavior.get("eventId"),
                "raw_activity": label or behavior.get("activity"),
            }
            return payload
    # No invented behavior validity/confidence, no mapping lying -> motion=still.
    if validity and raw.get("activityConfidence") is not None and location in {"room", "kitchen", "toilet"}:
        payload["behavior"] = {"time": raw["observedAt"], "valid_until": iso_time(observed + validity),
            "location": location, "confidence": raw["activityConfidence"], "activity": raw.get("activity"),
            "motion_state": raw.get("motion_state"), "fall_detected": raw.get("fall_detected"),
            "reason": "unverified_activity_label" if raw.get("activity") is not None
                      and raw["activity"] not in OBSERVED_STATES | BEHAVIOR_LABELS.keys() else None}
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

    def _fault(self, now, reason):
        # Always retain the fault in the bounded queue. Keep earlier messages
        # for the router to preserve any already-received explicit fall report.
        self.pending.append(SensingFault(now, reason))
        self.error = reason

    def drain(self):
        now = self.clock()
        if self.future is not None and self.future.done():
            try:
                items = self.future.result()
                self.connected = True
                self.error = None
                if not isinstance(items, list):
                    raise ContractError("sensing results require a list")
                for raw in items:
                    try:
                        observed = measured_time(raw.get("observedAt"))
                        normalize_result(raw, allow_mock_events=self.settings.integration.mock_behavior_contract)
                        if observed > now:
                            raise ContractError("future sensing result")
                        self.cursor = max(self.cursor, observed)
                        # Old results after downtime cannot become new live evidence.
                        if observed < now - self.settings.integration.allowed_lateness:
                            self.dropped += 1
                            continue
                        if len(self.pending) >= self.pending.maxlen:
                            self.dropped += 1
                            self._fault(now, "backend_sensing_queue_overflow")
                            continue
                        self.pending.append(Incoming(self.settings.mqtt.location_topic,
                                                     json.dumps(raw).encode(), now))
                        self.received += 1
                    except (ValueError, TypeError, AttributeError):
                        self.rejected += 1
                        mismatch = isinstance(raw, dict) and "time" in raw and "observedAt" not in raw
                        self._fault(now, "backend_sensing_contract_mismatch" if mismatch else "backend_sensing_invalid_result")
            except (BackendError, ValueError, TypeError, OSError) as exc:
                self.connected = False
                self._fault(now, "backend_sensing_poll_failed:" + type(exc).__name__)
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
