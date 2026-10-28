"""Laptop-only desktop frontend and optional terminal capture entry point."""
import argparse
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk

from csi_capture.desktop import Desktop
from csi_capture.processing import export_processed, process_session
from .collector import ACTIONS, BASE, LocalCoordinator


class LocalDesktop(Desktop):
    def __init__(self, root, coordinator, *, count=4, action="none"):
        self._auto_selected = False
        self._closing = False
        super().__init__(root, coordinator, None)
        root.geometry("1360x900")
        root.minsize(1160, 800)
        self.count.set(count)
        self.action = tk.StringVar(root, value=action)
        style = ttk.Style(root)
        style.configure("Action.Toolbutton", padding=(8, 8), anchor="center")
        style.map("Action.Toolbutton", background=[("selected", "#285e8e")],
                  foreground=[("selected", "white")])
        actions = ttk.LabelFrame(self.start_button.master, text="행동 선택", padding=6)
        actions.pack(fill="x", pady=(10, 0), before=self.start_button)
        self.action_buttons = {}
        for column, name in enumerate(ACTIONS):
            actions.columnconfigure(column, weight=1, uniform="action")
            button = ttk.Radiobutton(actions, text=name, value=name, variable=self.action,
                                     style="Action.Toolbutton")
            button.grid(row=0, column=column, sticky="ew", padx=2)
            self.action_buttons[name] = button
        self.folder_hint = tk.StringVar(root)
        ttk.Label(actions, textvariable=self.folder_hint).grid(row=1, column=0, columnspan=4,
                                                              sticky="w", pady=(6, 0))
        self.action.trace_add("write", self.update_folder_hint)
        self.update_folder_hint()

    def update_folder_hint(self, *_args):
        self.folder_hint.set(f"저장 이름: {self.action.get()}_YYMMDD_HHMMSS")

    def create_capture_job(self):
        job = self.coordinator.create_job([tuple(key.split("/")) for key in self.tree.selection()],
                                           self.wait.get(), sample_count=self.samples.get(),
                                           action=self.action.get())
        for button in self.action_buttons.values():
            button.state(["disabled"])
        return job

    def tick(self):
        super().tick()
        if self._closing:
            return
        online = self.online_ids()
        if self.tree.selection():
            self._auto_selected = True
        if not self._auto_selected and len(online) >= self.count.get():
            self.tree.selection_set(online[:self.count.get()])
            self._auto_selected = True
        if not self.coordinator.busy and not self.current_job:
            message = self.coordinator.discovery_error or f"USB 연결 {len(online)}대 · 수집할 ESP32를 선택하세요."
            self.status.set(message)
        if self.coordinator.busy or not online:
            self.start_button.configure(state="disabled")
        for button in self.action_buttons.values():
            button.state(["disabled"] if self.coordinator.busy else ["!disabled"])

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.start_button.configure(state="disabled")
        self.coordinator.shutdown(wait=False)
        self.capture_phase.set("결과 저장 후 종료")
        def finish():
            if self.coordinator.busy:
                self.root.after(50, finish)
                return
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()
        finish()


def main():
    parser = argparse.ArgumentParser(description="ESP32 USB CSI collection directly on the laptop")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ports", nargs="+", help="USB ports, e.g. /dev/ttyACM0 /dev/ttyACM1 /dev/ttyACM2 /dev/ttyACM3")
    group.add_argument("--config", type=Path, help="Optional JSON with explicit ESP names, ports and baud rates")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--wait", type=float, default=5)
    parser.add_argument("--samples", type=int, default=500, help="Final packet count after removing 25 packets at each end")
    parser.add_argument("--action", choices=ACTIONS, default="none", help="Action label for the saved session")
    parser.add_argument("--data-dir", type=Path, default=BASE / "data")
    parser.add_argument("--bindings", type=Path, default=BASE / "device_bindings.json")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.count <= 64 or args.baud <= 0:
        parser.error("장치 대수는 1–64, baud는 양수로 지정하세요.")
    devices = None
    config = args.config or (BASE / "config.local.json" if not args.ports and (BASE / "config.local.json").exists() else None)
    try:
        if config:
            devices = json.loads(config.read_text())["devices"]
            if not isinstance(devices, list) or not devices:
                raise ValueError("설정 파일의 devices 목록을 확인하세요.")
        elif args.ports:
            devices = [{"id": f"esp-{i:02d}", "port": port, "baud": args.baud}
                       for i, port in enumerate(args.ports, 1)]
        coordinator = LocalCoordinator(args.data_dir, devices=devices, baud=args.baud, bindings=args.bindings)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    if args.list_ports:
        for device in coordinator.refresh_devices():
            print(f'{device["id"]}\t{device["port"]}\t{"connected" if device["online"] else "offline"}')
        return
    if args.headless:
        try:
            online = [device for device in coordinator.refresh_devices() if device["online"]]
            if len(online) < args.count:
                raise ValueError(f"USB 장치 {len(online)}대 발견, 요청 {args.count}대. 연결과 포트를 확인하세요.")
            job = coordinator.create_job([("local", device["id"]) for device in online[:args.count]],
                                         args.wait, sample_count=args.samples, action=args.action)
            while coordinator.busy:
                time.sleep(.1)
            saved = coordinator.snapshot()["jobs"][job["id"]]
            result = process_session(coordinator.root / job["id"])
            export_processed(coordinator.root / job["id"], result)
            print(f'{saved["status"]}: {coordinator.root / job["id"]}')
            if saved["status"] != "completed":
                raise SystemExit(saved["message"] or "수집 목표를 채우지 못했습니다.")
        except ValueError as exc:
            parser.error(str(exc))
        except KeyboardInterrupt:
            coordinator.shutdown()
        return
    root = tk.Tk()
    try:
        app = LocalDesktop(root, coordinator, count=args.count, action=args.action)
        app.wait.set(args.wait)
        app.samples.set(args.samples)
        root.mainloop()
    finally:
        coordinator.shutdown()


if __name__ == "__main__":
    main()
