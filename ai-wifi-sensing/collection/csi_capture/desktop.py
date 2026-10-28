"""Native Tkinter frontend; no browser or frontend web server required."""
import argparse
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk, messagebox, filedialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from .processing import METRICS, device_keys, draw_plot, export_processed, process_session
from .server import ACTIVE, Coordinator, make_server

STATUS = {"preparing": "장치 준비 중", "waiting": "대기 중", "collecting": "수집 중",
          "uploading": "자동 전송 중", "completed": "수신 완료", "partial": "일부 데이터 누락",
          "cancelled": "취소됨", "failed": "실패", "interrupted": "서버 재시작으로 중단됨"}


def capture_timer(job, now=None):
    """Use the shared schedule, so redraws do not accumulate countdown drift."""
    now = time.time() if now is None else now
    if not job:
        return "수집 준비", "—", "장치를 선택하고 수집 시작을 누르세요.", "#475569"
    status = job["status"]
    if status == "preparing":
        return "장치 준비 중", "…", "USB 연결 준비가 끝나면 카운트다운을 시작합니다.", "#475569"
    if status in {"waiting", "collecting"}:
        if now < job["start_at"]:
            remaining = max(1, math.ceil(job["start_at"] - now))
            return "수집 시작까지", str(remaining), "초 후 수집 시작 · 자세와 위치를 준비하세요.", "#2563eb"
        if job.get("capture_mode") == "samples" and now < job["end_at"]:
            completed = sum(state.get("captured", 0) >= job["capture_count"] for state in job.get("progress", {}).values())
            hint = f'각 보드 {job["capture_count"]}개 수집 → 앞뒤 25개씩 제외 → 최종 {job["sample_count"]}개'
            return "길이 기준 수집 중", f'{completed}/{len(job["devices"])}', hint, "#15803d"
        if now < job["end_at"]:
            return "수집 중", f'{job["end_at"] - now:.1f}', "초 남음 · CSI 데이터를 기록하고 있습니다.", "#15803d"
        status = "uploading"
    if status == "uploading":
        return "수집 종료", "0", "결과를 자동 전송하고 있습니다.", "#2563eb"
    return STATUS.get(status, status), "—", "수집 결과를 확인하세요.", "#475569"


