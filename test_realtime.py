"""Replay timestamp-ordered JSON Lines or a built-in demo through existing LLM/TTS."""
import argparse
import json
from pathlib import Path

from src.control import CentralController, ApplianceUpdate, SensingUpdate
from src.alert_service import AlertService
from src.llm.message_generator import LLMMessageGenerator
from src.output.output_writer import OutputWriter
from src.voice.tts import DryRunTTS, Pyttsx3TTS


def demo():
    for t in range(0, 151, 5):
        yield {"type": "appliance", "timestamp": t, "power_on": True, "power_watts": 800, "temperature_c": 90}
        yield {"type": "sensing", "timestamp": t, "location": "kitchen" if t < 10 or t >= 140 else "living_room"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="UTF-8 JSONL event file; defaults to demo")
    parser.add_argument("--llm", default="none", choices=["none", "gemini", "qwen", "llama", "exaone"])
    parser.add_argument("--tts", default="dry-run", choices=["dry-run", "pyttsx3"])
    parser.add_argument("--output-dir", type=Path, default=Path("output/realtime"))
    args = parser.parse_args()
    controller = CentralController()
    llm = None
    if args.llm != "none":
        from src.llm.factory import create_llm
        llm = create_llm(args.llm)
    service = AlertService(LLMMessageGenerator(llm),
                           DryRunTTS() if args.tts == "dry-run" else Pyttsx3TTS(), args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    last_state = None
    source = args.input.open(encoding="utf-8-sig") if args.input else None
    try:
        events = (json.loads(line) for line in source if line.strip()) if source else demo()
        with (args.output_dir / "decisions.jsonl").open("w", encoding="utf-8") as log:
            for event in events:
                payload = dict(event)
                kind = payload.pop("type")
                if kind == "sensing":
                    result = controller.update_sensing(SensingUpdate(**payload))
                elif kind == "appliance":
                    result = controller.update_appliance(ApplianceUpdate(**payload))
                elif kind == "tick":
                    result = controller.tick(**payload)
                else:
                    raise ValueError(f"Unknown event type: {kind}")
                log.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
                if result.state != last_state:
                    print(f"{result.timestamp:g}s {result.state.value}: {result.reason}")
                    output = service.handle(result.to_risk_decision())
                    OutputWriter().save_json(output, args.output_dir / "alert_output.json")
                    last_state = result.state
    finally:
        if source:
            source.close()


if __name__ == "__main__":
    main()
