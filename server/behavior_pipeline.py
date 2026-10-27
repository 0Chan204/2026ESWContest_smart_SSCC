# behavior_pipeline.py
"""
행동(낙상 / 눕기 / 기상) 추론용 전처리 & 특성 추출 모듈
=======================================================

재실 파이프라인(wifi_occupancy_pipeline.py)과 '같은 방식'으로 학습·실시간(Pi)이 한 코드를 공유한다.
재실 파이프라인은 건드리지 않고, 행동용은 아래 점이 다르다.

  재실                               행동
  ─────────────────────────────────  ─────────────────────────────────
  서브캐리어 52개 (6개는 항상 0)      유효 서브캐리어 56개 (k = 4~31, 33~60)
  Hampel(3σ) + Savitzky-Golay        Hampel(5σ)만 (SG 생략: 낙상의 짧고 강한 변화를 깎지 않으려고)
  25Hz, 2초/10초 윈도우              20Hz, 6초 윈도우 (1초마다)
  '가만히 있는 사람' 특성            '순간 이벤트' 특성 (에너지 피크, 전후 정지 상태 변화 ...)

20Hz 로 정한 이유: 수신 속도가 날마다 15~27Hz 로 변한다. 모든 경우의 아래쪽(16Hz)보다 약간 높은 눈금에
맞춰 두면 '보간으로 부풀리는 양'이 적다. 스펙트럼 특성은 7Hz 까지만 본다(16Hz 수신의 나이퀴스트 8Hz 안쪽).

행동 클래스: none / fall / lie_down / get_up
  - 낙상은 모든 노드(r2·r3·r4), 눕기·기상은 방(r3)에서만 허용 (NODE_CLASSES)
"""

import hashlib
import json
from dataclasses import dataclass, asdict, fields
from typing import Optional

import numpy as np
import pandas as pd
from scipy.signal import detrend, periodogram
from scipy.stats import kurtosis

from wifi_occupancy_pipeline import (
    hampel_filter, parse_lltf_amplitude, reconstruct_time, resample_uniform,
)

# ==========================================================
# 0. 상수
# ==========================================================
LABELS = ["none", "fall", "lie_down", "get_up"]        # 인덱스 = 클래스 번호
EVENT_LABELS = ["fall", "lie_down", "get_up"]
NODES = ["r2", "r3", "r4"]
NODE_CLASSES = {                                         # 노드별로 낼 수 있는 행동
    "r2": ["none", "fall"],
    "r3": ["none", "fall", "lie_down", "get_up"],
    "r4": ["none", "fall"],
}

# ESP32 LLTF 64칸 중 실제 신호가 있는 56칸 (예시 CSV와 재실 CSV 모두에서 확인: 4~31, 33~60, 32 = DC)
SUBCARRIER_IDX = np.r_[4:32, 33:61]
NUM_SUBCARRIERS = len(SUBCARRIER_IDX)   # 56

N_SEG = 6        # 윈도우를 1초씩 6조각으로 나눠 에너지 궤적을 봄 (window_sec = 6 기준)
N_GROUPS = 4     # 앞/뒤 정지 상태 변화량을 서브캐리어 4묶음으로 나눠 '방향'을 봄

PIPELINE_VERSION = 1   # 특성 계산 방식을 바꾸면 올릴 것 → 옛 모델과 섞이지 않게 막아 줌

FEATURE_NAMES = (
    ["e_peak", "e_mean", "e_p90", "e_median", "e_peak_ratio", "e_peak_edge"]
    + [f"seg_sorted_{i}" for i in range(N_SEG)]
    + ["e_pre", "e_post", "e_post_pre"]
    + ["shift_mag"] + [f"shift_g{i}" for i in range(N_GROUPS)]
    + ["pc1_logstd", "pc1_ratio", "pc2_logstd"]
    + ["imp_max", "imp_ratio", "imp_kurt"]
    + ["band_low", "band_mid", "band_high"]
    + ["rssi_std", "rssi_range"]
)
NUM_FEATURES = len(FEATURE_NAMES)   # 31


