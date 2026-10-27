"""Manual voice requests are validated proposals; only the backend executes them."""
import re
from src.integration.schemas import ContractError, measured_time, number
from .contracts import action_payload, ROOMS


def select_device(intent, devices, now, max_age):
    choices = [d for d in devices if d["device"] == intent["device"]
               and (not intent["room"] or d["room"] == intent["room"])]
    if len(choices) != 1:
        raise ContractError("device target is ambiguous or missing")
    device = choices[0]
    if (not device["online"] or device["room"] not in ROOMS or not device.get("updatedAt")
            or not 0 <= now - measured_time(device["updatedAt"]) < max_age):
        raise ContractError("device state is stale or unavailable")
    return device


def propose_control(intent, devices, request, runtime, voice_config, now):
    if (request.get("confidence") is None or request["confidence"] < voice_config.min_stt_confidence
            or intent["confidence"] < voice_config.min_intent_confidence):
        raise ContractError("insufficient voice control confidence")
    if set(intent["intents"]) != {"control_request"}:
        raise ContractError("mixed control requests require clarification")
    if intent["device"] == "stove" and intent["action"] == "turn_on":
        level = intent["parameters"].get("level")
        if (type(level) is not int or not re.search(r"인덕션|화구|레인지", request["text"])
                or not re.search(r"켜|켜줘", request["text"])
                or not re.search(rf"(?<!\d){level}\s*(?:단|단계)", request["text"])):
            raise ContractError("stove activation requires an explicit level and user request")
    device = select_device(intent, devices, now, runtime.config.device_max_age)
    action = action_payload({"device": device["device"], "deviceId": device["deviceId"],
                             "action": intent["action"], **intent["parameters"]})
    validate_safety(runtime, action, device, now)
    return action, device


def validate_safety(runtime, action, device, now):
    # Run again immediately before dispatch; no LLM or HTTP on the owner thread.
    engine, config = runtime.controller.realtime_engine, runtime.config
    requested_room = device["room"]
    for observation in runtime.devices.values():
        if observation.raw["deviceId"] == device["deviceId"] and observation.measured_at >= measured_time(device["updatedAt"]):
            if observation.measured_at == measured_time(device["updatedAt"]) and any(
                    observation.raw.get(key) != device.get(key)
                    for key in ("device", "room", "online", "is_on", "current_state", "control_state")):
                raise ContractError("conflicting same-time device state")
            device = observation.raw
    if device["deviceId"] != action["deviceId"] or device["device"] != action["device"] or device["room"] != requested_room:
        raise ContractError("control target changed")
    if (not device["online"] or not 0 <= now - measured_time(device["updatedAt"]) < config.device_max_age):
        raise ContractError("device state stale before send")
    safe_off = action["device"] == "stove" and action["action"] == "turn_off"
    if not safe_off and runtime.home_automation.away_active:
        raise ContractError("away safety control takes priority")
    if not safe_off and (runtime.outbox.fall_incident() or engine.current_state == "DANGER"):
        raise ContractError("emergency takes priority")
    if action["device"] not in {"stove", "water_purifier"} or safe_off:
        return
    sample = engine._sensing
    latest = runtime._latest_received_location
    if (sample is None or engine.sensing_invalid or not sample.detected or sample.location != "kitchen"
            or engine.last_user_location != "kitchen" or sample.confidence < engine.config.MIN_CONFIDENCE
            or not 0 <= now - sample.timestamp < engine.config.UNKNOWN_TIMEOUT
            or latest is None or not latest.valid or latest.sample.location != "kitchen"
            or latest.valid_until is not None and now >= latest.valid_until):
        raise ContractError("confirmed kitchen presence required")
    if action["device"] == "water_purifier":
        observation = runtime.state_mapper.map(device, now)
        if not runtime.state_mapper.water_ready(observation, now):
            raise ContractError("water not ready")
        return
    if not config.accepts_device("stove", device["deviceId"]):
        raise ContractError("unmapped stove safety target")
    state = device["current_state"]
    # Reducing an already-running burner remains a safety-direction request.
    lower_level = (action["action"] == "set_level" and device["is_on"]
                   and type(state.get("level")) is int and action["level"] < state["level"])
    if not config.stove_temperature_trusted and not lower_level:
        raise ContractError("stove temperature validity contract unconfirmed")
    temperature = number(state.get("temperature"), "stove temperature")
    if (not config.temperature_is_celsius or engine.appliance_invalid
            or temperature >= engine.config.HIGH_TEMPERATURE_C
            or engine._temperature_rate is not None and engine._temperature_rate >= engine.config.RISING_TEMPERATURE_C_PER_SECOND
            or any(state.get(key) for key in ("smoke", "fire", "abnormal"))):
        raise ContractError("stove change not confirmed safe")
    if action["action"] == "restore_power":
        evidence = runtime._restore_evidence(runtime.state_mapper.map(device, now))
        if evidence.appliance is None or evidence.appliance.control_state != "HOMEVIS_REDUCED":
            raise ContractError("fresh restore provenance unconfirmed")
        reason = runtime._revalidate({"source_id": "voice-safety", "source": {},
                                      "payload": {"room": device["room"], "actions": [action]}}, now)
        if reason:
            raise ContractError(reason)
    elif action["action"] == "turn_on":
        if device["is_on"] or state.get("state") != "off":
            raise ContractError("stove activation requires confirmed off state")
    elif action["action"] == "set_level":
        if not device["is_on"]:
            raise ContractError("set_level requires an already running stove")
    else:
        raise ContractError("unsupported manual stove operation")
