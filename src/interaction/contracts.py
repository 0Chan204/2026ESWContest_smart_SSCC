"""Voice v0.7 only. Do not relax the existing automation/fall validators."""
from copy import deepcopy

from src.integration.schemas import ContractError, measured_time, number

ROOMS = {"room", "kitchen", "toilet"}
ACTIONS = {"light": {"on", "off", "blink", "fadeout"},
           "fan": {"on", "off", "set_speed"}, "water_purifier": {"dispense"},
           "stove": {"turn_on", "turn_off", "set_level", "restore_power"}}
ACTIONS["air_purifier"] = {"on", "off", "set_mode"}
REQUEST_FIELDS = {"voiceId", "text", "rawText", "wakeWord", "lang", "confidence", "source", "recognizedAt", "receivedAt", "expiresAt"}


def string(value, name, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContractError("invalid " + name)
    return value


def request_message(raw, now, *, allow_expired=False):
    if not isinstance(raw, dict) or set(raw) - REQUEST_FIELDS:
        raise ContractError("invalid voice request fields")
    data = deepcopy(raw)
    string(data.get("voiceId"), "voiceId", 100)
    string(data.get("text"), "text")
    if "rawText" in data:
        string(data["rawText"], "rawText")
    if "wakeWord" in data and type(data["wakeWord"]) is not bool:
        raise ContractError("wakeWord must be boolean")
    expires = measured_time(data.get("expiresAt"))
    if not allow_expired and now >= expires:
        raise ContractError("voice request expired")
    for field in ("recognizedAt", "receivedAt"):
        if data.get(field) is not None:
            at = measured_time(data[field])
            if at > now or at > expires:
                raise ContractError("future or inconsistent voice time")
    if data.get("confidence") is not None:
        number(data["confidence"], "STT confidence", confidence=True)
    for field, limit in (("lang", 20), ("source", 30)):
        if field in data:
            string(data[field], field, limit)
    return data


def action_payload(raw):
    if not isinstance(raw, dict) or raw.get("device") not in ACTIONS:
        raise ContractError("unsupported voice device")
    if raw.get("action") not in ACTIONS[raw["device"]]:
        raise ContractError("unsupported voice action")
    string(raw.get("deviceId"), "deviceId", 100)
    extra = {"turn_on": "level", "set_level": "level", "blink": "durationSec", "dispense": "amountMl", "set_speed": "speed", "set_mode": "mode"}.get(raw["action"])
    if set(raw) - ({"device", "deviceId", "action"} | ({extra} if extra else set())):
        raise ContractError("unexpected voice action fields")
    if extra == "mode":
        if raw.get(extra) not in {"auto", "manual"}:
            raise ContractError("invalid purifier mode")
    elif extra == "speed":
        if raw.get(extra) not in {"low", "mid", "high"}:
            raise ContractError("invalid fan speed")
    elif extra:
        maximum = {"level": 9, "durationSec": 600, "amountMl": 2000}[extra]
        if type(raw.get(extra)) is not int or not 1 <= raw[extra] <= maximum:
            raise ContractError("invalid voice action parameter")
    return deepcopy(raw)


def decision_payload(raw):
    allowed = {"decisionId", "voiceId", "scenario", "confidence", "timestamp", "room",
               "announcement", "actions", "requiresConfirmation", "expiresAt"}
    if not isinstance(raw, dict) or set(raw) - allowed or raw.get("scenario") != "voice_command":
        raise ContractError("invalid voice decision")
    for key in ("voiceId", "decisionId"):
        string(raw.get(key), key, 100)
    string(raw.get("announcement"), "announcement")
    number(raw.get("confidence"), "voice confidence", confidence=True)
    measured_time(raw.get("timestamp"))
    if "expiresAt" in raw:
        measured_time(raw["expiresAt"])
    if raw.get("room") is not None and raw["room"] not in ROOMS:
        raise ContractError("invalid voice room")
    if type(raw.get("requiresConfirmation", False)) is not bool:
        raise ContractError("invalid requiresConfirmation")
    if not isinstance(raw.get("actions"), list) or len(raw["actions"]) > 1:
        raise ContractError("voice supports one unambiguous control per request")
    for action in raw["actions"]:
        action_payload(action)
        safe_off = action["device"] == "stove" and action["action"] == "turn_off"
        if (not safe_off and not raw.get("requiresConfirmation")) or not raw.get("room"):
            raise ContractError("voice controls require confirmation and a verified room")
    return deepcopy(raw)


def decision_response(status, raw, request, *, polling=False):
    if status not in (200, 202) or not isinstance(raw, dict):
        raise ContractError("invalid voice response")
    for key in ("decisionId", "voiceId"):
        if raw.get(key) != request[key]:
            raise ContractError("voice response identity mismatch")
    if not polling and (type(raw.get("duplicate")) is not bool or raw["duplicate"] != (status == 200)):
        raise ContractError("invalid voice duplicate status")
    for key in ("scenario", "confidence"):
        if key in raw and raw[key] != request[key]:
            raise ContractError("voice response context mismatch")
    state = raw.get("status")
    if state not in {"executed", "awaiting_confirmation", "expired", "cancelled", "answered"}:
        raise ContractError("invalid voice response status")
    if "receivedAt" in raw:
        measured_time(raw["receivedAt"])
    if "requiresConfirmation" in raw and (type(raw["requiresConfirmation"]) is not bool
            or raw["requiresConfirmation"] != request.get("requiresConfirmation", False)):
        raise ContractError("voice confirmation mismatch")
    actions = raw.get("actions")
    if not isinstance(actions, list):
        raise ContractError("missing voice response actions")
    if state == "expired":
        if actions:
            raise ContractError("expired voice actions must be empty")
        return deepcopy(raw)
    expected = [(a["device"], a["deviceId"], a["action"]) for a in request["actions"]]
    actual = []
    for action in actions:
        if not isinstance(action, dict):
            raise ContractError("invalid voice action result")
        allowed = {"pending"} if state == "awaiting_confirmation" else (
            {"cancelled"} if state == "cancelled" else {"sent", "rejected", "failed"})
        if action.get("status") not in allowed:
            raise ContractError("voice action state mismatch")
        actual.append(tuple(action.get(k) for k in ("device", "deviceId", "action")))
    if actual != expected or (state == "awaiting_confirmation" and not expected) or (state == "answered" and expected):
        raise ContractError("voice response action mismatch")
    return deepcopy(raw)


def command_list(raw, now):
    # Confirmed in backend 00e59be app/schemas.py: VoiceCommandListResponse.
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list) or type(raw.get("total")) is not int:
        raise ContractError("voice list requires items and total")
    results = []
    for item in raw["items"]:
        if not isinstance(item, dict) or item.get("status") not in {
                "received", "thinking", "confirm_required", "executed", "answered", "cancelled", "timeout", "failed"}:
            raise ContractError("invalid voice command record")
        message = request_message({k: v for k, v in item.items() if k in REQUEST_FIELDS}, now, allow_expired=True)
        results.append({**deepcopy(item), **message})
    return results
