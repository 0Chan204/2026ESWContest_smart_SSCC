from __future__ import annotations

from abc import ABC, abstractmethod
from src.control.models import ControlDecision, DeviceState, SensingState


class DecisionEngine(ABC):
    @abstractmethod
    def predict(self, sensing: SensingState, device: DeviceState) -> ControlDecision:
        raise NotImplementedError
