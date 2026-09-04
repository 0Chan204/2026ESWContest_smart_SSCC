from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import math
import struct
import wave


class TTSEngine(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> Path:
        raise NotImplementedError


class Pyttsx3TTS(TTSEngine):
    """Offline TTS using voices installed in the host operating system."""

    name = "pyttsx3"

    def synthesize(self, text: str, output_path: Path) -> Path:
        if not text.strip():
            raise ValueError("TTS text must not be empty")

        import pyttsx3

        output_path.parent.mkdir(parents=True, exist_ok=True)

        engine = pyttsx3.init()
        try:
            engine.save_to_file(text, str(output_path))
            engine.runAndWait()
        finally:
            engine.stop()

        if not output_path.exists():
            raise RuntimeError(f"TTS output was not created: {output_path}")

        return output_path


class DryRunTTS(TTSEngine):
    """Dependency-free test WAV creator; not actual spoken TTS."""

    name = "dry-run"

    def synthesize(self, text: str, output_path: Path) -> Path:
        if not text.strip():
            raise ValueError("TTS text must not be empty")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 16000
        duration_sec = 0.25
        frequency = 440.0
        amplitude = 2500
        frames = int(sample_rate * duration_sec)

        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)

            for i in range(frames):
                value = int(
                    amplitude
                    * math.sin(2.0 * math.pi * frequency * i / sample_rate)
                )
                wav.writeframesraw(struct.pack("<h", value))

        return output_path
