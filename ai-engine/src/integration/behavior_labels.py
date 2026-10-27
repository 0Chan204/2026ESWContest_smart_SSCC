"""Confirmed classifier labels, separate from sustained posture observations.

The training report confirms labels, not the producer's wire protocol. The existing
backend activity field and the measured behavior adapter can carry these labels.
No CSI processing, probability recalibration, or inferred motion belongs here.
"""
from hashlib import sha256

OBSERVED_STATES = {"unknown", "lying", "sitting", "standing", "walking"}
BEHAVIOR_LABELS = {"none": None, "fall": "fall", "lie_down": "lie_down", "get_up": "wake"}


def observation_id(location: str, measured_at: float) -> str:
    """Stable *window observation* ID, not an invented physical-event/episode ID.

    Exclude label/confidence so changed predictions for the same measurement are
    conflicts, and exclude receipt time/database IDs so polling cannot renew it.
    """
    key = f"{location}:{float(measured_at).hex()}"
    return "behavior-window:" + sha256(key.encode("utf-8")).hexdigest()
