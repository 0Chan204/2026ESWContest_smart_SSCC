from __future__ import annotations

from src.models import RiskLevel

# Reserved for a future long-away rule; no arbitrary threshold is applied now.
LONG_AWAY_THRESHOLD: int | None = None
UNKNOWN_LOCATION_RISK = "LOW"

ALERT_RISK_MAPPING: dict[str, RiskLevel] = {
    "SAFE": RiskLevel.NORMAL,
    "LOW": RiskLevel.WARNING,
    "HIGH": RiskLevel.HIGH,
    "CRITICAL": RiskLevel.HIGH,
}


def map_control_risk(risk: object) -> RiskLevel:
    value = getattr(risk, "value", risk)
    try:
        return ALERT_RISK_MAPPING[str(value)]
    except KeyError as exc:
        raise ValueError(f"Unsupported control risk: {value}") from exc
