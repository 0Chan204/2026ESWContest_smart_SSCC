import copy
import json

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from csi_capture.desktop import capture_timer
from csi_capture.processing import draw_plot, process_session


def result_with_missing_device():
    t = np.arange(0, 5, .04)
    series = {"time": t, "change": np.sin(t), "rssi": np.full(len(t), -42),
              "amp": np.ones((len(t), 52)), "raw_time": t, "raw_mean": np.ones(len(t)),
              "info": {"rows_used": len(t)}}
    return {"job": {"duration_seconds": 5, "devices": [
        {"pi_id": "pi-01", "id": "esp-01"}, {"pi_id": "pi-01", "id": "esp-02"}]},
        "series": {"pi-01/esp-02": series}, "device_status": {
            "pi-01/esp-01": {"raw_rows": 0, "accepted_rows": 0, "plot_message": "No CSI data received"},
            "pi-01/esp-02": {"usable_rows": len(t)}}}


def test_missing_device_keeps_its_own_panel_and_no_fabricated_curve():
    figure = Figure(figsize=(8, 6))
    FigureCanvasAgg(figure)
    result = result_with_missing_device()
    draw_plot(figure, result, layout="devices")
    figure.canvas.draw()
    missing, received = figure.axes
    assert "pi-01/esp-01" in missing.get_title()
    assert "NO DATA" in missing.get_title()
    assert len(missing.lines) == 0
    assert "No CSI data received" in missing.texts[0].get_text()
    assert len(received.lines) == 1
    assert received.lines[0].get_label() == "pi-01/esp-02"
    assert received.get_xlim() == missing.get_xlim() == (0, 5)
    # Its color stays the same when switching back to the combined view.
    color = received.lines[0].get_color()
    draw_plot(figure, result, layout="combined")
    assert len(figure.axes) == 1
    assert figure.axes[0].lines[0].get_color() == color


def test_device_graphs_paginate_across_multiple_pis():
    result = result_with_missing_device()
    series = result["series"]["pi-01/esp-02"]
    result["job"]["devices"] = [{"pi_id": f"pi-{i:02}", "id": "esp-01"} for i in range(1, 7)]
    result["series"] = {f"pi-{i:02}/esp-01": copy.deepcopy(series) for i in range(1, 7)}
    figure = Figure(figsize=(9, 7))
    FigureCanvasAgg(figure)
    draw_plot(figure, result, layout="devices", page=0)
    assert len(figure.axes) == 4
    draw_plot(figure, result, layout="devices", page=1)
    assert len(figure.axes) == 2
    assert "pi-05/esp-01" in figure.axes[0].get_title()
    assert "pi-06/esp-01" in figure.axes[1].get_title()
    assert sum(len(ax.lines) for ax in figure.axes) == 2


def test_countdown_uses_scheduled_start_and_capture_end():
    job = {"status": "waiting", "start_at": 105, "end_at": 110}
    assert [capture_timer(job, t)[1] for t in (100, 101, 102, 103, 104)] == ["5", "4", "3", "2", "1"]
    assert capture_timer(job, 104.99)[0:2] == ("수집 시작까지", "1")
    assert capture_timer(job, 105)[0:2] == ("수집 중", "5.0")
    assert capture_timer(job, 107.4)[0:2] == ("수집 중", "2.6")
    assert capture_timer(job, 110)[0:2] == ("수집 종료", "0")
    job["status"] = "cancelled"
    assert capture_timer(job, 101)[0:2] == ("취소됨", "—")
    job["status"] = "preparing"
    assert capture_timer(job, 100)[0:2] == ("장치 준비 중", "…")


def test_empty_capture_retains_status_for_each_selected_esp(tmp_path):
    job = {"devices": [{"pi_id": "pi-01", "id": "esp-01"}, {"pi_id": "pi-01", "id": "esp-02"}],
           "start_at": None, "duration_seconds": 5}
    (tmp_path / "session.json").write_text(json.dumps(job))
    result = process_session(tmp_path)
    assert set(result["device_status"]) == {"pi-01/esp-01", "pi-01/esp-02"}
    figure = Figure(figsize=(8, 6))
    FigureCanvasAgg(figure)
    draw_plot(figure, result, layout="devices")
    assert len(figure.axes) == 2
    assert all("Collection never started" in ax.texts[0].get_text() for ax in figure.axes)


def test_sample_mode_countdown_changes_to_per_board_completion():
    job = {"status": "collecting", "capture_mode": "samples", "start_at": 105, "end_at": 705,
           "capture_count": 550, "sample_count": 500, "devices": [{}, {}],
           "progress": {"pi-01/esp-01": {"captured": 550}, "pi-01/esp-02": {"captured": 120}}}
    assert capture_timer(job, 104)[0:2] == ("수집 시작까지", "1")
    assert capture_timer(job, 120)[0:2] == ("길이 기준 수집 중", "1/2")
    assert "500" in capture_timer(job, 120)[2]


def test_sample_graph_uses_packet_index_and_preserves_length():
    result = result_with_missing_device()
    result["job"].update(capture_mode="samples", sample_count=125, duration_seconds=None)
    result["series"]["pi-01/esp-02"]["sample"] = np.arange(1, 126)
    figure = Figure(figsize=(8, 6))
    FigureCanvasAgg(figure)
    draw_plot(figure, result, layout="devices")
    assert all(ax.get_xlim() == (1, 125) for ax in figure.axes)
    assert figure.axes[1].get_xlabel() == "Sample index"
    assert len(figure.axes[1].lines[0].get_xdata()) == 125
