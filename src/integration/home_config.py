"""Fixed safety policies, deliberately separate from learned confidence weights."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class HomeAutomationConfig:
    air_purifier_enabled: bool = False
    cooking_air_clean_enabled: bool = False
    air_purifier_off_on_good_or_normal: bool = True
    air_purifier_clean_hold_seconds: float = 30.0
    away_all_off_enabled: bool = False
    away_min_confidence: float = .8
    # Deployment assertion, NOT a new sensor field. Remains false until the
    # producer confirms backend room=null/present=false or Wi-Fi location=empty
    # covers the entire home for the deployed input source.
    whole_home_presence_verified: bool = False

    def __post_init__(self):
        for key, value in vars(self).items():
            if key.endswith("seconds") or key == "away_min_confidence":
                if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                    raise ValueError(f"{key} must be finite and positive")
            elif type(value) is not bool:
                raise ValueError(f"{key} must be boolean")
        if self.away_min_confidence > 1:
            raise ValueError("away_min_confidence must be <= 1")
