"""Hardware-free end-to-end demo with two real C agent processes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from .processing import draw_plot, export_processed, process_session
from .server import ACTIVE, Coordinator, make_server

BASE = Path(__file__).resolve().parents[1]


def run_demo(output, wait=5, duration=None, sample_count=500):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    coordinator = Coordinator(output / "sessions")
    server = make_server(coordinator, "127.0.0.1", 0, "local-demo-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    processes, logs = [], []
    try:
        for i in (1, 2):
            config = {"server": f"http://127.0.0.1:{server.server_port}", "token": server.token,
                      "pi_id": f"pi-{i:02d}", "spool_dir": str(output / f"spool-pi-{i:02d}"),
                      "devices": [{"id": f"esp-{j:02d}", "port": f"sim-{j}"} for j in (1, 2)]}
            path = output / f"pi-{i:02d}.json"
            path.write_text(json.dumps(config))
            log = (output / f"pi-{i:02d}.log").open("w")
            logs.append(log)
            processes.append(subprocess.Popen([str(BASE / "pi_agent/csi-agent"), str(path), "--simulate"],
                                              stderr=log, env=dict(os.environ, CSI_TOKEN=server.token)))
        deadline = time.monotonic() + 10
        while len(coordinator.snapshot()["agents"]) < 2:
            if time.monotonic() > deadline:
                raise RuntimeError("C agents did not connect; inspect demo logs")
            time.sleep(.1)
        job = coordinator.create_job([(f"pi-{i:02d}", f"esp-{j:02d}") for i in (1, 2) for j in (1, 2)], wait, duration, sample_count=sample_count)
        deadline = time.monotonic() + wait + (duration if duration is not None else (sample_count + 50) / 25) + 25
        while True:
            current = coordinator.snapshot()["jobs"][job["id"]]
            if current["status"] not in ACTIVE:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Demo timed out")
            time.sleep(.1)
        if current["status"] != "completed":
            raise RuntimeError(f"Unexpected demo state: {current}")
        folder = coordinator.root / job["id"]
        result = process_session(folder)
        export_processed(folder, result)
        figure = Figure(figsize=(11, 5), dpi=140)
        FigureCanvasAgg(figure)
        draw_plot(figure, result)
        figure.savefig(output / "demo_result.png")
        print(f"Completed: 2 C agents, 4 ESP32 (SIMULATED), {wait}s wait; "
              + (f"{sample_count + 50} captured -> {sample_count} retained per board" if duration is None else f"{duration}s legacy capture"))
        print(f"Session: {folder}\nGraph: {output / 'demo_result.png'}")
        return result
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/demo")
    parser.add_argument("--wait", type=float, default=5)
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--duration", type=float, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    run_demo(args.output, args.wait, args.duration, args.samples)
