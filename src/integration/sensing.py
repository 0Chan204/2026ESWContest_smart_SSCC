"""Final location results only. No Pi feature or node-ID classification."""
from copy import deepcopy
from dataclasses import dataclass, replace

from src.control.realtime_models import SensingUpdate
from src.control.identifiers import canonical_room
from .config import IntegrationConfig
from .schemas import ContractError, measured_time, number


@dataclass(frozen=True)
class LocationObservation:
    raw: dict
    measured_at: float
    received_at: float
    valid: bool
    diagnostic: str | None
    sample: SensingUpdate
    valid_until: float | None = None


def location_observation(payload: dict, received_at: float, config: IntegrationConfig) -> LocationObservation:
    if not isinstance(payload, dict):
        raise ContractError("location result must be an object")
    if "features" in payload:
        raise ContractError("expected final location JSON, not Pi features")
    timestamp = measured_time(payload.get("time"))
    valid_until = measured_time(payload["valid_until"]) if "valid_until" in payload else None
    raw_location = payload.get("location")
    if not isinstance(raw_location, str):
        raise ContractError("location must be a string")
    if "location_confidence" not in payload:
        raise ContractError("missing location_confidence")
    confidence = number(payload["location_confidence"], "location_confidence",
                        nullable=True, confidence=True)
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ContractError("reason must be a string or null")
    explanation = payload.get("location_explanation")
    if explanation is not None and not isinstance(explanation, str):
        raise ContractError("location explanation must be a string or null")
    if "valid" in payload and type(payload["valid"]) is not bool:
        raise ContractError("location valid must be boolean")
    diagnostic = None
    location = "unknown"
    if raw_location in {"empty", "unknown"}:
        diagnostic = f"location_{raw_location}"
    else:
        try:
            location = config.internal_room(raw_location)
        except ValueError as exc:
            diagnostic = str(exc)
    if confidence is None:
        diagnostic = diagnostic or "missing_location_confidence"
    # No enumerated reason allowlist: config_mismatch and detailed node errors survive.
    if reason:
        diagnostic = diagnostic or "sensing_reason_present"
    if payload.get("valid") is False:
        diagnostic = diagnostic or "location_marked_invalid"
    if valid_until is not None and valid_until <= timestamp:
        diagnostic = diagnostic or "invalid_location_validity"
    if valid_until is not None and received_at >= valid_until:
        diagnostic = diagnostic or "location_result_expired"
    valid = diagnostic is None
    sample = SensingUpdate(location, timestamp, confidence=confidence if confidence is not None else 0.0,
                           detected=valid, observation_valid=valid, activity_observed=False,
                           location_reason=explanation, received_at=received_at)
    return LocationObservation(deepcopy(payload), timestamp, received_at, valid, diagnostic, sample, valid_until)


@dataclass(frozen=True)
class BehaviorObservation:
    """Internal measured behavior stream; this is not a Wi-Fi wire protocol."""
    measured_at: float
    valid_until: float
    location: str
    confidence: float | None = None
    activity: str | None = None
    motion_state: str | None = None
    fall_detected: bool | None = None
    valid: bool = True
    reason: str | None = None
    explanation: str | None = None
    event: str | None = None
    event_id: str | None = None
    raw_activity: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "location", canonical_room(self.location))
        number(self.measured_at, "behavior.measured_at")
        number(self.valid_until, "behavior.valid_until")
        number(self.confidence, "behavior.confidence", nullable=True, confidence=True)
        if self.valid_until <= self.measured_at:
            raise ContractError("behavior validity must end after measurement")
        if type(self.valid) is not bool:
            raise ContractError("behavior.valid must be boolean")
        for name in ("reason", "explanation", "event_id", "raw_activity", "activity"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                raise ContractError(f"behavior.{name} must be a string or null")
        if self.event is not None and (not isinstance(self.event_id, str) or not self.event_id.strip()):
            raise ContractError("behavior events require a stable event ID")
        # Reuse the existing model's location, motion and fall validation.
        SensingUpdate(self.location, self.measured_at, motion_state=self.motion_state,
                      fall_detected=self.fall_detected, activity_event=self.event)


def join_behavior(location: LocationObservation, behavior: BehaviorObservation | None,
                  max_skew: float) -> SensingUpdate:
    if (behavior is None or not location.valid or not behavior.valid or behavior.reason
            or behavior.location != location.sample.location
            or not behavior.measured_at <= location.measured_at < behavior.valid_until
            or location.measured_at - behavior.measured_at > max_skew
            or behavior.confidence is None
            or (behavior.raw_activity != "none" and all(v is None for v in (
                behavior.activity, behavior.motion_state, behavior.fall_detected, behavior.event)))):
        return location.sample
    return replace(location.sample, activity=behavior.activity or "unknown",
                   motion_state=behavior.motion_state, fall_detected=behavior.fall_detected,
                   activity_confidence=behavior.confidence, activity_observed=location.received_at < behavior.valid_until,
                   activity_timestamp=behavior.measured_at, activity_valid_until=behavior.valid_until,
                   activity_event=behavior.event, activity_event_id=behavior.event_id,
                   activity_reason=behavior.explanation, raw_activity=behavior.raw_activity or behavior.activity)