# ==========================================================
# 1. 설정 & 지문
# ==========================================================
@dataclass
class BehaviorConfig:
    fs: float = 20.0               # 리샘플링 주파수(Hz). fs × step_sec 가 정수여야 함
    window_sec: float = 6.0        # 이벤트 하나가 통째로 들어갈 길이
    step_sec: float = 1.0          # 실시간에서 윈도우를 밀어 가는 간격
    max_gap_sec: float = 1.0       # 이보다 긴 패킷 공백이 섞인 윈도우는 버림 (0.5초 공백 1건에 파일 전체가 버려지는 일이 있어 1.0으로 완화)
    hampel_k: int = 3
    hampel_sigmas: float = 5.0     # 재실(3σ)보다 느슨하게: 낙상 충격이 이상치로 깎이지 않도록
    normalize_agc: bool = True
    edge_sec: float = 1.5          # 윈도우 앞/뒤 이 구간의 평균을 비교해 '자세 변화'를 봄
    margin_sec: float = 1.0        # 에너지 피크 전/후 비교에서 피크 주변을 비우는 길이
    bands: tuple = (0.3, 1.5, 4.0, 7.0)   # 스펙트럼 대역 경계(Hz): 저 / 중 / 고


def behavior_config_from_dict(d: dict) -> BehaviorConfig:
    known = {f.name for f in fields(BehaviorConfig)}
    clean = {k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k in known}
    return BehaviorConfig(**clean)


def make_behavior_hash(cfg: BehaviorConfig) -> str:
    """전처리 설정 + 특성 목록 + 서브캐리어 + 코드 버전 → 8자리. Pi 와 서버/학습 PC 가 같은지 확인용"""
    payload = {
        "version": PIPELINE_VERSION,
        "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()},
        "features": FEATURE_NAMES,
        "subcarriers": SUBCARRIER_IDX.tolist(),
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]


# ==========================================================
# 2. 윈도우 특성 추출 (31개)
# ==========================================================
def _log(v, eps=1e-4):
    return float(np.log(v + eps))


