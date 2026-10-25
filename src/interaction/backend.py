"""Read-only queries and voice decisions using the existing authenticated transport."""
import time
from urllib.parse import quote

from src.integration.backend_client import BackendError, HTTPResult
from src.integration.schemas import ContractError, device_items, measured_time, number
from .contracts import command_list, decision_payload, decision_response, string, ROOMS


class VoiceBackend:
    def __init__(self, client, config, clock=time.time):
        self.client, self.config, self.clock = client, config, clock

    def request(self, method, path, body=None, deadline=None):
        timeout = self.config.http_timeout
        if deadline is not None:
            remaining = deadline - self.clock()
            if remaining <= 0.05:
                raise TimeoutError("voice deadline")
            timeout = min(timeout, remaining)
        result = self.client._request(method, path, body, timeout=timeout)
        if result.status not in ({200, 202} if method == "POST" else {200}):
            raise BackendError("voice backend HTTP error", status_code=result.status,
                               retryable=result.status in {408, 429} or result.status >= 500)
        return result

    def post(self, payload):
        payload = decision_payload(payload)
        result = self.request("POST", self.client.DECISIONS_PATH, payload, measured_time(payload["expiresAt"]))
        return HTTPResult(result.status, decision_response(result.status, result.body, payload))

    def status(self, payload):
        result = self.request("GET", self.client.DECISIONS_PATH + "/" + quote(payload["decisionId"], safe=""))
        return decision_response(result.status, result.body, payload, polling=True)

    def commands(self, *, recovery=False, deadline=None):
        query = "status=thinking" if recovery else "limit=10"
        result = self.request("GET", "/api/v1/voice/commands?" + query, deadline=deadline)
        return command_list(result.body, self.clock())

    def devices(self, deadline):
        result = self.request("GET", self.client.DEVICE_STATES_PATH, deadline=deadline)
        return device_items(result.body)

    def presence(self, deadline):
        result = self.request("GET", "/api/v1/sensing/results/latest", deadline=deadline).body
        if not isinstance(result, dict):
            raise ContractError("invalid latest sensing")
        string(result.get("resultId"), "resultId", 100)
        at = measured_time(result.get("observedAt"))
        measured_time(result.get("savedAt"))
        if result.get("room") not in {*ROOMS, None} or type(result.get("present")) not in (bool, type(None)):
            raise ContractError("invalid sensing location/presence")
        number(result.get("confidence"), "sensing confidence", nullable=True, confidence=True)
        validity = result.get("validSec")
        if validity is not None:
            number(validity, "validSec")
        if at > self.clock() or validity is None or validity <= 0 or self.clock() >= at + validity:
            raise ContractError("stale or unbounded sensing")
        return result

    def weather(self, deadline):
        result = self.request("GET", "/api/v1/weather", deadline=deadline).body
        if (not isinstance(result, dict) or type(result.get("available")) is not bool
                or type(result.get("stale")) is not bool or not isinstance(result.get("text"), str)):
            raise ContractError("invalid weather briefing")
        if result.get("basedOn") is not None:
            measured_time(result["basedOn"])
        return result
