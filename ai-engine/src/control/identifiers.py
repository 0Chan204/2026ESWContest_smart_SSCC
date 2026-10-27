"""Canonical data names; legacy aliases are accepted only at input/read boundaries.

Scenario/history keys such as bathroom_fall are intentionally not renamed: they
are existing policy identifiers, not backend scenario names or room values.
"""

ROOMS = frozenset({"room", "kitchen", "toilet"})
DEVICES = frozenset({"stove", "light", "water_purifier"})


def canonical_room(value: str) -> str:
    return {"bedroom": "room", "bathroom": "toilet"}.get(value, value)


def canonical_device(value: str) -> str:
    return {"water_dispenser": "water_purifier", "induction": "stove"}.get(value, value)


def device_target(value: str, room: str | None = None) -> tuple[str, str | None]:
    """Read old room-qualified targets without mutating a persisted request."""
    if not isinstance(value, str) or (room is not None and not isinstance(room, str)):
        raise ValueError("invalid device target")
    room = None if room is None else canonical_room(room)
    if value.endswith("_light"):
        legacy_room = canonical_room(value[:-6])
        if room is not None and room != legacy_room:
            raise ValueError("target_room_mismatch")
        return "light", legacy_room
    return canonical_device(value), room