class Desktop:
    def __init__(self, root, coordinator, server):
        self.root, self.coordinator, self.server = root, coordinator, server
        self.local_mode = server is None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.current_job = None
        self.result = None
        self.result_folder = None
        self.loaded_signature = None
        self.load_generation = 0
        root.title("Wi-Fi CSI 수집 · 노트북 USB 직결" if self.local_mode else "Wi-Fi CSI 수집 · Multi Raspberry Pi")
        root.geometry("1240x860")
        root.minsize(1060, 760)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", padding=7)
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Treeview", rowheight=tkfont.nametofont("TkDefaultFont").metrics("linespace") + 10)
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Wi-Fi CSI 수집", style="Title.TLabel").pack(anchor="w")
        subtitle = "ESP32 → USB → 이 노트북 · 보드별 패킷 개수 수집" if self.local_mode else f"노트북 서버 :{server.server_port}  ·  ESP32 → USB → Raspberry Pi → 노트북"
        ttk.Label(outer, text=subtitle).pack(anchor="w", pady=(4, 10))
        connection = ttk.Frame(outer)
        connection.pack(fill="x")
        if self.local_mode:
            ttk.Button(connection, text="USB 새로고침", command=coordinator.refresh_devices).pack(side="left")
            ttk.Label(connection, text="USB 자동 검색 · 기본 4대 선택 · 시리얼 속도는 ESP32 펌웨어와 맞추세요.").pack(side="left", padx=8)
        else:
            ttk.Label(connection, text="고정 연결 토큰").pack(side="left")
            token = ttk.Entry(connection, width=46)
            token.insert(0, server.token)
            token.configure(state="readonly")
            token.pack(side="left", padx=8)
            ttk.Label(connection, text="노트북과 Pi에서 같은 .env 파일을 사용하세요.").pack(side="left")
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=12)
        right = ttk.Frame(panes, padding=6)
        if self.local_mode:
            controls = ttk.Frame(panes)
            controls.rowconfigure(0, weight=1)
            controls.columnconfigure(0, weight=1)
            self.controls_canvas = tk.Canvas(controls, width=380, highlightthickness=0,
                                             background=style.lookup("TFrame", "background"))
            scroll = ttk.Scrollbar(controls, orient="vertical", command=self.controls_canvas.yview)
            self.controls_canvas.configure(yscrollcommand=scroll.set)
            self.controls_canvas.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            left = ttk.Frame(self.controls_canvas, padding=6)
            window = self.controls_canvas.create_window(0, 0, window=left, anchor="nw")
            left.bind("<Configure>", lambda _e: self.controls_canvas.configure(
                scrollregion=self.controls_canvas.bbox("all")))
            self.controls_canvas.bind("<Configure>", lambda e: self.controls_canvas.itemconfigure(
                window, width=e.width))
            panes.add(controls, weight=1)
        else:
            left = ttk.Frame(panes, padding=6)
            panes.add(left, weight=1)
        panes.add(right, weight=4)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        ttk.Label(left, text="연결된 ESP32 · Ctrl/Shift로 여러 대 선택").pack(anchor="w")
        columns = ("port", "state") if self.local_mode else ("state",)
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings", selectmode="extended", height=4)
        self.tree.heading("#0", text="ESP32" if self.local_mode else "Pi / ESP32")
        self.tree.heading("state", text="상태 / 수집")
        self.tree.column("#0", width=90 if self.local_mode else 180)
        if self.local_mode:
            self.tree.heading("port", text="USB 포트")
            self.tree.column("port", width=130)
        self.tree.column("state", width=110)
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.selected.set(f"선택: {len(self.tree.selection())}대"))
        self.selected = tk.StringVar(value="선택: 0대")
        ttk.Label(left, textvariable=self.selected).pack(anchor="w")
        choices = ttk.Frame(left)
        choices.pack(fill="x", pady=8)
        self.count = tk.IntVar(value=4 if self.local_mode else 2)
        ttk.Spinbox(choices, from_=1, to=4096, textvariable=self.count, width=5).pack(side="left")
        ttk.Button(choices, text="대 선택", command=self.select_count).pack(side="left", padx=4)
        ttk.Button(choices, text="전체", command=lambda: self.tree.selection_set(self.online_ids())).pack(side="left")
        self.wait = tk.DoubleVar(value=5)
        self.samples = tk.IntVar(value=500)
        for title, var, minimum, maximum, increment in [("대기 시간 (초)", self.wait, 0, 3600, .5), ("최종 수집 길이 (개)", self.samples, 2, 20000, 25)]:
            row = ttk.Frame(left)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=title).pack(side="left")
            ttk.Spinbox(row, from_=minimum, to=maximum, increment=increment, textvariable=var, width=8).pack(side="right")
        self.sample_hint = tk.StringVar(value="보드당 550개 수집 · 앞뒤 25개씩 제외")
        ttk.Label(left, textvariable=self.sample_hint, wraplength=300).pack(fill="x", pady=4)
        self.samples.trace_add("write", self.update_sample_hint)
        self.start_button = ttk.Button(left, text="수집 시작", command=self.start)
        self.start_button.pack(fill="x", pady=(12, 4))
        ttk.Button(left, text="수집 취소", command=self.cancel).pack(fill="x")
        self.status = tk.StringVar(value="노트북의 USB 장치를 검색하는 중" if self.local_mode else "라즈베리파이 연결을 기다리는 중")
        ttk.Label(left, textvariable=self.status, wraplength=285).pack(fill="x", pady=12)
        self.progress = ttk.Progressbar(left, maximum=100)
        self.progress.pack(fill="x")
        ttk.Button(left, text="기존 결과 폴더 열기", command=self.open_result).pack(fill="x", pady=(12, 4))
        ttk.Button(left, text="그래프 PNG 저장", command=self.save_plot).pack(fill="x")
        timer = ttk.Frame(right, padding=(12, 4))
        timer.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.capture_phase = tk.StringVar(value="수집 준비")
        self.countdown = tk.StringVar(value="—")
        self.countdown_hint = tk.StringVar(value="장치를 선택하고 수집 시작을 누르세요.")
        ttk.Label(timer, textvariable=self.capture_phase, font=("TkDefaultFont", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(timer, textvariable=self.countdown_hint).grid(row=1, column=0, sticky="w")
        self.countdown_label = ttk.Label(timer, textvariable=self.countdown,
                                         font=("TkDefaultFont", 42, "bold"), foreground="#475569")
        self.countdown_label.grid(row=0, column=1, rowspan=2, padx=(20, 8), sticky="e")
        timer.columnconfigure(0, weight=1)
        plot_controls = ttk.Frame(right)
        plot_controls.grid(row=1, column=0, sticky="ew")
        view_row = ttk.Frame(plot_controls)
        view_row.pack(fill="x", pady=(0, 5))
        self.view = tk.StringVar(value="장치별 보기")
        view = ttk.Combobox(view_row, state="readonly", textvariable=self.view,
                            values=("장치별 보기", "통합 비교"), width=14)
        view.pack(side="left")
        view.bind("<<ComboboxSelected>>", lambda _e: self.redraw())
        self.page = 0
        self.page_label = tk.StringVar(value="")
        self.previous_page = ttk.Button(view_row, text="이전", command=lambda: self.change_page(-1))
        self.previous_page.pack(side="left", padx=(12, 4))
        ttk.Label(view_row, textvariable=self.page_label).pack(side="left")
        self.next_page = ttk.Button(view_row, text="다음", command=lambda: self.change_page(1))
        self.next_page.pack(side="left", padx=4)
        self.previous_page.configure(state="disabled")
        self.next_page.configure(state="disabled")
        metric_row = ttk.Frame(plot_controls)
        metric_row.pack(fill="x")
        self.metric = tk.StringVar(value=next(iter(METRICS)))
        metric = ttk.Combobox(metric_row, state="readonly", textvariable=self.metric, values=list(METRICS), width=22)
        metric.pack(side="left")
        metric.bind("<<ComboboxSelected>>", lambda _e: self.redraw())
        ttk.Label(metric_row, text="서브캐리어 0–51:").pack(side="left", padx=(12, 3))
        self.carrier = tk.IntVar(value=0)
        spin = ttk.Spinbox(metric_row, from_=0, to=51, textvariable=self.carrier, width=4, command=self.redraw)
        spin.pack(side="left")
        spin.bind("<Return>", lambda _e: self.redraw())
        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, right)
        self.canvas.get_tk_widget().grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False).grid(row=3, column=0, sticky="ew")
        self.canvas.mpl_connect("pick_event", self.toggle_line)
        self.legend_lines = {}
        self.details = tk.StringVar(value="수집 완료 후 ESP32별 그래프를 표시합니다.\n통합 비교 화면에서도 함께 볼 수 있습니다.")
        details = ttk.Label(right, textvariable=self.details, wraplength=800)
        details.grid(row=4, column=0, sticky="ew", pady=8)
        right.bind("<Configure>", lambda event: details.configure(wraplength=max(200, event.width - 16)))
        self.figure.add_subplot(111).set_title("Waiting for a capture")
        self.canvas.draw()
        self.root.after(250, self.tick)

    def online_ids(self):
        return [key for key in self.tree.get_children() if self.tree.set(key, "state") in ("연결됨", "모의 장치")]

    def select_count(self):
        try:
            count = self.count.get()
            online = self.online_ids()
            if not 1 <= count <= len(online):
                raise ValueError(f"선택 가능한 장치는 {len(online)}대입니다.")
            self.tree.selection_set(online[:count])
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("장치 선택", str(exc))

    def create_capture_job(self):
        return self.coordinator.create_job([tuple(key.split("/")) for key in self.tree.selection()],
                                           self.wait.get(), sample_count=self.samples.get())

    def start(self):
        try:
            job = self.create_capture_job()
            self.current_job = job["id"]
            self.loaded_signature = None
            self.load_generation += 1
            self.result = None
            self.page = 0
            self.progress["value"] = 0
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.text(.5, .5, "Waiting for collection result", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            self.canvas.draw_idle()
            self.update_timer(job)
        except (ValueError, tk.TclError, OSError) as exc:
            messagebox.showerror("수집 시작", str(exc))

    def cancel(self):
        if self.current_job:
            self.coordinator.cancel(self.current_job)

    def update_sample_hint(self, *_args):
        try:
            self.sample_hint.set(f"보드당 {self.samples.get() + 50}개 수집 · 앞뒤 25개씩 제외")
        except tk.TclError:
            pass

    def update_timer(self, job):
        phase, count, hint, color = capture_timer(job)
        if self.local_mode and job and job["status"] == "uploading":
            phase, hint = "수집 종료", "수집 결과를 노트북에 저장하고 있습니다."
        elif self.local_mode and job and job["status"] == "completed":
            phase = "수집 완료"
        self.capture_phase.set(phase)
        self.countdown.set(count)
        self.countdown_hint.set(hint)
        self.countdown_label.configure(foreground=color)

    def change_page(self, step):
        self.page += step
        self.redraw()

    def tick(self):
        snapshot = self.coordinator.snapshot()
        job = snapshot["jobs"].get(self.current_job)
        for pi_id, agent in snapshot["agents"].items():
            for device in agent["devices"]:
                key = f'{pi_id}/{device["id"]}'
                state = "오프라인" if time.time() - agent["last_seen"] > 5 else (
                    "작업 중" if agent["busy"] else "모의 장치" if device.get("simulated") else "연결됨")
                if self.local_mode and not device.get("online", True):
                    state = "미연결"
                if job and job.get("capture_mode") == "samples" and job["status"] in {"collecting", "uploading"}:
                    progress = job.get("progress", {}).get(key)
                    if progress:
                        state = f'{progress["captured"]}/{job["capture_count"]}'
                if not self.tree.exists(key):
                    self.tree.insert("", "end", iid=key, text=device["id"] if self.local_mode else key,
                                     values=(device.get("port", ""), state) if self.local_mode else (state,))
                else:
                    self.tree.item(key, values=(device.get("port", ""), state) if self.local_mode else (state,))
        self.start_button.configure(state="disabled" if any(j["status"] in ACTIVE for j in snapshot["jobs"].values()) else "normal")
        if job:
            self.update_timer(job)
            local_status = {"uploading": "저장 중", "completed": "수집 완료"}
            status = local_status.get(job["status"], STATUS[job["status"]]) if self.local_mode else STATUS[job["status"]]
            if job["status"] == "waiting":
                status += f' · {max(0, job["start_at"] - time.time()):.1f}초 남음'
            if job["status"] == "collecting":
                if job.get("capture_mode") == "samples":
                    status += f' · 보드당 최종 {job["sample_count"]}개'
                else:
                    status += f' · {max(0, job["end_at"] - time.time()):.1f}초 남음'
            verb = "저장" if self.local_mode else "수신"
            self.status.set(f'{status}\n{verb} {len(job["uploads"])}/{len(job["devices"])}대\n{job["message"]}')
            if job["start_at"]:
                if job.get("capture_mode") == "samples":
                    captured = sum(min(job["capture_count"], state.get("captured", 0)) for state in job.get("progress", {}).values())
                    self.progress["value"] = captured / (len(job["devices"]) * job["capture_count"]) * 100
                    if job["status"] == "collecting":
                        lines = []
                        for device in job["devices"][:4]:
                            key = f'{device["pi_id"]}/{device["id"]}'
                            count = job.get("progress", {}).get(key, {}).get("captured", 0)
                            label = device["id"] if self.local_mode else key
                            lines.append(f'{label}: {count} / {job["capture_count"]}개')
                        self.details.set("\n".join(lines))
                else:
                    self.progress["value"] = max(0, min(100, (time.time() - job["start_at"]) / job["duration_seconds"] * 100))
            signature = (job["id"], job["status"], len(job["uploads"]), len(job["results"]))
            if job["status"] not in ACTIVE and signature != self.loaded_signature:
                self.loaded_signature = signature
                self.load(self.coordinator.root / job["id"])
        try:
            while True:
                generation, folder, result, error = self.events.get_nowait()
                if generation != self.load_generation:
                    continue
                if error:
                    self.details.set(f"결과 처리 오류: {error}")
                else:
                    self.result, self.result_folder = result, folder
                    self.page = 0
                    self.redraw()
        except queue.Empty:
            pass
        self.root.after(250, self.tick)

    def load(self, folder):
        self.load_generation += 1
        generation = self.load_generation
        self.details.set("AI_WIFI 전처리 적용 중…")
        def work():
            try:
                result = process_session(folder)
                export_processed(folder, result)
                self.events.put((generation, folder, result, None))
            except Exception as exc:
                self.events.put((generation, folder, None, str(exc)))
        self.pool.submit(work)

    def redraw(self):
        if self.result is None:
            return
        try:
            carrier = self.carrier.get()
            if not 0 <= carrier <= 51:
                return
        except tk.TclError:
            return
        layout = "devices" if self.view.get() == "장치별 보기" else "combined"
        pages = max(1, math.ceil(len(device_keys(self.result)) / 4)) if layout == "devices" else 1
        self.page = max(0, min(self.page, pages - 1))
        self.page_label.set(f"{self.page + 1} / {pages}")
        self.previous_page.configure(state="normal" if self.page > 0 else "disabled")
        self.next_page.configure(state="normal" if self.page + 1 < pages else "disabled")
        draw_plot(self.figure, self.result, METRICS[self.metric.get()], carrier, layout=layout, page=self.page)
        self.legend_lines = {}
        for ax in self.figure.axes:
            legend = ax.get_legend()
            if legend:
                for handle, line in zip(legend.get_lines(), ax.lines):
                    handle.set_picker(5)
                    self.legend_lines[handle] = line
        self.canvas.draw_idle()
        keys = device_keys(self.result)
        shown = keys[self.page * 4:(self.page + 1) * 4] if layout == "devices" else keys[:4]
        statuses = self.result.get("device_status", {})
        summaries = [f'{key.split("/", 1)[1] if self.local_mode else key}: {statuses[key]["message"]}'
                     for key in shown if key in statuses]
        self.details.set("\n".join(summaries) + (f"\n총 {len(keys)}대 · 장치별 보기에서 이전/다음으로 확인" if len(keys) > 4 else "")
                         + f"\n저장 위치: {self.result_folder}")

    def toggle_line(self, event):
        line = self.legend_lines.get(event.artist)
        if line:
            line.set_visible(not line.get_visible())
            event.artist.set_alpha(1 if line.get_visible() else .2)
            self.canvas.draw_idle()

    def open_result(self):
        folder = filedialog.askdirectory(initialdir=self.coordinator.root, title="session.json이 있는 폴더 선택")
        if folder:
            self.current_job = None
            self.capture_phase.set("저장된 결과 보기")
            self.countdown.set("—")
            self.countdown_hint.set("장치별 결과 또는 통합 비교를 선택하세요.")
            self.load(Path(folder))

    def save_plot(self):
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if path:
            self.figure.savefig(path, dpi=160)

    def close(self):
        if self.current_job:
            self.coordinator.cancel(self.current_job)
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Native Python CSI collection desktop")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    root = tk.Tk()
    try:
        coordinator = Coordinator(args.data_dir)
        server = make_server(coordinator, args.host, args.port)
    except (OSError, ValueError) as exc:
        messagebox.showerror("서버 시작 실패", str(exc))
        root.destroy()
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Desktop(root, coordinator, server)
    try:
        root.mainloop()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
