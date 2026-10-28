"""Optional desktop smoke check (requires a display); uses only simulated devices."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import tkinter as tk

from PIL import ImageGrab

from csi_capture.desktop import Desktop
from csi_capture.server import Coordinator, make_server

BASE = Path(__file__).resolve().parents[1]


def main():
    output = BASE / "data/ui-smoke"
    output.mkdir(parents=True, exist_ok=True)
    coordinator = Coordinator(output / "sessions")
    server = make_server(coordinator, "127.0.0.1", 0, "ui-demo-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = tk.Tk()
    app = Desktop(root, coordinator, server)
    processes, logs = [], []
    error = []
    started = False
    completed = False
    observed = set()
    deadline = time.monotonic() + 65
    try:
        for i in (1, 2):
            path = output / f"pi-{i:02d}.json"
            path.write_text(json.dumps({"server": f"http://127.0.0.1:{server.server_port}", "token": server.token,
                                       "pi_id": f"pi-{i:02d}", "spool_dir": str(output / f"spool-{i}"),
                                       "devices": [{"id": f"esp-{j:02d}", "port": f"sim{j}"} for j in (1, 2)]}))
            log = (output / f"pi-{i:02d}.log").open("w")
            logs.append(log)
            processes.append(subprocess.Popen([str(BASE / "pi_agent/csi-agent"), str(path), "--simulate"],
                                              stderr=log, env=dict(os.environ, CSI_TOKEN=server.token)))

        def check():
            nonlocal started, completed
            try:
                if not started and len(app.online_ids()) == 4:
                    app.count.set(4)
                    app.select_count()
                    app.start_button.invoke()
                    started = True
                if app.capture_phase.get() == "수집 시작까지":
                    observed.add("waiting")
                    if app.countdown.get() in ("3", "4") and not (output / "countdown.png").exists():
                        root.update_idletasks()
                        x, y = root.winfo_rootx(), root.winfo_rooty()
                        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(output / "countdown.png")
                if app.capture_phase.get() == "길이 기준 수집 중":
                    observed.add("collecting")
                if app.result is not None and len(app.result["series"]) == 4:
                    assert observed == {"waiting", "collecting"}
                    assert app.view.get() == "장치별 보기" and len(app.figure.axes) == 4
                    assert app.samples.get() == 500
                    assert all(len(series["sample"]) == 500 for series in app.result["series"].values())
                    assert all(upload["accepted_rows"] == 550 and upload["retained_rows"] == 500
                               for upload in app.result["job"]["uploads"].values())
                    # Exercise native metric switching, carrier selection and legend toggles.
                    app.metric.set("서브캐리어 진폭")
                    app.carrier.set(26)
                    app.redraw()
                    app.view.set("통합 비교")
                    app.redraw()
                    assert len(app.figure.axes) == 1 and len(app.figure.axes[0].lines) == 4
                    app.view.set("장치별 보기")
                    app.redraw()
                    app.metric.set("변화량 RMS (기본)")
                    app.redraw()
                    artist = next(iter(app.legend_lines))
                    event = type("Pick", (), {"artist": artist})()
                    app.toggle_line(event)
                    assert not app.legend_lines[artist].get_visible()
                    app.toggle_line(event)
                    root.update_idletasks()
                    app.figure.savefig(output / "graph.png", dpi=140)
                    x, y = root.winfo_rootx(), root.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(output / "desktop.png")
                    print(f"UI smoke passed: four boards independently captured 550 -> retained 500; countdown, packet progress, separate/combined graphs.\n{output / 'desktop.png'}")
                    completed = True
                    app.close()
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError("UI smoke test timed out")
            except Exception as exc:
                error.append(exc)
                app.close()
                return
            root.after(200, check)
        root.after(300, check)
        root.mainloop()
        if error:
            raise error[0]
        if not completed:
            raise RuntimeError("UI closed before validation completed")
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=6)
        for log in logs:
            log.close()
        server.server_close()


if __name__ == "__main__":
    main()
