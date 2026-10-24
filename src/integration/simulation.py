"""Explicit offline simulation. Never connects to MQTT or physical devices."""
from copy import deepcopy
import json
from threading import Lock
import time

from .mock_backend import MockBackend
from .backend_client import BackendError, HTTPResult
from .mqtt_source import Incoming
from .schemas import iso_time


class SimulationBackend(MockBackend):
    def __init__(self, clock=time.time, fall_scenario="fall_detected"):
        super().__init__(clock)
        self.fall_scenario = fall_scenario
        self.lock = Lock()
        self.previous_level = None
        self.incidents = {}

    def request(self, method, url, headers, body, timeout):
        with self.lock:
            if method == "GET" and "/fall-incidents/" in url:
                record = self.incidents.get(url.rsplit("/", 1)[-1])
                return HTTPResult(404, {}) if record is None else HTTPResult(200, deepcopy(record))
            if method == "GET" and url.endswith("/api/v1/ai/device-states"):
                for item in self.snapshot["items"]:
                    item["updatedAt"] = iso_time(self.clock())
            fail_after_accept = self.fail_after_accept
            self.fail_after_accept = False
            response = super().request(method, url, headers, body, timeout)
            del self.requests[:-1000]
            if method == "POST" and response.status == 202:
                payload = json.loads(body)
                if payload["scenario"] == self.fall_scenario:
                    response.body["fallIncidentId"] = "mock-fall-" + payload["decisionId"]
                    response.body["actions"] = [
                        {"device": "stove", "deviceId": "induction-01", "action": "turn_off", "status": "sent"},
                        {"device": "light", "deviceId": "light-01", "action": "blink", "status": "sent"}]
                    self.incidents[response.body["fallIncidentId"]] = {
                        "incidentId": response.body["fallIncidentId"], "status": "pending", "stage": "user",
                        "detectedAt": payload["timestamp"], "confidence": payload["confidence"]}
                response.body.update(status="executed", timestamp=payload["timestamp"], room=payload["room"],
                                     reason=payload["reason"], announcement=payload.get("announcement"), expiresAt=payload.get("expiresAt"))
                self.accepted[payload["decisionId"]] = deepcopy(payload), deepcopy(response.body)
                actions = response.body["actions"] if payload["scenario"] == self.fall_scenario else payload["actions"]
                for action in actions:
                    item = next(d for d in self.snapshot["items"] if d["device"] == action["device"])
                    if action["action"] in {"turn_on", "on"}:
                        item["is_on"] = True
                    elif action["action"] in {"turn_off", "off"}:
                        item["is_on"] = False
                    elif action["action"] == "reduce_power":
                        self.previous_level = item["current_state"].get("level", 5)
                        item["current_state"]["level"] = max(1, self.previous_level - 1)
                    elif action["action"] == "set_level":
                        self.previous_level = item["current_state"].get("level", 5)
                        item["current_state"]["level"] = action["level"]
                    elif action["action"] == "restore_power" and self.previous_level is not None:
                        item["current_state"]["level"] = self.previous_level
                    item["control_state"] = "homevis"
                if fail_after_accept:
                    raise BackendError("mock timeout after acceptance", retryable=True)
            elif fail_after_accept:
                self.fail_after_accept = True
            return response


class SimulationSource:
    def __init__(self, settings, *, clock=time.time, scenario="presence"):
        self.settings, self.clock, self.scenario = settings, clock, scenario
        self.connected = False
        self.next_sample = 0
        self.count = 0

    def start(self):
        self.connected = True

    def drain(self):
        now = self.clock()
        if now < self.next_sample:
            return []
        self.next_sample = now + 1
        fall = self.scenario == "fall"
        room = "toilet" if fall else "room"
        measured_at = int(now)
        payload = {"time": iso_time(measured_at), "location": room, "location_confidence": .99,
                   "behavior": {"time": iso_time(measured_at), "valid_until": iso_time(measured_at + 3),
                                "location": room, "confidence": .99,
                                "activity": "lying" if fall else "walking",
                                "motion_state": "still" if fall else "moving", "fall_detected": fall}}
        self.count += 1
        return [Incoming(self.settings.location_topic, json.dumps(payload).encode(), now)]

    def health(self):
        return {"connected": self.connected, "received": self.count, "simulation": True}

    def close(self):
        self.connected = False
