from __future__ import annotations

from src.control.decision.base import DecisionEngine
from src.control.models import ControlDecision, ControlRisk, DeviceState, SensingState, Situation, UserLocation
from src.control.policy import UNKNOWN_LOCATION_RISK


class RuleBasedDecisionEngine(DecisionEngine):
    def predict(self, sensing: SensingState, device: DeviceState) -> ControlDecision:
        situation, risk = self._classify(sensing, device)
        return ControlDecision(
            situation=situation, risk=risk, location=sensing.location,
            activity=sensing.activity, stove_on=device.stove_on,
            heat_level=device.heat_level, away_duration=sensing.away_duration,
        )

    def _classify(self, sensing: SensingState, device: DeviceState) -> tuple[Situation, ControlRisk]:
        if not device.stove_on:
            return Situation.STOVE_OFF, ControlRisk.SAFE
        rules = {
            UserLocation.STOVE_AREA: (Situation.COOKING, ControlRisk.SAFE),
            UserLocation.KITCHEN: (Situation.TEMP_AWAY, ControlRisk.LOW),
            UserLocation.OTHER_ROOM: (Situation.IN_HOME_AWAY, ControlRisk.LOW),
            UserLocation.OUTSIDE_HOME: (Situation.HOME_EXIT_WITH_STOVE_ON, ControlRisk.HIGH),
            UserLocation.UNKNOWN: (Situation.LOCATION_UNKNOWN, ControlRisk(UNKNOWN_LOCATION_RISK)),
        }
        return rules[sensing.location]
