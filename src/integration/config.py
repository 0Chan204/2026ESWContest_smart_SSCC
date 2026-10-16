from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class IntegrationConfig:
    mode: str = "mock"
    base_url: str = ""
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    data_dir: Path = Path("output/integration")
    poll_interval: float = 2.0
    http_timeout: float = 3.0
    max_attempts: int = 3
    retry_interval: float = 2.0
    allowed_lateness: float = 2.0
    command_ttl: float = 15.0
    device_max_age: float = 20.0
    behavior_max_skew: float = 1.0
    room_is_bedroom: bool = False
    # These settings require confirmation by the deployment contract.
    temperature_is_celsius: bool = False
    level_to_watts: dict[int, float] = field(default_factory=dict)
    watts_field: str | None = None
    water_ready_states: tuple[str, ...] = ()
    rule_confidence_policy: str = "block"  # "null" only with an explicit contract
    fall_owner: str = "backend"
    device_ids: dict[str, str] = field(default_factory=lambda: {
        "stove": "induction-01", "light": "light-01", "water_purifier": "water-01",
    })
    # (internal scenario, internal action) -> (backend scenario, device, action, room).
    # Empty until the full backend contract supplies approved names.
    action_routes: dict[tuple[str, str], tuple[str, str, str, str]] = field(default_factory=dict)

    def __post_init__(self):
        if self.mode not in {"mock", "live"}:
            raise ValueError("mode must be mock or live")
        if self.mode == "live":
            url = urlsplit(self.base_url)
            if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
                raise ValueError("live mode requires an explicit HTTP(S) backend URL without credentials")
            if url.query or url.fragment or url.path.rstrip("/"):
                raise ValueError("base_url must be an origin; API paths are fixed")
        for name in ("poll_interval", "http_timeout", "retry_interval", "command_ttl", "device_max_age"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("allowed_lateness", "behavior_max_skew"):
            if not isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.rule_confidence_policy not in {"block", "null"}:
            raise ValueError("rule confidence must be blocked or explicitly nullable")
        if self.fall_owner != "backend":
            raise ValueError("integrated runtime supports backend-managed fall response only")
        if any(type(k) is not int or isinstance(v, bool) or not isfinite(v) or v < 0
               for k, v in self.level_to_watts.items()):
            raise ValueError("level_to_watts requires a validated nonnegative numeric table")

    @property
    def outbox_path(self) -> Path:
        return Path(self.data_dir) / self.mode / "outbox.sqlite3"

    def internal_room(self, room: str) -> str:
        mapping = {"kitchen": "kitchen", "toilet": "bathroom"}
        if self.room_is_bedroom:
            mapping["room"] = "bedroom"
        if room not in mapping:
            raise ValueError(f"unmapped_room:{room}")
        return mapping[room]

    def backend_room(self, room: str) -> str:
        mapping = {"kitchen": "kitchen", "bathroom": "toilet"}
        if self.room_is_bedroom:
            mapping["bedroom"] = "room"
        if room not in mapping:
            raise ValueError(f"unmapped_room:{room}")
        return mapping[room]
