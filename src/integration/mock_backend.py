from copy import deepcopy
import json

from .backend_client import BackendError, HTTPResult
from .schemas import decision_payload, iso_time


def sample_devices(timestamp: float) -> dict:
    return {"items": [
        {"device": "stove", "deviceId": "induction-01", "room": "kitchen", "online": True,
         "is_on": True, "current_state": {"state": "on", "level": 5, "temperature": 120.0},
         "control_state": "user", "updatedAt": iso_time(timestamp)},
        {"device": "light", "deviceId": "light-01", "room": "room", "online": True,
         "is_on": False, "current_state": {"power": "off", "mode": "steady"},
         "control_state": "homevis", "updatedAt": iso_time(timestamp)},
        {"device": "water_purifier", "deviceId": "water-01", "room": "kitchen", "online": True,
         "is_on": False, "current_state": {"status": "idle", "lastDispensedMl": 250},
         "control_state": None, "updatedAt": iso_time(timestamp)},
    ]}


def ready_sample_devices(timestamp: float) -> dict:
    """TEST ONLY: an independent readiness signal, not a claimed backend field.

    Keep the supplied status=idle unchanged. Production readiness is unconfirmed.
    """
    snapshot = sample_devices(timestamp)
    snapshot["items"][2]["current_state"]["mock_readiness"] = "ready"
    return snapshot


class MockBackend:
    mock_only = True

    def __init__(self, clock, *, allow_null_confidence=True):
        self.clock = clock
        self.allow_null_confidence = allow_null_confidence
        self.snapshot = sample_devices(clock())
        self.requests = []
        self.accepted = {}
        self.fail_after_accept = False
        self.action_status = "sent"

    def request(self, method, url, headers, body, timeout):
        self.requests.append((method, url, body))
        if method == "GET" and url.endswith("/api/v1/ai/device-states"):
            return HTTPResult(200, deepcopy(self.snapshot))
        if method != "POST" or not url.endswith("/api/v1/ai/decisions"):
            return HTTPResult(404, {})
        payload = decision_payload(json.loads(body), allow_null_confidence=self.allow_null_confidence)
        identity = payload["decisionId"]
        if identity in self.accepted:
            original, response = self.accepted[identity]
            if original != payload:
                return HTTPResult(409, {})
            return HTTPResult(200, {**deepcopy(response), "duplicate": True})
        actions = [{"device": a["device"], "deviceId": "mock-device", "action": a["action"],
                    "status": self.action_status, "commandId": f"mock-cmd-{identity}-{i}",
                    "message": None if self.action_status == "sent" else "mock failure"}
                   for i, a in enumerate(payload["actions"])]
        response = {"decisionId": identity, "scenario": payload["scenario"],
                    "confidence": payload["confidence"], "receivedAt": iso_time(self.clock()),
                    "actions": actions, "eventId": "mock-evt-" + identity,
                    "fallIncidentId": None, "feedback": None,
                    "weather": {"available": True, "text": "Mock weather (not live)", "stale": False},
                    "duplicate": False}
        self.accepted[identity] = deepcopy(payload), deepcopy(response)
        if self.fail_after_accept:
            self.fail_after_accept = False
            raise BackendError("mock timeout after acceptance", retryable=True)
        return HTTPResult(202, response)
