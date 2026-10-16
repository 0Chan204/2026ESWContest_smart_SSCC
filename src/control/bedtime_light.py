from src.control.realtime_config import RealtimeConfig
from src.control.realtime_models import SensingUpdate
from src.control.scenario_config import ScenarioConfig
from src.control.scenario_models import BedtimeLightState as State, ScenarioAction


class BedtimeLightScenario:
    """Request bedroom lights off once after a continuously observed lying period."""

    def __init__(self, config: ScenarioConfig, sensing_config: RealtimeConfig) -> None:
        self.config = config
        self.sensing_config = sensing_config
        self.state = State.AWAKE
        self._lying_since: float | None = None
        self._last: float | None = None
        self._requested = False
        self._valid_until = None
        self._request: ScenarioAction | None = None

    def _reset(self) -> None:
        self.state = State.AWAKE
        self._lying_since = None
        self._requested = False
        self._request = None

    def matches_current_request(self, source: dict) -> bool:
        """Read-only identity/episode check; the caller must also validate current observations.

        A reset invalidates the old request even if another lying period later qualifies.
        Do not tick here: a sender can be ahead of the event-time evaluation cursor.
        """
        return bool(self._requested and self._lying_since is not None and self._request is not None
                    and all(source.get(key) == value for key, value in self._request.to_dict().items()))

    def tick(self, timestamp: float) -> ScenarioAction | None:
        if self._valid_until is not None and timestamp >= self._valid_until:
            self._reset()
            return None
        if self._last is None or timestamp - self._last >= self.sensing_config.UNKNOWN_TIMEOUT:
            self._reset()
            return None
        return self._maybe_request(timestamp)

    def update(self, sample: SensingUpdate) -> ScenarioAction | None:
        observed_at = sample.activity_timestamp if sample.activity_timestamp is not None else sample.timestamp
        if self._valid_until is not None and observed_at > self._valid_until:
            self._reset()
        if (self._last is not None
                and sample.timestamp - self._last >= self.sensing_config.UNKNOWN_TIMEOUT):
            self._reset()
        self._last = sample.timestamp
        self._valid_until = sample.activity_valid_until
        reliable = (
            sample.observation_valid is not False
            and sample.activity_observed is not False
            and (sample.activity_valid_until is None or sample.timestamp < sample.activity_valid_until)
            and (sample.activity_confidence is None
                 or sample.activity_confidence >= self.sensing_config.MIN_CONFIDENCE)
            and sample.detected
            and sample.confidence >= self.sensing_config.MIN_CONFIDENCE
            and sample.location == "bedroom"
            and sample.activity == "lying"
        )
        if not reliable:
            self._reset()
            self._last = sample.timestamp
            return None
        if self._lying_since is None:
            self._lying_since = observed_at
        self.state = State.LYING
        return self._maybe_request(observed_at)

    def _maybe_request(self, timestamp: float) -> ScenarioAction | None:
        if self._lying_since is None or self._requested:
            return None
        if timestamp - self._lying_since < self.config.BEDTIME_LYING_SECONDS:
            return None
        self.state = State.BEDTIME_CONFIRMED
        self._requested = True
        self.state = State.LIGHT_OFF_REQUESTED
        self._request = ScenarioAction(
            timestamp=timestamp,
            scenario="bedtime_light_off",
            event="bedtime_detected",
            action="turn_off",
            target="bedroom_light",
            reason="Bedroom lying duration reached the configured bedtime threshold",
            details={"lying_seconds": timestamp - self._lying_since},
        )
        return self._request
