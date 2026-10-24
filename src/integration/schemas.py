from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite

from src.control.identifiers import DEVICES, ROOMS


class ContractError(ValueError):
    pass


def measured_time(value: str) -> float:
    if not isinstance(value, str):
        raise ContractError("time must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid ISO 8601 time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError("time requires an explicit timezone")
    return parsed.timestamp()


def iso_time(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def number(value, name, *, nullable=False, confidence=False):
    if value is None and nullable:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ContractError(f"{name} must be finite")
    if confidence and not 0 <= value <= 1:
        raise ContractError(f"{name} must be between 0 and 1")
    return value


def device_items(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ContractError("device states require items[]")
    items = deepcopy(payload["items"])
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ContractError("device item must be an object")
        for field in ("device", "deviceId", "room"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise ContractError(f"missing device field:{field}")
        if item["deviceId"] in ids:
            raise ContractError("duplicate deviceId in snapshot")
        ids.add(item["deviceId"])
        if item.get("updatedAt") is not None:
            measured_time(item["updatedAt"])
        elif item.get("online") is not False:
            raise ContractError("online device needs updatedAt")
        for field in ("online", "is_on"):
            if type(item.get(field)) is not bool:
                raise ContractError(f"{field} must be boolean")
        if not isinstance(item.get("current_state"), dict) and not (item.get("current_state") is None and item["online"] is False):
            raise ContractError("current_state must be an object")
        if item.get("control_state") not in (None, "user", "homevis"):
            raise ContractError("unrecognized control_state")
    return items


def decision_payload(payload: dict, *, allow_null_confidence=True) -> dict:
    if not isinstance(payload, dict):
        raise ContractError("decision must be an object")
    data = deepcopy(payload)
    for field in ("decisionId", "scenario", "reason", "timestamp", "room"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise ContractError(f"missing decision field:{field}")
    measured_time(data["timestamp"])
    if data["room"] not in ROOMS:
        raise ContractError("decision room must be room, kitchen or toilet")
    if "confidence" not in data:
        raise ContractError("missing decision confidence")
    number(data["confidence"], "confidence", nullable=allow_null_confidence, confidence=True)
    if type(data.get("weatherBriefing", False)) is not bool:
        raise ContractError("weatherBriefing must be boolean")
    if not isinstance(data.get("actions"), list):
        raise ContractError("decision requires actions[]")
    if not data["actions"] and data["scenario"] not in {"fall_detected", "power_saving", "power_saving_end"} and not data.get("announcement"):
        raise ContractError("empty actions requires a backend-managed scenario or announcement")
    if data.get("announcement") is not None and (not isinstance(data["announcement"], str)
                                                  or not 0 < len(data["announcement"]) <= 500):
        raise ContractError("announcement must contain 1..500 characters")
    if data.get("expiresAt") is not None:
        measured_time(data["expiresAt"])
    for action in data["actions"]:
        if not isinstance(action, dict) or not all(isinstance(action.get(k), str) and action[k]
                                                  for k in ("device", "action")):
            raise ContractError("invalid action")
        if action["action"] == "dispense":
            if action["device"] != "water_purifier":
                raise ContractError("dispense requires water_purifier")
            if type(action.get("amountMl")) is not int or action["amountMl"] <= 0:
                raise ContractError("dispense requires a positive integer amountMl")
        if action["action"] == "set_level" and (type(action.get("level")) is not int or not 1 <= action["level"] <= 9):
            raise ContractError("set_level requires level 1..9")
        if action["device"] not in DEVICES:
            raise ContractError("unsupported decision device")
    return data


def decision_response(status: int, payload: dict, request: dict) -> dict:
    if status not in {200, 202} or not isinstance(payload, dict):
        raise ContractError("unexpected decision response")
    data = deepcopy(payload)
    if data.get("decisionId") != request["decisionId"]:
        raise ContractError("response decisionId mismatch")
    if type(data.get("duplicate")) is not bool or data["duplicate"] != (status == 200):
        raise ContractError("HTTP 200 requires duplicate=true; HTTP 202 requires duplicate=false")
    if data.get("scenario") != request["scenario"] or data.get("confidence") != request["confidence"]:
        raise ContractError("response decision identity mismatch")
    measured_time(data.get("receivedAt"))
    number(data.get("confidence"), "response.confidence", nullable=request["confidence"] is None, confidence=True)
    weather = data.get("weather")
    if weather is not None:
        if (not isinstance(weather, dict) or type(weather.get("available")) is not bool
                or type(weather.get("stale")) is not bool
                or (weather.get("text") is not None and not isinstance(weather["text"], str))):
            raise ContractError("invalid weather response")
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise ContractError("response action count mismatch")
    if data.get("status") == "expired":
        if request["scenario"] == "fall_detected" or actions:
            raise ContractError("invalid expired decision response")
        return data
    if data.get("status") not in (None, "executed"):
        raise ContractError("invalid decision status")
    # Match by device/action, not by response order.
    expected = sorted((a["device"], a["action"]) for a in request["actions"])
    actual = []
    for action in actions:
        if not isinstance(action, dict) or action.get("status") not in ("sent", "rejected", "failed"):
            raise ContractError("invalid action status")
        if not all(isinstance(action.get(key), str) and action[key] for key in ("device", "action")):
            raise ContractError("invalid response action identity")
        actual.append((action.get("device", ""), action.get("action", "")))
    if request["scenario"] == "fall_detected":
        # The backend adds its own emergency actions even when actions=[] was sent.
        builtins = {("stove", "turn_off"), ("light", "blink")}
        expected = [pair for pair in expected if pair not in builtins]
        actual = [pair for pair in actual if pair not in builtins]
        if not isinstance(data.get("fallIncidentId"), str) or not data["fallIncidentId"]:
            raise ContractError("fall response requires fallIncidentId")
    if sorted(actual) != expected:
        raise ContractError("response action identity mismatch")
    return data
