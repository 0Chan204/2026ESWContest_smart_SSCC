from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool = False
    topic: str = "home/voice/request"
    queue_size: int = 16
    llm_timeout: float = 5.0
    send_margin: float = 2.0
    http_timeout: float = 1.5
    recovery_interval: float = 5.0
    status_interval: float = 2.0
    min_stt_confidence: float = .6
    min_intent_confidence: float = .8
    history_seconds: float = 1800.0
    # STT has no identity. Explicit single-resident deployment, not speaker authentication.
    user_id: str = "default"

    def __post_init__(self):
        if type(self.enabled) is not bool or not isinstance(self.topic, str) or not self.topic or any(c in self.topic for c in "#+"):
            raise ValueError("invalid voice enable/topic setting")
        if not isinstance(self.user_id, str) or not self.user_id.strip() or type(self.queue_size) is not int or not 1 <= self.queue_size <= 100:
            raise ValueError("invalid voice user/queue setting")
        for key in ("llm_timeout", "send_margin", "http_timeout", "recovery_interval", "status_interval", "history_seconds"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError("invalid voice duration setting")
        if self.send_margin <= self.http_timeout:
            raise ValueError("voice send_margin must exceed http_timeout")
        for value in (self.min_stt_confidence, self.min_intent_confidence):
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 1:
                raise ValueError("invalid voice confidence setting")
