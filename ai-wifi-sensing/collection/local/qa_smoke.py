"""GUI verification with four real PTYs emitting explicitly simulated CSI."""
import csv
import io
import math
import os
from pathlib import Path
import pty
import threading
import time
import tkinter as tk

from PIL import ImageGrab

from .app import LocalDesktop
from .collector import BASE, LocalCoordinator


def main():
    output = BASE / "data" / "qa"
    output.mkdir(parents=True, exist_ok=True)
    stopped = threading.Event()
    channels, threads, errors = [], [], []
    coordinator = None

    def feed(master, index, interval):
        os.set_blocking(master, False)
        while not stopped.is_set():
            now = time.monotonic()
            iq = []
            for k in range(64):
                iq.extend([5 + k % 4, int(30 + 12 * math.sin(k * .25 + now * (1.2 + index * .2)))])
            stream = io.StringIO()
            csv.writer(stream, lineterminator="\n").writerow(
                [int(now * 1e6) % 2**32, str(iq), -45 - index, "aa:bb:cc:dd:ee:ff", 0, 128])
            try:
                os.write(master, stream.getvalue().encode())
            except BlockingIOError:
                pass
            stopped.wait(interval)

    try:
        for i, interval in enumerate((.014, .02, .028, .04)):
            master, slave = pty.openpty()
            channels.append((master, slave))
            thread = threading.Thread(target=feed, args=(master, i, interval))
            thread.start()
            threads.append(thread)
        devices = [{"id": f"esp-{i:02d}", "port": os.ttyname(slave), "simulated": True}
                   for i, (_master, slave) in enumerate(channels, 1)]
        coordinator = LocalCoordinator(output / "sessions", devices=devices, bindings=output / "bindings.json")
        root = tk.Tk()
        app = LocalDesktop(root, coordinator)
        deadline = time.monotonic() + 65
        observed = set()
        started = completed = countdown_saved = False

        def screenshot(name):
            root.update_idletasks()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(output / name)

        def check():
            nonlocal started, completed, countdown_saved
            try:
                if not started and len(app.online_ids()) == 4:
                    assert len(app.tree.selection()) == 4
                    assert app.server is None and app.local_mode
                    assert app.wait.get() == 5 and app.samples.get() == 500
                    assert app.action.get() == "none"
                    for name in ("fall", "get_up", "none", "lie_down"):
                        app.action_buttons[name].invoke()
                        assert app.action.get() == name
                    app.start_button.invoke()
                    assert app.current_job.startswith("lie_down_")
                    assert all(button.instate(["disabled"]) for button in app.action_buttons.values())
                    app.action_buttons["fall"].invoke()
                    assert app.action.get() == "lie_down"
                    started = True
                if app.capture_phase.get() == "수집 시작까지":
                    observed.add("waiting")
                    if app.countdown.get() == "4" and not countdown_saved:
                        screenshot("local_countdown.png")
                        countdown_saved = True
                if app.capture_phase.get() == "길이 기준 수집 중":
                    observed.add("collecting")
                    if app.countdown.get() in ("1/4", "2/4", "3/4") and "independent" not in observed:
                        screenshot("local_packet_progress.png")
                        observed.add("independent")
                if app.result is not None and len(app.result["series"]) == 4:
                    assert {"waiting", "collecting", "independent"} <= observed
                    assert app.result["job"]["status"] == "completed"
                    assert app.result["job"]["action"] == "lie_down"
                    assert all(not button.instate(["disabled"]) for button in app.action_buttons.values())
                    assert all(value["accepted_rows"] == 550 and value["retained_rows"] == 500
                               for value in app.result["job"]["uploads"].values())
                    assert len(app.figure.axes) == 4
                    assert all(len(series["sample"]) == 500 for series in app.result["series"].values())
                    app.view.set("통합 비교")
                    app.redraw()
                    assert len(app.figure.axes) == 1 and len(app.figure.axes[0].lines) == 4
                    app.view.set("장치별 보기")
                    app.redraw()
                    root.geometry("1160x800")
                    root.update_idletasks()
                    app.controls_canvas.yview_moveto(1)
                    root.update_idletasks()
                    assert app.controls_canvas.yview()[1] > .999
                    for widget in app.start_button.master.winfo_children()[-2:]:
                        assert widget.winfo_rooty() + widget.winfo_height() <= (
                            app.controls_canvas.winfo_rooty() + app.controls_canvas.winfo_height())
                    root.geometry("1360x900")
                    app.controls_canvas.yview_moveto(0)
                    root.update()
                    screenshot("local_desktop.png")
                    app.figure.savefig(output / "local_graph.png", dpi=140)
                    print("Local GUI verified: four action buttons; action_timestamp folder; four USB PTYs; 5s countdown; independent 550->500 packets; separate/combined graphs.")
                    print(output / "local_desktop.png")
                    completed = True
                    app.close()
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError("Local GUI capture timed out")
            except Exception as exc:
                errors.append(exc)
                app.close()
                return
            root.after(100, check)

        root.after(350, check)
        root.mainloop()
        if errors:
            raise errors[0]
        if not completed:
            raise RuntimeError("Local GUI closed before verification completed")
    finally:
        if coordinator:
            coordinator.shutdown()
        stopped.set()
        for thread in threads:
            thread.join(timeout=3)
        for master, slave in channels:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    main()
