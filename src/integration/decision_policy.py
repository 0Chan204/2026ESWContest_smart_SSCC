"""Load operator-editable connections and decision criteria."""
from dataclasses import fields, replace
from datetime import time
from pathlib import Path
import tomllib

from src.control.confidence.config import ConfidenceConfig
from src.control.realtime_config import RealtimeConfig
from src.llm.config import LLMConfig


INTEGRATION_KEYS = {
    "sensing": {"allowed_lateness", "device_max_age", "behavior_max_skew"},
    "automation": {"automation_profile", "automation_absence_seconds", "automation_return_seconds",
                   "light_on_seconds", "light_off_seconds", "stove_reduce_steps"},
}
CONNECTION_KEYS = {
    "backend": {"base_url", "http_timeout", "poll_interval"},
    "mqtt": {"host", "port", "client_id", "location_topic", "behavior_topic",
             "fall_status_topic", "tls", "ca_file"},
}
CONFIDENCE_SCALARS = {
    "medium_confidence_threshold", "feedback_learning_rate", "feedback_apply_threshold",
    "feedback_review_threshold", "min_weight", "max_weight", "max_stove_power_watts", "sensor_history_size",
}
PROFILES = {"legacy", "location_level_v1"}


def table(value, name, allowed=None):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table")
    if allowed is not None and set(value) - allowed:
        raise ValueError(f"unknown {name} keys: {sorted(set(value) - allowed)}")
    return value


def config_values(cls, values):
    """Reject misspelled keys, booleans as seconds, and invalid local clock times."""
    field_types = {field.name: field.type for field in fields(cls)}
    allowed = {name.lower() for name in field_types}
    values = table(values, cls.__name__, allowed)
    defaults, result = cls(), {}
    for key, value in values.items():
        name = key.upper()
        default = getattr(defaults, name)
        if isinstance(default, time):
            value = time.fromisoformat(value) if isinstance(value, str) else value
            valid = isinstance(value, time) and value.tzinfo is None
        elif type(default) is bool:
            valid = type(value) is bool
        elif field_types[name] is int:
            valid = type(value) is int
        else:
            valid = type(value) in (int, float)
        if not valid:
            raise ValueError(f"invalid type for {cls.__name__}.{key}")
        result[name] = value
    return result


def merge_policy(raw, config_path):
    """Paths are relative to homevis.toml, never the process working directory."""
    reference = raw.get("decision_policy")
    if reference is None:
        return raw  # Existing standalone configurations remain supported.
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("decision_policy must name a TOML file")
    with (Path(config_path).resolve().parent / reference).open("rb") as stream:
        policy = tomllib.load(stream)
    table(policy, "decision policy", set(INTEGRATION_KEYS) | set(CONNECTION_KEYS) | {
        "realtime", "scenarios", "home_automation", "confidence", "voice", "llm"})
    merged = {key: dict(value) if isinstance(value, dict) else value for key, value in raw.items()}

    def add(section, values):
        destination = merged.setdefault(section, {})
        overlap = set(destination) & set(values)
        if overlap:
            raise ValueError(f"settings defined twice in {section}: {sorted(overlap)}")
        destination.update(values)

    for section, allowed in CONNECTION_KEYS.items():
        add(section, table(policy.get(section, {}), section, allowed))
    for section, allowed in INTEGRATION_KEYS.items():
        add("backend", table(policy.get(section, {}), section, allowed))
    for section in ("scenarios", "home_automation"):
        add(section, table(policy.get(section, {}), section))
    add("voice", table(policy.get("voice", {}), "voice",
                       {"min_stt_confidence", "min_intent_confidence", "history_seconds"}))
    add("backend", {
        "llm_config": LLMConfig(**table(policy.get("llm", {}), "llm", {"provider", "model", "failure_retry_seconds"})),
        "realtime_config": RealtimeConfig(**config_values(RealtimeConfig, policy.get("realtime", {}))),
        "confidence_options": table(policy.get("confidence", {}), "confidence",
                                    CONFIDENCE_SCALARS | {"weights", "thresholds"}),
    })
    return merged


def build_confidence_config(integration):
    options = table({} if integration.confidence_options is None else integration.confidence_options,
                    "confidence", CONFIDENCE_SCALARS | {"weights", "thresholds"})
    base = ConfidenceConfig.for_profile(integration.automation_profile,
        absence_seconds=integration.automation_absence_seconds,
        return_seconds=integration.automation_return_seconds,
        light_on_seconds=integration.light_on_seconds, light_off_seconds=integration.light_off_seconds)
    if integration.confidence_options is not None:
        # Legacy direct constructors retain their historic 60s default. A loaded
        # policy explicitly controls the four timing values for either profile.
        base = replace(base, KITCHEN_LEAVE_FULL_SECONDS=integration.automation_absence_seconds,
                       KITCHEN_RETURN_FULL_SECONDS=integration.automation_return_seconds,
                       LIGHT_PRESENCE_FULL_SECONDS=integration.light_on_seconds,
                       LIGHT_LEAVE_FULL_SECONDS=integration.light_off_seconds)
    scalars = {}
    for key in options.keys() & CONFIDENCE_SCALARS:
        value = options[key]
        valid = type(value) is int if key == "sensor_history_size" else type(value) in (int, float)
        if not valid:
            raise ValueError(f"invalid numeric confidence.{key}")
        scalars[key.upper()] = value
    thresholds = table(options.get("thresholds", {}), "confidence.thresholds", set(base.SCENARIO_THRESHOLDS))
    if any(type(value) not in (int, float) for value in thresholds.values()):
        raise ValueError("confidence thresholds must be numbers")
    profiles = table(options.get("weights", {}), "confidence.weights", PROFILES)
    # Validate inactive profiles too, so a typo cannot lurk until a later switch.
    for profile, scenarios in profiles.items():
        defaults = ConfidenceConfig.for_profile(profile)
        table(scenarios, f"confidence.weights.{profile}", set(defaults.SCENARIO_WEIGHTS))
        for scenario, weights in scenarios.items():
            expected = set(defaults.SCENARIO_WEIGHTS[scenario])
            table(weights, f"weights.{profile}.{scenario}", expected)
            if set(weights) != expected or any(type(value) not in (int, float) for value in weights.values()):
                raise ValueError(f"weights.{profile}.{scenario} must define every supported feature numerically")
        replace(defaults, **scalars, SCENARIO_WEIGHTS={**defaults.SCENARIO_WEIGHTS, **scenarios},
                SCENARIO_THRESHOLDS={**defaults.SCENARIO_THRESHOLDS, **thresholds})
    return replace(base, **scalars, SCENARIO_WEIGHTS={**base.SCENARIO_WEIGHTS, **profiles.get(base.INPUT_PROFILE, {})},
                   SCENARIO_THRESHOLDS={**base.SCENARIO_THRESHOLDS, **thresholds})
