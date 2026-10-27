from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

from src.control.identifiers import ROOMS, canonical_room
from src.control.scenario_config import ScenarioConfig
from src.control.realtime_config import RealtimeConfig
from src.llm.config import LLMConfig
from .home_config import HomeAutomationConfig


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
    # Deprecated constructor option, retained for callers. room is always the sleep/wake room.
    room_is_bedroom: bool | None = None
    # These settings require confirmation by the deployment contract.
    temperature_is_celsius: bool = False
    # Live deployment assertion: backend must suppress invalid/stale sensor
    # temperatures, not just refresh the device heartbeat. Mock data is synthetic.
    stove_temperature_validity_verified: bool = False
    level_to_watts: dict[int, float] = field(default_factory=dict)
    watts_field: str | None = None
    water_ready_states: tuple[str, ...] = ()
    # Legacy direct-call policy. The continuous v0.5 profile uses measured evidence.
    rule_confidence_policy: str = "null"  # "block" remains an explicit deployment opt-out.
    fall_owner: str = "backend"  # Follow-up response owner, NOT the fall/recovery decision maker.
    device_ids: dict[str, str] = field(default_factory=lambda: {
        "stove": "induction-01", "light": "light-01", "water_purifier": "water-01",
    })
    # (internal scenario, internal action) -> (backend scenario, device, action, room).
    # Empty until the full backend contract supplies approved names.
    action_routes: dict[tuple[str, str], tuple[str, str, str, str]] = field(default_factory=dict)
    # Legacy explicit readiness field; v0.5 has a separate backend_idle mode.
    water_ready_field: str | None = None
    # The long-running host opts into the supplied backend workflow. Direct
    # callers retain their existing explicit-contract configuration.
    water_readiness_mode: str = "explicit"
    backend_fall_scenario: str | None = None
    fall_actions: tuple[dict, ...] = (
        {"device": "stove", "action": "turn_off"},
        {"device": "light", "action": "blink", "durationSeconds": 10},
    )
    backend_restore: bool = False
    async_alerts: bool = False
    evaluation_audit_interval: float = 0.0
    backend_v05: bool = False
    stove_reduce_steps: int = 1
    fall_status_path: str | None = None
    automation_profile: str = "legacy"
    automation_absence_seconds: float = 40.0
    automation_return_seconds: float = 5.0
    light_on_seconds: float = 5.0
    light_off_seconds: float = 30.0
    multi_room_lights: bool = False
    mock_behavior_contract: bool = False
    scenario_config: ScenarioConfig = field(default_factory=ScenarioConfig)
    home_automation: HomeAutomationConfig = field(default_factory=HomeAutomationConfig)
    realtime_config: RealtimeConfig = field(default_factory=RealtimeConfig)
    confidence_options: dict | None = None
    llm_config: LLMConfig = field(default_factory=LLMConfig)

    def __post_init__(self):
        if self.mode not in {"mock", "live"}:
            raise ValueError("mode must be mock or live")
        if type(self.mock_behavior_contract) is not bool or (self.mock_behavior_contract and self.mode != "mock"):
            raise ValueError("mock_behavior_contract is allowed only in mock mode")
        if not isinstance(self.scenario_config, ScenarioConfig):
            raise ValueError("scenario_config must be ScenarioConfig")
        if not isinstance(self.home_automation, HomeAutomationConfig):
            raise ValueError("home_automation must be HomeAutomationConfig")
        if not isinstance(self.realtime_config, RealtimeConfig):
            raise ValueError("realtime_config must be RealtimeConfig")
        if not isinstance(self.llm_config, LLMConfig):
            raise ValueError("llm_config must be LLMConfig")
        if self.mode == "live":
            url = urlsplit(self.base_url)
            if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
                raise ValueError("live mode requires an explicit HTTP(S) backend URL without credentials")
            if url.query or url.fragment or url.path.rstrip("/"):
                raise ValueError("base_url must be an origin; API paths are fixed")
        for name in ("poll_interval", "http_timeout", "retry_interval", "command_ttl", "device_max_age",
                     "automation_absence_seconds", "automation_return_seconds", "light_on_seconds", "light_off_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("allowed_lateness", "behavior_max_skew", "evaluation_audit_interval"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.rule_confidence_policy not in {"block", "null", "observed"}:
            raise ValueError("rule confidence policy must be block, null or observed")
        if self.automation_profile not in {"legacy", "location_level_v1"}:
            raise ValueError("unsupported automation profile")
        if type(self.multi_room_lights) is not bool:
            raise ValueError("multi_room_lights must be boolean")
        if type(self.stove_temperature_validity_verified) is not bool:
            raise ValueError("stove_temperature_validity_verified must be boolean")
        if type(self.stove_reduce_steps) is not int or not 1 <= self.stove_reduce_steps <= 8:
            raise ValueError("stove_reduce_steps must be 1..8")
        if self.water_readiness_mode not in {"explicit", "backend_idle"}:
            raise ValueError("invalid water_readiness_mode")
        if self.backend_fall_scenario is not None and not self.backend_fall_scenario.strip():
            raise ValueError("backend_fall_scenario must not be empty")
        if self.fall_status_path is not None and (
                not self.fall_status_path.startswith("/") or self.fall_status_path.startswith("//")
                or "{incident_id}" not in self.fall_status_path
                or "?" in self.fall_status_path or "#" in self.fall_status_path):
            raise ValueError("fall_status_path requires a relative API path with {incident_id}")
        if self.water_ready_field is not None and (
                not isinstance(self.water_ready_field, str) or not self.water_ready_field
                or self.water_ready_field == "status"):
            raise ValueError("water readiness needs a separate field; status is not readiness")
        if self.fall_owner != "backend":
            raise ValueError("integrated runtime supports backend-managed fall response only")
        if any(type(k) is not int or isinstance(v, bool) or not isfinite(v) or v < 0
               for k, v in self.level_to_watts.items()):
            raise ValueError("level_to_watts requires a validated nonnegative numeric table")
        self.make_confidence_config()  # Validate policy even for --check-config.

    def make_confidence_config(self):
        from .decision_policy import build_confidence_config
        return build_confidence_config(self)

    @property
    def outbox_path(self) -> Path:
        return Path(self.data_dir) / self.mode / "outbox.sqlite3"

    @property
    def stove_temperature_trusted(self) -> bool:
        return self.mode == "mock" or self.stove_temperature_validity_verified

    def internal_room(self, room: str) -> str:
        normalized = canonical_room(room)
        if normalized not in ROOMS:
            raise ValueError(f"unmapped_room:{room}")
        return normalized

    def backend_room(self, room: str) -> str:
        return self.internal_room(room)

    def device_stream(self, device: str, device_id: str) -> str:
        if device == "light" and self.multi_room_lights and device_id != self.device_ids.get("light"):
            return "light:" + device_id
        return device

    def accepts_device(self, device: str, device_id: str) -> bool:
        if device == "air_purifier" and self.home_automation.air_purifier_enabled:
            return device_id == self.device_ids.get(device, "air-01")
        return self.device_ids.get(device) == device_id or (self.multi_room_lights and device == "light")
