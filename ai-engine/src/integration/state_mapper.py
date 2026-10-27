from dataclasses import dataclass

from src.control.realtime_models import ApplianceUpdate
from src.control.identifiers import canonical_device
from .config import IntegrationConfig
from .schemas import ContractError, measured_time, number


def purifier_state(item, now, max_age):
    """Read reported classifications, never calculate a PM threshold.

    lastControl is optional: backend v0.7 currently strips it from the AI GET.
    Missing provenance is not evidence of AI ownership.
    """
    state = item["current_state"]
    at = measured_time(item["updatedAt"])
    reported = measured_time(state.get("reportedAt"))
    if (not item["online"] or not 0 <= now - at < max_age or not 0 <= now - reported < max_age
            or state.get("power") not in {"on", "off"} or (state["power"] == "on") != item["is_on"]
            or state.get("mode") not in {"auto", "manual"}):
        raise ContractError("purifier state unavailable or stale")
    quality = state.get("airQuality")
    if not isinstance(quality, dict) or quality.get("level") not in {"good", "normal", "bad"}:
        raise ContractError("purifier air quality unavailable")
    for key in ("pm25", "pm10"):
        if quality.get(key) is not None and number(quality[key], key) < 0:
            raise ContractError("invalid air quality measurement")
    control = state.get("lastControl")
    if control is not None and (not isinstance(control, dict) or control.get("publisher") not in {"user", "system", "api"}
            or control.get("commandId") is not None and not isinstance(control["commandId"], str)):
        raise ContractError("invalid purifier control provenance")
    return {"level": quality["level"], "quality": quality, "mode": state["mode"],
            "reported_at": reported, "control": control}


@dataclass(frozen=True)
class DeviceObservation:
    raw: dict
    measured_at: float
    fetched_at: float
    room: str | None
    appliance: ApplianceUpdate | None
    diagnostics: tuple[str, ...]


class StateMapper:
    def __init__(self, config: IntegrationConfig):
        self.config = config

    def map(self, item: dict, fetched_at: float) -> DeviceObservation:
        c = self.config
        diagnostics = []
        room = None
        appliance = None
        device = canonical_device(item["device"])
        timestamp = measured_time(item["updatedAt"])
        if not c.accepts_device(device, item["deviceId"]):
            diagnostics.append(f"unmapped_device:{item['deviceId']}")
        try:
            room = c.internal_room(item["room"])
        except ValueError as exc:
            diagnostics.append(str(exc))
        if not item["online"]:
            diagnostics.append("device_offline")
        if timestamp > fetched_at:
            diagnostics.append("future_device_measurement")
        if fetched_at - timestamp >= c.device_max_age:
            diagnostics.append("device_snapshot_stale")
        if device == "air_purifier":
            try:
                purifier_state(item, fetched_at, c.device_max_age)
            except (ValueError, TypeError, KeyError):
                diagnostics.append("purifier_state_or_air_quality_invalid")
        if not diagnostics and device == "stove":
            state = item["current_state"]
            level = state.get("level")
            if level is not None and type(level) is not int:
                raise ValueError("level must be an integer or null")
            watts = None
            if c.watts_field and c.watts_field in state:
                watts = number(state[c.watts_field], c.watts_field)
            elif type(state.get("level")) is int and state["level"] in c.level_to_watts:
                watts = c.level_to_watts[state["level"]]
            if watts is None and c.automation_profile == "legacy":
                diagnostics.append("power_watts_unmeasured")
            temperature = None
            if state.get("temperature") is not None:
                number(state["temperature"], "temperature")
            if c.temperature_is_celsius and state.get("temperature") is not None:
                temperature = number(state["temperature"], "temperature")
            elif state.get("temperature") is not None:
                diagnostics.append("temperature_unit_unconfirmed")
            # Ownership is not evidence of reduction or manual override.
            diagnostics.append("restore_requires_local_reduction_and_observed_lower_level" if c.backend_restore
                               else "control_provenance_unconfirmed:automatic_restore_disabled")
            appliance = ApplianceUpdate(item["is_on"], timestamp, power_watts=watts,
                                        temperature_c=temperature, control_state=None, level=level)
        return DeviceObservation(item, timestamp, fetched_at, room, appliance, tuple(diagnostics))

    def water_ready(self, observation: DeviceObservation | None, now: float) -> bool:
        # Never use status=idle (or later user activity) as dispensing readiness.
        field = self.config.water_ready_field
        if observation is None or observation.diagnostics:
            return False
        raw = observation.raw
        if self.config.water_readiness_mode == "backend_idle":
            # This is the WATER DEVICE state from GET /ai/device-states,
            # never the user's Wi-Fi activity (idle/sitting/lying).
            return bool(raw["device"] == "water_purifier" and raw["online"]
                        and observation.room == "kitchen"
                        and 0 <= now - observation.measured_at < self.config.device_max_age
                        and raw["current_state"].get("status") == "idle")
        if field is None:
            return False
        return bool(canonical_device(raw["device"]) == "water_purifier" and raw["online"]
                    and 0 <= now - observation.measured_at < self.config.device_max_age
                    and raw["current_state"].get(field) in self.config.water_ready_states)
