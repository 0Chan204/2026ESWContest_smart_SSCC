"""Polling host. Attach a confirmed sensing adapter via IntegrationRuntime.ingest_location."""
import argparse
import os
from pathlib import Path
import time

from .backend_client import BackendClient
from .config import IntegrationConfig
from .mock_backend import MockBackend
from .runtime import IntegrationRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--base-url", default=os.environ.get("HOMEVIS_BACKEND_URL", ""))
    parser.add_argument("--data-dir", type=Path, default=Path("output/integration"))
    parser.add_argument("--duration", type=float, default=10,
                        help="seconds to poll; no sensing transport is invented by this host")
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("duration must be positive")
    config = IntegrationConfig(mode=args.mode, base_url=args.base_url, data_dir=args.data_dir)
    client = BackendClient(config, MockBackend(time.time) if args.mode == "mock" else None)
    runtime = IntegrationRuntime(config, client)
    end = time.monotonic() + args.duration
    try:
        while time.monotonic() < end:
            runtime.run_once()
            time.sleep(0.1)
        print(f"mode={args.mode}; state={runtime.last_decision.state.value}; sensing adapter not attached")
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
