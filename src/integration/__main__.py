"""Run continuous Wi-Fi result ingestion, central detection and backend control."""
import argparse
import json
from math import isfinite
import os
from pathlib import Path
import signal
from threading import Event
import time

from .backend_client import BackendClient
from .host import ContinuousHost, InstanceLock
from .mqtt_source import MQTTSource
from .runtime import IntegrationRuntime
from .settings import DEFAULT_CONFIG, load_settings
from .simulation import SimulationBackend, SimulationSource


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--mode", choices=("mock", "live"))
    parser.add_argument("--base-url")
    parser.add_argument("--sensing-source", choices=("mqtt", "backend"))
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--duration", type=float, help="optional run limit in seconds; default: until Ctrl+C/SIGTERM")
    parser.add_argument("--mock-scenario", choices=("presence", "fall"), default="presence")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--healthcheck", action="store_true", help="check runner heartbeat (not hardware readiness)")
    args = parser.parse_args(argv)
    if args.duration is not None and (not isfinite(args.duration) or args.duration <= 0):
        parser.error("duration must be positive")
    try:
        if args.env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(args.env_file, override=False)
        settings = load_settings(args.config, mode=args.mode, base_url=args.base_url, data_dir=args.data_dir)
        if args.sensing_source:
            from dataclasses import replace
            settings = replace(settings, sensing_source=args.sensing_source)
    except (ValueError, TypeError, KeyError, OSError, ImportError) as exc:
        parser.error(f"configuration error ({type(exc).__name__}); check TOML/.env and requirements-runtime.txt")
    config = settings.integration
    if args.check_config:
        print(f"configuration valid; mode={config.mode}; source={settings.sensing_source}; contract=backend-v0.5")
        return 0
    if args.healthcheck:
        try:
            status = json.loads((config.outbox_path.parent / "status.json").read_text(encoding="utf-8"))
            return 0 if status["running"] and 0 <= time.time() - status["updated_at"] < max(15, settings.status_interval * 3) else 1
        except (OSError, ValueError, KeyError, TypeError):
            return 1
    stop = Event()
    handlers = {}
    for name in (signal.SIGINT, signal.SIGTERM):
        handlers[name] = signal.signal(name, lambda *_: stop.set())
    try:
        with InstanceLock(config.outbox_path.parent):
            backend = SimulationBackend(fall_scenario=config.backend_fall_scenario) if config.mode == "mock" else None
            client = BackendClient(config, backend)
            if backend is not None:
                source = SimulationSource(settings.mqtt, scenario=args.mock_scenario)
            elif settings.sensing_source == "backend":
                from .backend_sensing import BackendSensingSource
                source = BackendSensingSource(settings, client)
            else:
                source = MQTTSource(settings.mqtt)
            alert_service = None
            if config.mode == "mock":
                from src.alert_service import AlertService
                from src.llm.message_generator import LLMMessageGenerator
                from src.voice.tts import DryRunTTS
                alert_service = AlertService(LLMMessageGenerator(), DryRunTTS(), config.outbox_path.parent / "fall_alerts")
            runtime = IntegrationRuntime(config, client, fall_alert_service=alert_service)
            print(f"HomeVIS {config.mode}: continuous runner started; stop with Ctrl+C; status={config.outbox_path.parent / 'status.json'}", flush=True)
            ContinuousHost(settings, runtime, source).run(stop, args.duration)
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"HomeVIS startup/runtime error: {type(exc).__name__}; check dependencies, data directory permissions and instance lock", flush=True)
        return 1
    finally:
        for name, handler in handlers.items():
            signal.signal(name, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
