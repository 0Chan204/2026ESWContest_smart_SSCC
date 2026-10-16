from dataclasses import dataclass

from src.control.realtime_models import ApplianceUpdate
from .config import IntegrationConfig
from .schemas import measured_time, number


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
        timestamp = measured_time(item["updatedAt"])
        if c.device_ids.get(item["device"]) != item["deviceId"]:
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
        if not diagnostics and item["device"] == "stove":
            state = item["current_state"]
            watts = None
            if c.watts_field and c.watts_field in state:
                watts = number(state[c.watts_field], c.watts_field)
            elif type(state.get("level")) is int and state["level"] in c.level_to_watts:
                watts = c.level_to_watts[state["level"]]
            if watts is None:
                diagnostics.append("power_watts_unmeasured")
            temperature = None
            if c.temperature_is_celsius and state.get("temperature") is not None:
                temperature = number(state["temperature"], "temperature")
            elif state.get("temperature") is not None:
                diagnostics.append("temperature_unit_unconfirmed")
            # Ownership is not evidence of reduction or manual override.
            diagnostics.append("control_provenance_unconfirmed:automatic_restore_disabled")
            appliance = ApplianceUpdate(item["is_on"], timestamp, power_watts=watts,
                                        temperature_c=temperature, control_state=None)
        return DeviceObservation(item, timestamp, fetched_at, room, appliance, tuple(diagnostics))

    def water_ready(self, observation: DeviceObservation | None, now: float) -> bool:
        if observation is None or observation.diagnostics:
            return False
        raw = observation.raw
        return bool(raw["device"] == "water_purifier" and raw["online"]
                    and 0 <= now - observation.measured_at < self.config.device_max_age
                    and raw["current_state"].get("status") in self.config.water_ready_states)
