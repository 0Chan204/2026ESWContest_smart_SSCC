"""Backend client boundary; no server, MQTT or Wi-Fi classifier is implemented here."""

from .config import IntegrationConfig
from .runtime import IntegrationRuntime

__all__ = ["IntegrationConfig", "IntegrationRuntime"]
