import hashlib
import json
from dataclasses import dataclass

from src.control.automation_models import AutomationAction
from src.control.scenario_models import DeviceCommand, ScenarioAction
from src.control.identifiers import canonical_room, device_target
from .config import IntegrationConfig
from .schemas import decision_payload, iso_time


def source_id(output) -> str:
    if isinstance(output, AutomationAction):
        return "automation:" + output.action_id
    raw = type(output).__name__ + json.dumps(output.to_dict(), sort_keys=True, ensure_ascii=False)
    return "rule:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MappedDecision:
    source_id: str
    payload: dict | None
    diagnostic: str | None
    source: dict


class DecisionMapper:
    def __init__(self, config: IntegrationConfig, history):
        self.config = config
        self.history = history

    def map(self, output, *, emergency=False) -> MappedDecision:
        identity = source_id(output)
        source = {"type": type(output).__name__, **output.to_dict()}

        def blocked(reason):
            return MappedDecision(identity, None, reason, source)

        if isinstance(output, ScenarioAction) and output.scenario == "bathroom_fall":
            return blocked("backend_managed_fall:local_stage_not_sent")
        if emergency and getattr(output, "action", None) == "restore_power":
            return blocked("emergency_active:restore_suppressed")
        if getattr(output, "action", None) == "restore_power":
            return blocked("restore_control_provenance_unconfirmed")
        confidence = None
        if isinstance(output, AutomationAction):
            confidence = output.confidence
            record = self.history.get(output.action_id)
            source["explanation"] = record
            if not record:
                return blocked("automation_explanation_missing")
            reason = (f"{output.scenario}; confidence={output.confidence:g}; "
                      f"threshold={record['threshold']:g}; contributions="
                      + json.dumps(record["contributions"], sort_keys=True, ensure_ascii=False))
        else:
            reason = output.reason
            if self.config.rule_confidence_policy == "block":
                return blocked("rule_confidence_policy_blocked")
        weather = False
        if isinstance(output, DeviceCommand):
            if output.device != "water_purifier" or output.command_type != "DISPENSE_WATER":
                return blocked("unsupported_device_command")
            scenario, room = "water_dispense", "kitchen"
            actions = [{"device": "water_purifier", "action": "dispense", "amountMl": output.amount_ml}]
            weather = output.request_weather_info
        else:
            route = self.config.action_routes.get((output.scenario, output.action))
            if route is None:
                return blocked("scenario_action_contract_unconfirmed")
            scenario, device, action, internal_room = route
            internal_room = canonical_room(internal_room)
            # A configured route is not permission to change command semantics.
            if action != output.action:
                return blocked("action_semantics_mismatch")
            try:
                room = self.config.backend_room(internal_room)
            except ValueError as exc:
                return blocked(str(exc))
            target = output.device if isinstance(output, AutomationAction) else output.target
            target, target_room = device_target(target, output.room)
            if target == "stove" and target_room is None:
                target_room = "kitchen"  # Compatibility with old stove actions.
            if (device not in self.config.device_ids or target != device
                    or target_room != internal_room):
                return blocked("target_mapping_mismatch")
            actions = [{"device": device, "action": action}]
        body = decision_payload({
            "decisionId": "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
            "scenario": scenario, "confidence": confidence, "reason": reason,
            "timestamp": iso_time(output.timestamp), "room": room,
            "actions": actions, "weatherBriefing": weather,
        }, allow_null_confidence=self.config.rule_confidence_policy == "null")
        return MappedDecision(identity, body, None, source)
