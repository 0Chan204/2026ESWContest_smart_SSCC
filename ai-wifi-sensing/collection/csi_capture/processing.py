"""Visualization adapter around the unchanged AI_WIFI preprocessing pipeline."""
import json
import csv
from pathlib import Path

import numpy as np

from .vendor.ai_wifi_pipeline import (CSIDataProcessor, ProcessingConfig, load_csi_csv,
                                     parse_csi_amplitude, hampel_filter, savgol_filter)


def load_packet_csv(path, target_mac=None):
    """Preserve every retained packet in order; no clock-based row dropping."""
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    t, amp, rssi = [], [], []
    for row in rows:
        if target_mac and row["mac"].lower() != target_mac.lower():
            continue
        value = parse_csi_amplitude(row["data"], bool(int(row["first_word"])))
        host, signal = float(row["host_timestamp"]), float(row["rssi"])
        if value is not None and np.isfinite(host) and np.isfinite(signal):
            t.append(host)
            amp.append(value)
            rssi.append(signal)
    t = np.asarray(t, dtype=float)
    info = {"rows_total": len(rows), "rows_used": len(t), "time_source": "host_timestamp; packet order retained",
            "rate_hz": (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 and t[-1] > t[0] else 0}
    return t, np.asarray(amp, dtype=float).reshape(-1, 52), np.asarray(rssi, dtype=float), info


def preprocess_packets(amp, cfg):
    """AI_WIFI amplitude filters in packet order, without inventing time samples."""
    filtered = amp / amp.mean(axis=1, keepdims=True) if cfg.normalize_agc else amp.copy()
    filtered = hampel_filter(filtered, cfg.hampel_k, cfg.hampel_sigmas)
    if len(filtered) >= cfg.savgol_window:
        filtered = savgol_filter(filtered, cfg.savgol_window, cfg.savgol_polyorder, axis=0)
    return filtered


def process_session(folder):
    folder = Path(folder)
    job = json.loads((folder / "session.json").read_text())
    cfg = ProcessingConfig()
    sample_mode = job.get("capture_mode") == "samples"
    result = {"job": job, "series": {}, "warnings": [], "device_status": {}}
    for device in job["devices"]:
        key = f'{device["pi_id"]}/{device["id"]}'
        capture = job.get("results", {}).get(device["pi_id"], {}).get("devices", {}).get(device["id"], {})
        upload = job.get("uploads", {}).get(key, {})
        result["device_status"][key] = {"raw_rows": int(capture.get("raw_rows", 0)),
                                        "accepted_rows": upload.get("accepted_rows", 0), "usable_rows": 0,
                                        "message": "아직 결과를 받지 못했습니다.",
                                        "plot_message": "Result not received"}
    if job["start_at"] is None:
        result["warnings"].append("Collection never started.")
        for status in result["device_status"].values():
            status.update(message="수집이 시작되지 않았습니다.", plot_message="Collection never started")
        return result
    for device in job["devices"]:
        key = f'{device["pi_id"]}/{device["id"]}'
        status = result["device_status"][key]
        path = folder / device.get("file", f'{device["pi_id"]}/{device["id"]}.csv')
        if not path.exists():
            result["warnings"].append(f"{key}: file not received")
            continue
        try:
            loader = load_packet_csv if sample_mode else load_csi_csv
            t, amp, rssi, info = loader(path, device.get("target_mac") or None)
            if not sample_mode:
                keep = np.isfinite(t) & (t >= job["start_at"]) & (t < job["end_at"])
                t, amp, rssi = t[keep], amp[keep], rssi[keep]
            status["usable_rows"] = len(t)
            if len(t) < 2 or (not sample_mode and len(np.unique(t)) < 2):
                if status["raw_rows"] == 0:
                    status.update(message="CSI 데이터가 수신되지 않았습니다.", plot_message="No CSI data received")
                elif status["accepted_rows"] == 0:
                    status.update(message="수신한 CSI 형식을 해석하지 못했습니다.", plot_message="CSI format not recognized")
                else:
                    status.update(message="유효 CSI 패킷이 2개 미만입니다.", plot_message="Fewer than two usable CSI packets")
                result["warnings"].append(f"{key}: fewer than two usable CSI packets")
                continue
            if sample_mode:
                filtered = preprocess_packets(amp, cfg)
                baseline = np.median(filtered[:min(25, len(filtered))], axis=0)
                change = np.sqrt(np.mean((filtered - baseline) ** 2, axis=1))
                result["series"][key] = {"time": t - job["start_at"], "sample": np.arange(1, len(t) + 1),
                                         "amp": filtered, "change": change, "rssi": rssi,
                                         "raw_time": t - job["start_at"], "raw_mean": amp.mean(axis=1),
                                         "info": info, "valid": np.ones(len(t), dtype=bool),
                                         "simulated": device.get("simulated", False)}
                status.update(message=f'최종 CSI {len(t)} / {job["sample_count"]}개 (앞뒤 {job["trim_each"]}개씩 제외)', plot_message="")
                if len(t) != job["sample_count"]:
                    result["warnings"].append(f'{key}: only {len(t)}/{job["sample_count"]} retained packets')
                continue
            processed = CSIDataProcessor(cfg).preprocess(t, amp, rssi, keep_steps=True)
            if processed is None:
                status.update(message="25Hz 전처리를 적용하기에 데이터가 너무 짧습니다.",
                              plot_message="Recording too short for 25 Hz resampling")
                result["warnings"].append(f"{key}: recording too short for 25 Hz resampling")
                continue
            times = processed["ticks"] / cfg.fs - job["start_at"]
            valid = processed["valid"]
            filtered = processed["amp"].copy()
            filtered[~valid] = np.nan  # Never draw interpolation over long packet gaps.
            baseline_rows = valid & (times <= times[0] + 1)
            if not baseline_rows.any():
                baseline_rows = valid
            baseline = np.nanmedian(filtered[baseline_rows], axis=0) if baseline_rows.any() else np.full(52, np.nan)
            change = np.sqrt(np.mean((filtered - baseline) ** 2, axis=1))
            rss = processed["rssi"].copy()
            rss[~valid] = np.nan
            raw_times = processed["steps"]["t_raw"] - job["start_at"]
            raw_mean = processed["steps"]["raw"].mean(axis=1)
            # Break the raw curve as well at packet loss boundaries.
            raw_mean[np.r_[False, np.diff(raw_times) > cfg.max_gap_sec]] = np.nan
            result["series"][key] = {"time": times, "amp": filtered, "change": change, "rssi": rss,
                                     "raw_time": raw_times, "raw_mean": raw_mean, "info": info,
                                     "valid": valid, "simulated": device.get("simulated", False)}
            status.update(message=f"유효 CSI {len(t)}개", plot_message="")
            if not valid.all():
                result["warnings"].append(f"{key}: {int((~valid).sum())} invalid resampling ticks (packet gaps)")
            if "리셋" in info.get("time_source", ""):
                result["warnings"].append(f"{key}: ESP32 clock reset; host timestamps used")
        except (ValueError, KeyError, OSError) as exc:
            status.update(message=f"결과 처리 실패: {exc}", plot_message="Unable to process CSI data")
            result["warnings"].append(f"{key}: {exc}")
    return result


METRICS = {"변화량 RMS (기본)": "change", "서브캐리어 진폭": "subcarrier",
           "원본 진폭 평균": "raw_mean", "RSSI": "rssi"}


def device_keys(result):
    keys = [f'{device["pi_id"]}/{device["id"]}' for device in result["job"].get("devices", [])]
    return list(dict.fromkeys([*keys, *result["series"]]))


def draw_plot(figure, result, metric="change", subcarrier=0, layout="combined", page=0):
    figure.clear()
    labels = {"change": "Normalized amplitude change (RMS)", "subcarrier": "Normalized amplitude",
              "raw_mean": "Raw amplitude (mean of 52 subcarriers)", "rssi": "RSSI (dBm)"}
    short_labels = {"change": "RMS change", "subcarrier": "Amp. (AGC)",
                    "raw_mean": "Raw amp.", "rssi": "RSSI (dBm)"}
    keys = device_keys(result)
    colors = {key: f"C{index % 10}" for index, key in enumerate(keys)}
    simulated = any(device.get("simulated") for device in result["job"].get("devices", []))
    sample_mode = result["job"].get("capture_mode") == "samples"
    local_mode = result["job"].get("source") == "local_usb"
    title = ("SIMULATED DATA | " if simulated else "") + (
        "Laptop USB / ESP32 Wi-Fi CSI" if local_mode else "Multi-Pi / ESP32 Wi-Fi CSI")

    def display_name(key):
        return key.split("/", 1)[1] if local_mode else key

    def plot_series(ax, key):
        series = result["series"][key]
        x = series["sample"] if sample_mode else series["raw_time"] if metric == "raw_mean" else series["time"]
        y = series["amp"][:, subcarrier] if metric == "subcarrier" else series[metric]
        ax.plot(x, y, label=display_name(key), color=colors[key], linewidth=1.4)

    if layout == "devices" and keys:
        page = max(0, min(int(page), (len(keys) - 1) // 4))
        shown = keys[page * 4:(page + 1) * 4]
        columns = 1 if len(shown) <= 2 else 2
        rows = (len(shown) + columns - 1) // columns
        axes = figure.subplots(rows, columns, sharex=True, squeeze=False).ravel()
        for ax, key in zip(axes, shown):
            status = result.get("device_status", {}).get(key, {})
            if key in result["series"]:
                plot_series(ax, key)
                packets = status.get("usable_rows", result["series"][key]["info"]["rows_used"])
                ax.set_title(f"{display_name(key)} | {packets} usable packets", color=colors[key], fontsize=11)
                ax.legend(loc="upper right", fontsize=8)
            else:
                ax.set_title(f"{display_name(key)} | NO DATA", color="#b45309", fontsize=11)
                message = status.get("plot_message", "No usable CSI data")
                counts = f'Raw: {status.get("raw_rows", 0)} | Accepted: {status.get("accepted_rows", 0)}'
                ax.text(.5, .5, f"{message}\n{counts}", transform=ax.transAxes,
                        ha="center", va="center", color="#b45309", fontsize=10)
        for ax in axes[len(shown):]:
            figure.delaxes(ax)
        figure.suptitle(title, fontsize=11)
    else:
        ax = figure.add_subplot(111)
        for key in keys:
            if key in result["series"]:
                plot_series(ax, key)
        ax.set_title(title)
        if result["series"]:
            ax.legend(loc="upper right", fontsize=9)
        else:
            ax.text(.5, .5, "No usable CSI data", transform=ax.transAxes, ha="center")
    for ax in figure.axes:
        ax.set_xlabel("Sample index" if sample_mode else "Time from start (s)" if layout == "devices" else "Time from scheduled start (seconds)", fontsize=9)
        ax.set_ylabel(short_labels[metric] if layout == "devices" else labels[metric], fontsize=9)
        ax.set_xlim((1, result["job"]["sample_count"]) if sample_mode else (0, result["job"]["duration_seconds"]))
        ax.grid(True, alpha=.22)
    figure.tight_layout()
    return figure.axes[0]


def export_processed(folder, result):
    """Save every processed carrier, not just the plotted summary."""
    folder = Path(folder) / "processed"
    folder.mkdir(exist_ok=True)
    for key, series in result["series"].items():
        name = key.split("/", 1)[1] if result["job"].get("source") == "local_usb" else key.replace("/", "__")
        target = folder / (name + ".csv")
        sample_mode = result["job"].get("capture_mode") == "samples"
        columns = ([series["sample"]] if sample_mode else []) + [series["time"], series["valid"], series["change"], series["rssi"], series["amp"]]
        matrix = np.column_stack(columns)
        header = ("sample_index," if sample_mode else "") + "elapsed_seconds,valid,change_rms,rssi," + ",".join(f"sc_{i:02d}" for i in range(52))
        np.savetxt(target, matrix, delimiter=",", header=header, comments="")
    return folder
