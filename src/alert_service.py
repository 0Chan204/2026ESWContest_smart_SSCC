from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from src.llm.message_generator import LLMMessageGenerator
from src.models import AlertOutput, RiskDecision, RiskLevel
from src.voice.tts import TTSEngine


@dataclass(frozen=True)
class AlertPolicy:
    warning_sound: bool
    voice: bool


ALERT_POLICY: dict[RiskLevel, AlertPolicy] = {
    RiskLevel.NORMAL: AlertPolicy(warning_sound=False, voice=False),
    RiskLevel.WARNING: AlertPolicy(warning_sound=False, voice=True),
    RiskLevel.HIGH: AlertPolicy(warning_sound=True, voice=True),
}


class AlertService:
    """Convert an already-decided risk result into message/TTS output."""

    def __init__(
        self,
        message_generator: LLMMessageGenerator,
        tts: TTSEngine,
        output_dir: str | Path = "output",
    ) -> None:
        self.message_generator = message_generator
        self.tts = tts
        self.output_dir = Path(output_dir)

    def handle(self, decision: RiskDecision) -> AlertOutput:
        policy = ALERT_POLICY[decision.risk_level]

        if not policy.voice:
            return AlertOutput(
                risk_level=decision.risk_level,
                warning_sound=policy.warning_sound,
                voice=False,
                message=None,
                tts_file=None,
                llm_name=self.message_generator.llm_name,
                prompt_version=self.message_generator.prompt_version,
                fallback_used=False,
            )

        generation = self.message_generator.generate(decision)

        tts_file: str | None = None
        tts_error: str | None = None

        filename = (
            f"alert_{decision.risk_level.value.lower()}_"
            f"{uuid4().hex[:8]}.wav"
        )
        target_path = self.output_dir / filename

        try:
            audio_path = self.tts.synthesize(generation.message, target_path)
            tts_file = audio_path.as_posix()
        except Exception as exc:
            tts_error = f"{type(exc).__name__}: {exc}"

        return AlertOutput(
            risk_level=decision.risk_level,
            warning_sound=policy.warning_sound,
            voice=True,
            message=generation.message,
            tts_file=tts_file,
            llm_name=generation.llm_name,
            prompt_version=generation.prompt_version,
            fallback_used=generation.fallback_used,
            llm_error=generation.error,
            tts_error=tts_error,
        )
