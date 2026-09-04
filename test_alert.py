"""Standalone test runner for the HomeVIS post-decision alert pipeline.

Examples:
    python test_alert.py --risk HIGH --llm none --tts dry-run
    python test_alert.py --risk WARNING --llm qwen --tts dry-run
"""

from __future__ import annotations

import argparse
import importlib.util

from src.alert_service import AlertService
from src.llm.factory import create_llm
from src.llm.message_generator import LLMMessageGenerator
from src.models import RiskDecision, RiskLevel
from src.output.output_writer import OutputWriter
from src.voice.tts import DryRunTTS, Pyttsx3TTS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test HomeVIS message/TTS after a risk decision"
    )
    parser.add_argument(
        "--risk",
        choices=[level.value for level in RiskLevel],
        default="NORMAL",
    )
    parser.add_argument("--situation", default=None)
    parser.add_argument("--user_state", default=None)
    parser.add_argument("--user_location", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--heat", dest="heat_level", default=None)
    parser.add_argument("--duration", type=int, default=None)

    parser.add_argument(
        "--llm",
        choices=("none","gemini", "qwen", "llama", "exaone"),
        default="none",
    )
    parser.add_argument("--prompt", default="v1")
    parser.add_argument(
        "--tts",
        choices=("auto", "pyttsx3", "dry-run"),
        default="auto",
    )
    parser.add_argument(
        "--output-json",
        default="output/alert_output.json",
    )
    return parser.parse_args()


def build_tts(name: str):
    if name == "dry-run":
        return DryRunTTS()
    if name == "pyttsx3":
        return Pyttsx3TTS()

    if importlib.util.find_spec("pyttsx3") is not None:
        return Pyttsx3TTS()
    return DryRunTTS()


def main() -> int:
    args = parse_args()

    decision = RiskDecision(
        risk_level=args.risk,
        situation=args.situation,
        user_state=args.user_state,
        user_location=args.user_location,
        device=args.device,
        heat_level=args.heat_level,
        duration=args.duration,
    )

    generator = LLMMessageGenerator(
        llm=create_llm(args.llm),
        prompt_version=args.prompt,
    )
    service = AlertService(
        message_generator=generator,
        tts=build_tts(args.tts),
    )

    result = service.handle(decision)
    json_path = OutputWriter().save_json(result, args.output_json)

    print("[DECISION INPUT]")
    print(f"Risk Level    : {decision.risk_level.value}")
    print(f"Situation     : {decision.situation}")
    print(f"User State    : {decision.user_state}")
    print(f"User Location : {decision.user_location}")
    print(f"Device        : {decision.device}")
    print(f"Heat Level    : {decision.heat_level}")
    print(f"Duration      : {decision.duration}")

    print("\n[GENERATION]")
    print(f"LLM            : {result.llm_name}")
    print(f"Prompt Version : {result.prompt_version}")
    print(f"Fallback Used  : {result.fallback_used}")
    if result.llm_error:
        print(f"LLM Error      : {result.llm_error}")

    print("\n[ALERT OUTPUT]")
    print(f"Risk Level     : {result.risk_level.value}")
    print(f"Warning Sound  : {result.warning_sound}")
    print(f"Voice          : {result.voice}")

    if result.message:
        print("\n[MESSAGE]")
        print(result.message)

    if result.tts_file:
        print("\n[TTS FILE]")
        print(result.tts_file)
    elif result.tts_error:
        print("\n[TTS ERROR]")
        print(result.tts_error)

    print("\n[OUTPUT JSON]")
    print(json_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
