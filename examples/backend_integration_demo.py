"""Deterministic mock exercise, no GPU, TTS, Wi-Fi transport or real appliance access."""
import argparse
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.control import CentralController, ScenarioConfig
from src.integration import IntegrationConfig, IntegrationRuntime
from src.integration.backend_client import BackendClient
from src.integration.mock_backend import MockBackend, ready_sample_devices
from src.integration.schemas import iso_time
from src.integration.sensing import BehaviorObservation
from src.llm.factory import create_llm


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def run_demo(data_dir: Path, *, with_mock_behavior=False, start_at=None):
    zone = timezone(timedelta(hours=9))
    today = datetime.now(zone).date()
    clock = FakeClock(datetime.combine(today, time(7), zone).timestamp() if start_at is None else start_at)
    start = clock.now
    # Only the independent readiness signal is synthetic. Rule confidence uses the agreed null contract.
    config = IntegrationConfig(data_dir=data_dir,
                               allowed_lateness=0, water_ready_field="mock_readiness",
                               water_ready_states=("ready",))
    backend = MockBackend(clock)
    client = BackendClient(config, backend)
    controller = CentralController(confidence_data_dir=config.outbox_path.parent / "controller",
                                   scenario_config=ScenarioConfig())
    runtime = IntegrationRuntime(config, client, controller=controller, clock=clock)
    assert create_llm("none") is None
    try:
        for offset, room, activity in ((0, "room", "lying"), (1, "room", "standing"),
                                       (6, "room", "standing"), (7, "kitchen", "walking"),
                                       (12, "kitchen", "walking")):
            clock.now = start + offset
            backend.snapshot = ready_sample_devices(clock.now)
            runtime.ingest_device_states({"items": client.fetch_device_states()}, fetched_at=clock.now)
            behavior = None
            if with_mock_behavior:
                behavior = BehaviorObservation(clock.now, clock.now + 10,
                    room, confidence=0.95, activity=activity)
            runtime.ingest_location({"time": iso_time(clock.now), "location": room,
                                     "location_confidence": 0.95}, behavior=behavior)
            runtime.advance()
            runtime.dispatch_mock_once()
        rows = runtime.outbox.rows()
        return {
            "mode": "mock", "fake_clock_start": iso_time(start),
            "separate_synthetic_behavior": with_mock_behavior,
            "rule_confidence_policy": config.rule_confidence_policy,
            "synthetic_device_readiness": True,
            "device_queries": sum(method == "GET" for method, _, _ in backend.requests),
            "posts": sum(method == "POST" for method, _, _ in backend.requests),
            "missing_inputs": runtime.missing_inputs,
            "decisions": [{"status": r["status"], "diagnostic": r["diagnostic"],
                           "payload": r["payload"], "response": r["response"]} for r in rows],
        }
    finally:
        runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-mock-behavior", action="store_true",
                        help="explicit synthetic behavior + mock-only nullable confidence contract")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.data_dir is not None:
        result = run_demo(args.data_dir, with_mock_behavior=args.with_mock_behavior)
    else:
        with TemporaryDirectory(prefix="homevis-mock-") as directory:
            result = run_demo(Path(directory), with_mock_behavior=args.with_mock_behavior)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