def extract_features(W: np.ndarray, rssi: np.ndarray, cfg: BehaviorConfig) -> np.ndarray:
    """
    W    : (윈도우 샘플 수, 56)  AGC 보정 + Hampel + 균일 리샘플이 끝난 진폭
    rssi : (윈도우 샘플 수,)
    반환 : (31,) — 순서는 FEATURE_NAMES

    생각의 틀
      낙상  = 짧고 '강한' 에너지 피크 + 그 뒤의 정지
      눕기  = 중간 강도의 느린 변화 + 정지 자세(서브캐리어 패턴)가 바뀜
      기상  = 눕기와 비슷하지만 정지 패턴 변화의 '방향'이 반대
    """
    n, fs, eps = len(W), cfg.fs, 1e-6

    # (1) 움직임 에너지 궤적: 인접 샘플 사이 변화량의 크기 (서브캐리어 평균)
    d = np.diff(W, axis=0)
    e = np.sqrt((d ** 2).mean(axis=1))
    k = max(1, int(round(0.5 * fs)))
    es = np.convolve(e, np.ones(k) / k, mode="same")          # 0.5초 평활
    pk = int(np.argmax(es))
    pos = pk / max(len(es) - 1, 1)                            # 피크가 윈도우의 어디쯤인가 (0~1)
    med = float(np.median(e))

    # 1초 조각별 에너지를 '큰 순서로' 정렬 → 피크가 윈도우 어디에 있든 같은 값 (위치 불변)
    seg = np.array([np.sqrt(np.mean(s ** 2)) for s in np.array_split(e, N_SEG)])
    seg_sorted = np.sort(seg)[::-1]

    # 피크 앞/뒤의 '조용한 수준' (피크 ±margin 은 비움)
    m = int(round(cfg.margin_sec * fs))
    pre_v = float(e[:pk - m].mean()) if pk - m >= 3 else med
    post_v = float(e[pk + m:].mean()) if len(e) - (pk + m) >= 3 else med

    # (2) 정지 자세의 변화: 윈도우 맨 앞 1.5초 평균 vs 맨 뒤 1.5초 평균
    he = max(1, int(round(cfg.edge_sec * fs)))
    diff = W[-he:].mean(axis=0) - W[:he].mean(axis=0)
    rms = float(np.sqrt(np.mean(diff ** 2)))
    shift_g = [float(g.mean()) / (rms + 1e-3) for g in np.array_split(diff, N_GROUPS)]  # 방향(부호 포함)

    # (3) PCA: 서브캐리어들이 함께 흔들리는 정도
    c = W - W.mean(axis=0)
    _, s, vt = np.linalg.svd(c, full_matrices=False)
    s1 = c @ vt[0]
    pv = s ** 2 / max(n - 1, 1)
    pv = np.pad(pv, (0, max(0, 2 - len(pv))))

    # (4) 충격성: PC1 이 얼마나 갑자기 변하는가
    ds = np.abs(np.diff(s1))
    kur = float(kurtosis(ds)) if ds.std() > 0 else 0.0
    if not np.isfinite(kur):
        kur = 0.0

    # (5) 스펙트럼 (PC1): 저/중/고 대역 비율
    f, pxx = periodogram(detrend(s1), fs=fs, window="hann")
    edges = cfg.bands
    tot = pxx[(f >= edges[0]) & (f < edges[-1])].sum() + eps
    bands = [pxx[(f >= a) & (f < b)].sum() / tot for a, b in zip(edges[:-1], edges[1:])]

    feats = (
        [_log(es[pk]), _log(e.mean()), _log(np.percentile(e, 90)), _log(med),
         _log(es[pk] / (med + 1e-4)), min(pos, 1.0 - pos)]
        + [_log(v) for v in seg_sorted]
        + [_log(pre_v), _log(post_v), _log(post_v / (pre_v + 1e-4))]
        + [_log(rms)] + shift_g
        + [_log(np.sqrt(pv[0])), float(pv[0] / (pv.sum() + eps)), _log(np.sqrt(pv[1]))]
        + [_log(ds.max()), _log(ds.max() / (np.median(ds) + 1e-3)), kur]
        + bands
        + [float(np.std(rssi)), float(np.ptp(rssi))]
    )
    return np.nan_to_num(np.asarray(feats, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)


# ==========================================================
# 3. 학습/실시간 공용 처리기
# ==========================================================
class BehaviorProcessor:
    """
      process_stream(t, amp56, rssi, target_end_ticks=None, stride_sec=None)
        t      : 패킷 시각(초, 학습·실시간 모두 '인과적 offset' 방식으로 복원한 값)
        amp56  : (N, 56) 서브캐리어 진폭 (SUBCARRIER_IDX 로 이미 고른 것)
      학습: 파일 전체를 넣고 stride_sec 를 작게(예: 0.25초) 줘서 윈도우를 촘촘히 뽑음
      Pi  : 최근 7초 버퍼를 넣고 target_end_ticks={이번 초} 하나만 계산
    """

    def __init__(self, cfg: Optional[BehaviorConfig] = None):
        self.cfg = cfg or BehaviorConfig()
        c = self.cfg
        if abs(c.fs * c.step_sec - round(c.fs * c.step_sec)) > 1e-9:
            raise ValueError("fs × step_sec 가 정수여야 합니다.")

    def preprocess(self, t, amp, rssi):
        cfg = self.cfg
        if len(t) < 2:
            return None
        t = np.asarray(t, dtype=np.float64)
        amp = np.asarray(amp, dtype=np.float64)
        rssi = np.asarray(rssi, dtype=np.float64)

        order = np.argsort(t, kind="stable")
        t, amp, rssi = t[order], amp[order], rssi[order]
        uniq = np.r_[True, np.diff(t) > 0]
        t, amp, rssi = t[uniq], amp[uniq], rssi[uniq]
        ok = np.all(np.isfinite(amp), axis=1) & (amp.mean(axis=1) > 0) & np.isfinite(rssi)
        t, amp, rssi = t[ok], amp[ok], rssi[ok]
        if len(t) < 2:
            return None

        if cfg.normalize_agc:
            amp = amp / amp.mean(axis=1, keepdims=True)
        amp = hampel_filter(amp, cfg.hampel_k, cfg.hampel_sigmas)

        ticks, xu, valid = resample_uniform(t, np.column_stack([amp, rssi]), cfg.fs, cfg.max_gap_sec)
        if len(ticks) == 0:
            return None
        return {"ticks": ticks, "amp": xu[:, :NUM_SUBCARRIERS], "rssi": xu[:, NUM_SUBCARRIERS], "valid": valid}

    def process_stream(self, t, amp, rssi, target_end_ticks=None, stride_sec=None):
        """반환: (특성 (윈도우 수, 31), 윈도우 끝 tick (윈도우 수,))"""
        cfg = self.cfg
        empty = (np.empty((0, NUM_FEATURES), dtype=np.float32), np.empty(0, dtype=np.int64))
        pre = self.preprocess(t, amp, rssi)
        if pre is None:
            return empty
        ticks, amp_u, rssi_u, valid = pre["ticks"], pre["amp"], pre["rssi"], pre["valid"]
        win_n = int(round(cfg.window_sec * cfg.fs))
        stride_n = int(round((stride_sec if stride_sec else cfg.step_sec) * cfg.fs))
        bad_cum = np.concatenate([[0], np.cumsum(~valid)])

        feats, ends = [], []
        for e in range(win_n - 1, len(ticks)):
            if ticks[e] % stride_n != 0:          # 윈도우 끝은 '절대 시각'의 배수 (노드끼리 정렬)
                continue
            if target_end_ticks is not None and int(ticks[e]) not in target_end_ticks:
                continue
            s = e - win_n + 1
            if bad_cum[e + 1] - bad_cum[s] > 0:   # 윈도우 안에 패킷 공백
                continue
            feats.append(extract_features(amp_u[s:e + 1], rssi_u[s:e + 1], cfg))
            ends.append(ticks[e])
        if not feats:
            return empty
        return np.vstack(feats), np.asarray(ends, dtype=np.int64)

    # ---------- 학습 전용 ----------
    def event_info(self, t, amp, rssi):
        """
        파일 하나(이벤트 1개)에서 '이벤트가 일어난 순간'을 찾는다 = 움직임 에너지가 가장 큰 곳.
        반환 dict: center(절대 초), center_rel(파일 시작 기준 초), dur(파일 길이), peak_ratio(피크 / 중앙값)
          peak_ratio 가 작으면(≈1.5 미만) 에너지로는 이벤트가 안 보인다 → 중심 검출을 믿기 어려움
        데이터가 모자라면 None.
        """
        pre = self.preprocess(t, amp, rssi)
        if pre is None or len(pre["ticks"]) < 10:
            return None
        cfg = self.cfg
        e = np.sqrt((np.diff(pre["amp"], axis=0) ** 2).mean(axis=1))
        k = max(1, int(round(0.5 * cfg.fs)))
        es = np.convolve(e, np.ones(k) / k, mode="same")
        idx = int(np.argmax(es))
        t0 = float(pre["ticks"][0] / cfg.fs)
        c = float(pre["ticks"][idx + 1] / cfg.fs)
        return {"center": c, "center_rel": c - t0, "dur": float((pre["ticks"][-1] - pre["ticks"][0]) / cfg.fs),
                "peak_ratio": float(es[idx] / (np.median(e) + 1e-6))}

    def event_center_sec(self, t, amp, rssi):
        """(center_sec 또는 None, 파일 길이(초)) — event_info 의 얇은 래퍼"""
        ei = self.event_info(t, amp, rssi)
        return (None, 0.0) if ei is None else (ei["center"], ei["dur"])


# ==========================================================
# 4. CSV 로드 (학습용)
# ==========================================================
def _expand_raw_lines(df: pd.DataFrame) -> pd.DataFrame:
    """
    `host_timestamp, raw_line` 두 열짜리 raw 형식 → 표준 형식(host_timestamp, local_timestamp, data, rssi, mac, first_word, len).
    raw_line 은 ESP32 가 보낸 시리얼 한 줄 그대로:  local_timestamp,"[CSI...]",rssi,mac,first_word,len
    """
    import csv as _csv
    rows = []
    for h, line in zip(df["host_timestamp"].to_numpy(), df["raw_line"].to_numpy()):
        try:
            r = next(_csv.reader([str(line)]))
        except Exception:
            continue
        if len(r) == 6:
            rows.append([h] + r)
    return pd.DataFrame(rows, columns=["host_timestamp", "local_timestamp", "data", "rssi", "mac", "first_word", "len"])


def load_behavior_csv(csv_path: str, target_mac: Optional[str] = None,
                      thin_to_hz: Optional[float] = None, rng: Optional[np.random.Generator] = None):
    """
    로거가 만든 CSV → (시각[초], 진폭 (N,56), RSSI (N,), 정보 dict)
    시각 복원은 재실 파이프라인(reconstruct_time)과 똑같다.

    thin_to_hz: 수신 속도가 이 값보다 높으면 패킷을 무작위로 솎아 이 속도에 맞춘다.
                (재실 데이터 26Hz 를 행동 데이터 16Hz 와 비슷하게 만들어 'none' 으로 쓰기 위함)
    """
    df = pd.read_csv(csv_path)
    if "raw_line" in df.columns and "data" not in df.columns:      # *.raw.csv 형식
        df = _expand_raw_lines(df)
    info = {"file": csv_path, "rows_total": len(df)}
    if "mac" in df.columns and len(df) > 0:
        macs = df["mac"].astype(str).str.strip().str.lower()
        if target_mac is None:
            target_mac = macs.mode().iloc[0]
        keep = macs == target_mac.lower()
        info["mac_ratio"] = float(keep.mean())
        df = df[keep.values]

    t, stale, tinfo = reconstruct_time(df)
    info.update(tinfo)
    df, t = df[~stale], t[~stale]

    rssi_all = pd.to_numeric(df["rssi"], errors="coerce").to_numpy(dtype=np.float64)
    amps, keep_idx = [], []
    for i, s in enumerate(df["data"].to_numpy()):
        a = parse_lltf_amplitude(s)
        if a is not None and np.isfinite(rssi_all[i]):
            amps.append(a[SUBCARRIER_IDX])
            keep_idx.append(i)
    keep_idx = np.asarray(keep_idx, dtype=np.int64)
    t, rssi = t[keep_idx], rssi_all[keep_idx]
    amp = np.asarray(amps, dtype=np.float64).reshape(-1, NUM_SUBCARRIERS)

    rate = (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 and t[-1] > t[0] else 0.0
    info["rate_hz_raw"] = rate
    if thin_to_hz and rate > thin_to_hz * 1.05:
        rng = rng or np.random.default_rng(0)
        m = rng.random(len(t)) < thin_to_hz / rate
        t, amp, rssi = t[m], amp[m], rssi[m]
        rate = (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 else 0.0
        info["thinned"] = True
    info["rate_hz"] = rate
    info["rows_used"] = len(t)
    info["amp_mean"] = float(amp.mean()) if len(amp) else 0.0     # 신호 크기 (CSI 정수값이 작으면 양자화 잡음이 큼)
    return t, amp, rssi, info
