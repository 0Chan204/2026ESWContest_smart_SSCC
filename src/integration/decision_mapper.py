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

    def map_home_rule(self, scenario, episode_id, timestamp, confidence, evidence, *, action=None):
        """Narrow v0.7 contracts; no changes to learned automation scoring."""
        if scenario not in {"cooking_air_clean", "away_all_off"}:
            raise ValueError("unsupported home rule")
        identity = f"home:{scenario}:{episode_id}:{action or 'all_off'}"
        reason = ("Confirmed stove operation and purifier state" if scenario == "cooking_air_clean"
                  else "Valid whole-home absence sustained for the configured interval")
        source = {"type": "HomeAutomationDecision", "scenario": scenario, "timestamp": timestamp,
                  "episode_id": episode_id, "action": action, "reason": reason, "details": evidence,
                  "confidence_basis": ("telemetry_freshness_not_probability" if action else "minimum_absence_confidence")}
        if self.config.rule_confidence_policy == "block":
            return MappedDecision(identity, None, "rule_confidence_policy_blocked", source)
        body = {"decisionId": "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
                "scenario": scenario, "confidence": confidence, "reason": reason,
                "timestamp": iso_time(timestamp), "expiresAt": iso_time(timestamp + self.config.command_ttl), "actions": []}
        if scenario == "cooking_air_clean":
            body.update(room="room", actions=[{"device": "air_purifier",
                "deviceId": self.config.device_ids.get("air_purifier", "air-01"), "action": action}],
                announcement="조리 연동으로 공기청정기 " + ("켜기" if action == "on" else "끄기") + "를 요청합니다.")
        return MappedDecision(identity, decision_payload(body, allow_null_confidence=False), None, source)

    def map(self, output, *, emergency=False, evidence_confidence=None, stove_level=None) -> MappedDecision:
        identity = source_id(output)
        source = {"type": type(output).__name__, **output.to_dict()}

        def blocked(reason):
            return MappedDecision(identity, None, reason, source)

        rule_confidence = None
        if not isinstance(output, AutomationAction) and self.config.rule_confidence_policy == "observed":
            if evidence_confidence is None:
                return blocked("measured_rule_confidence_missing")
            rule_confidence = evidence_confidence
            source["confidence_basis"] = "minimum_observed_location_and_behavior_confidence"
            source["input_confidence"] = evidence_confidence

        if isinstance(output, ScenarioAction) and output.scenario == "bathroom_fall":
            if self.config.backend_fall_scenario and output.event == "fall_detected":
                incident_id = (output.details or {}).get("incident_id")
                if not incident_id:
                    return blocked("fall_incident_id_missing")
                identity = "fall:" + incident_id
                body = decision_payload({
                    "decisionId": "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
                    "scenario": self.config.backend_fall_scenario,
                    "confidence": rule_confidence, "reason": output.reason,
                    "timestamp": iso_time(output.timestamp), "room": "toilet",
                    "actions": [] if self.config.backend_v05 else list(self.config.fall_actions), "weatherBriefing": False,
                }, allow_null_confidence=self.config.rule_confidence_policy == "null")
                return MappedDecision(identity, body, None, source)
            return blocked("backend_managed_fall:local_stage_not_sent")
        if emergency and getattr(output, "action", None) == "restore_power":
            return blocked("emergency_active:restore_suppressed")
        if getattr(output, "action", None) == "restore_power" and not self.config.backend_restore:
            return blocked("restore_control_provenance_unconfirmed")
        confidence = rule_confidence
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
            if (self.config.multi_room_lights and isinstance(output, AutomationAction)
                    and output.scenario in {"light_auto_on", "light_auto_off"} and device == "light"
                    and output.device_id is not None):
                internal_room = output.room
            internal_room = canonical_room(internal_room)
            # A configured route is not permission to change command semantics.
            allowed_alias = self.config.backend_v05 and (
                (device == "light" and (output.action, action) in {("turn_on", "on"), ("turn_off", "off")})
                or (device == "stove" and output.action == "reduce_power" and action == "set_level"))
            if action != output.action and not allowed_alias:
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
            if self.config.backend_v05 and action == "set_level":
                if type(stove_level) is not int or not 1 < stove_level <= 9:
                    return blocked("stove_level_unavailable_or_minimum")
                actions[0]["level"] = max(1, stove_level - self.config.stove_reduce_steps)
        body = decision_payload({
            "decisionId": "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
            "scenario": scenario, "confidence": confidence, "reason": reason,
            "timestamp": iso_time(output.timestamp), "room": room,
            "actions": actions, "weatherBriefing": weather,
        }, allow_null_confidence=self.config.rule_confidence_policy == "null")
        if self.config.backend_v05:
            body["expiresAt"] = iso_time(output.timestamp + self.config.command_ttl)
            for action in body["actions"]:
                action["deviceId"] = (getattr(output, "device_id", None) or self.config.device_ids[action["device"]])
        return MappedDecision(identity, body, None, source)
