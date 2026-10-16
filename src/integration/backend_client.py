"""Small standard-library HTTP client. Retries are scheduled by the runtime."""
import json
from http.client import HTTPException
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import IntegrationConfig
from .schemas import ContractError, decision_payload, decision_response, device_items


class BackendError(RuntimeError):
    def __init__(self, message: str, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class HTTPResult:
    status: int
    body: dict


class UrllibTransport:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def request(self, method, url, headers, body, timeout) -> HTTPResult:
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return HTTPResult(response.status, json.loads(response.read().decode("utf-8")))
        except HTTPError as exc:
            raise BackendError(f"backend HTTP {exc.code}",
                               retryable=exc.code in {408, 429} or 500 <= exc.code < 600) from exc
        except (URLError, TimeoutError, OSError, HTTPException) as exc:
            # Avoid logging URLs, authentication headers, or credentials from exceptions.
            raise BackendError("backend connection/timeout error", retryable=True) from exc
        except (ValueError, UnicodeError) as exc:
            raise BackendError("backend returned invalid JSON") from exc


class BackendClient:
    DEVICE_STATES_PATH = "/api/v1/ai/device-states"
    DECISIONS_PATH = "/api/v1/ai/decisions"

    def __init__(self, config: IntegrationConfig, transport=None):
        self.config = config
        if transport is None and config.mode != "live":
            raise ValueError("mock mode requires an explicit mock transport")
        if config.mode == "live" and getattr(transport, "mock_only", False):
            raise ValueError("mock transport cannot be used in live mode")
        self.transport = transport if transport is not None else UrllibTransport()

    def _request(self, method, path, body=None):
        headers = dict(self.config.headers)
        headers["Accept"] = "application/json"
        if body is not None:
            headers["Content-Type"] = "application/json"
        raw = None if body is None else json.dumps(body, sort_keys=True, ensure_ascii=False,
                                                  allow_nan=False, separators=(",", ":")).encode("utf-8")
        return self.transport.request(method, self.config.base_url.rstrip("/") + path,
                                      headers, raw, self.config.http_timeout)

    def fetch_device_states(self) -> list[dict]:
        response = self._request("GET", self.DEVICE_STATES_PATH)
        if response.status != 200:
            raise BackendError(f"device states HTTP {response.status}",
                               retryable=response.status in {408, 429} or response.status >= 500)
        return device_items(response.body)

    def post_decision(self, payload: dict) -> HTTPResult:
        body = decision_payload(payload, allow_null_confidence=self.config.rule_confidence_policy == "null")
        response = self._request("POST", self.DECISIONS_PATH, body)
        if response.status not in {200, 202}:
            raise BackendError(f"decision HTTP {response.status}",
                               retryable=response.status in {408, 429} or response.status >= 500)
        try:
            parsed = decision_response(response.status, response.body, body)
        except ContractError as exc:
            raise BackendError(str(exc)) from exc
        return HTTPResult(response.status, parsed)
