# wifi_occupancy_pipeline.py
"""
WiFi CSI 기반 재실 감지 - 전처리 & 특성 추출 공통 모듈
=========================================================

학습(train_multizone_model.py)과 나중에 만들 실시간 추론이 '완전히 같은' 처리를
거치도록, 전처리와 특성 추출 로직을 모두 이 파일 하나에 모아 둔다.
(학습 때와 추론 때 처리가 조금이라도 다르면 성능이 크게 떨어진다.)

CSV 1개(= ESP32 노드 1개의 기록)를 처리하는 순서
  1) CSV 읽기 → 송신기(AP) MAC만 남기기 → CSI 문자열을 진폭 52개로 변환
  2) AGC(자동 이득) 보정: 패킷마다 진폭을 평균값으로 나눠 '전체 세기 튐'을 제거
  3) Hampel 필터: 갑자기 튀는 값(이상치)을 주변 중앙값으로 교체
  4) 균일한 시간축으로 리샘플링 (예: 정확히 25Hz) + 패킷이 끊긴 구간 표시
  5) Savitzky-Golay 필터: 잔떨림(고주파 노이즈) 제거
  6) 1초마다 윈도우를 잘라 특성 19개 추출
     - 짧은 윈도우(2초): 움직임 크기
     - 긴 윈도우(10초): 호흡처럼 느리고 작은 변화 → '가만히 있는 사람' 감지용
"""

import hashlib
import json
from collections import deque
from dataclasses import dataclass, asdict, fields
from typing import Optional

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import savgol_filter, detrend, periodogram
from scipy.stats import entropy


# ==========================================================
# 0. 프로젝트 공통 상수
# ==========================================================

# 클래스 (1인 가구 가정: 사람은 최대 한 구역에만 있음)
LABELS = ["empty", "room", "kitchen", "toilet"]   # 인덱스 = 클래스 번호 0~3

# 노드(장소) 코드. 이 순서대로 특성을 이어 붙인다.
LOCATION_CODES = ["r2", "r3", "r4"]
LOCATION_NAMES = {"r2": "부엌", "r3": "방", "r4": "화장실"}


# ==========================================================
# 1. ESP32 서브캐리어 배치
# ==========================================================
#
# ESP32가 보내는 CSI 배열 앞부분 128개 값 = LLTF 구간의 서브캐리어 64개.
# 서브캐리어 하나당 값 2개(허수부, 실수부)가 붙어 있다.
#
# 배열 인덱스 k 와 실제 주파수 번호의 관계 (FFT 순서):
#   k =  0 ~ 31  →  주파수  0 ~ +31
#   k = 32 ~ 63  →  주파수 -32 ~ -1
#
# 802.11 20MHz 기준으로 실제 신호가 실리는 곳은 주파수 -26 ~ -1, +1 ~ +26 (총 52개).
#   - 주파수 0 (k=0)          : DC, 항상 0 근처
#   - 주파수 ±27 ~ ±32 (k=27~37): 가드 밴드, 항상 0 근처
# → 유효 인덱스 = k 38~63(음의 주파수) + k 1~26(양의 주파수)
#   (주파수가 낮은 쪽부터 높은 쪽 순서로 정렬해 둔다)
#
# ※ 실제 보드에서 맞는지는 check_csi_data.py 로 꼭 한 번 확인할 것.

RAW_SUBCARRIERS = 64
VALID_SUBCARRIER_IDX = np.r_[38:64, 1:27]
NUM_SUBCARRIERS = len(VALID_SUBCARRIER_IDX)  # 52


def parse_lltf_amplitude(csi_str) -> Optional[np.ndarray]:
    """
    CSI 문자열 "[a0, b0, a1, b1, ...]" → LLTF 서브캐리어 64개의 진폭.
    진폭 = sqrt(a^2 + b^2) 이므로 허수/실수 순서는 결과에 영향이 없다.
    파싱에 실패하거나 길이가 모자라면 None을 돌려준다 (0으로 채우지 않음!).
    """
    try:
        raw = np.asarray(json.loads(csi_str), dtype=np.float32)
    except (ValueError, TypeError):
        return None
    if raw.ndim != 1 or raw.size < RAW_SUBCARRIERS * 2:
        return None
    iq = raw[: RAW_SUBCARRIERS * 2].reshape(RAW_SUBCARRIERS, 2)
    return np.hypot(iq[:, 0], iq[:, 1])


def parse_csi_amplitude(csi_str, first_word_invalid: bool = False) -> Optional[np.ndarray]:
    """
    CSI 문자열 → 유효 서브캐리어 52개의 진폭. 쓸 수 없는 패킷이면 None.

    first_word_invalid:
        ESP32 하드웨어 제약으로 배열의 '첫 4바이트'(= 서브캐리어 0, 1번)가
        깨졌을 수 있다는 표시. 0번은 어차피 안 쓰고, 1번은 바로 옆 2번 값으로 채운다.
        (패킷 전체를 버릴 필요는 없다.)
    """
    amp64 = parse_lltf_amplitude(csi_str)
    if amp64 is None:
        return None
    if first_word_invalid:
        amp64[1] = amp64[2]
    amp = amp64[VALID_SUBCARRIER_IDX]
    if not np.all(np.isfinite(amp)) or amp.mean() <= 0:
        return None
    return amp


# ==========================================================
# 2. 필터 & 리샘플링
# ==========================================================

def hampel_filter(x: np.ndarray, k: int = 3, n_sigmas: float = 3.0) -> np.ndarray:
    """
    Hampel 필터 (이상치 제거). x: (시간, 채널)

    각 시점마다 앞뒤 k개(총 2k+1개) 이웃의 중앙값과 MAD를 구해서,
    |값 - 중앙값| > n_sigmas × 1.4826 × MAD 이면 그 값을 중앙값으로 바꾼다.
    (1.4826 × MAD ≈ 정규분포의 표준편차)

    기존 코드는 파이썬 이중 for문이었는데, 여기서는 한 번에(벡터화) 계산해서
    실시간 처리에서도 충분히 빠르다.
    """
    if len(x) < 2 * k + 1:
        return x.copy()
    padded = np.pad(x, ((k, k), (0, 0)), mode="edge")
    win = sliding_window_view(padded, 2 * k + 1, axis=0)          # (시간, 채널, 2k+1)
    med = np.median(win, axis=-1)
    mad = np.median(np.abs(win - med[..., None]), axis=-1)
    thr = n_sigmas * 1.4826 * mad
    is_outlier = (np.abs(x - med) > thr) & (thr > 0)
    return np.where(is_outlier, med, x)


def resample_uniform(t: np.ndarray, x: np.ndarray, fs: float, max_gap_sec: float):
    """
    불규칙하게 들어온 패킷(t, x)을 정확히 fs Hz 간격의 시간축으로 옮긴다 (선형 보간).

    왜 필요한가?
      ESP32의 CSI 수신 속도는 주변 트래픽에 따라 들쭉날쭉하다.
      '25행 = 1초'라고 가정하면 노드마다 실제 시간이 달라져서 3개 노드가 어긋난다.

    시간축은 '절대 시각 × fs'의 정수 눈금(tick)에 맞춘다.
      → 서로 다른 노드도 같은 tick = 같은 시각이 되어, 나중에 tick 기준으로 합칠 수 있다.

    반환값
      ticks : 정수 눈금 배열 (tick / fs = 시각[초])
      x_u   : (len(ticks), 채널) 리샘플된 값
      valid : 각 눈금 주변에 max_gap_sec 보다 긴 패킷 공백이 없으면 True
    """
    first_tick = int(np.ceil(t[0] * fs))
    last_tick = int(np.floor(t[-1] * fs))
    if last_tick <= first_tick:
        return np.array([], dtype=np.int64), np.empty((0, x.shape[1])), np.array([], dtype=bool)

    ticks = np.arange(first_tick, last_tick + 1, dtype=np.int64)
    grid = ticks / fs

    x_u = np.empty((len(grid), x.shape[1]), dtype=np.float64)
    for d in range(x.shape[1]):
        x_u[:, d] = np.interp(grid, t, x[:, d])

    # 각 눈금을 감싸는 두 실제 패킷 사이 간격이 너무 길면 '보간으로 지어낸 값' → 무효
    right = np.clip(np.searchsorted(t, grid, side="left"), 1, len(t) - 1)
    gap = t[right] - t[right - 1]
    valid = gap <= max_gap_sec
    return ticks, x_u, valid


# ==========================================================
# 3. 설정값
# ==========================================================

@dataclass
class ProcessingConfig:
    fs: float = 25.0               # 리샘플링 주파수(Hz). check_csi_data.py로 본 실제 수신 속도에 맞출 것
    short_window_sec: float = 2.0  # 움직임 특성용 윈도우 (기존 1초는 통계가 너무 불안정)
    long_window_sec: float = 10.0  # 호흡 등 느린 변화용 윈도우 (0.1Hz 해상도를 얻으려면 10초 필요)
    step_sec: float = 1.0          # 1초마다 판단 1번 (윈도우끼리 겹침)
    max_gap_sec: float = 0.5       # 이보다 긴 패킷 공백이 섞인 윈도우는 버림
    hampel_k: int = 3
    hampel_sigmas: float = 3.0
    savgol_window: int = 7
    savgol_polyorder: int = 3
    normalize_agc: bool = True     # 패킷별 평균으로 나눠 AGC(자동 이득) 튐 제거
    breath_band: tuple = (0.1, 0.6)   # 호흡 대역(Hz): 분당 6~36회
    motion_band: tuple = (0.6, 3.0)   # 몸 움직임 대역(Hz)


# 노드 1개당 추출되는 특성 19개의 이름 (노드 3개 → 57차원)
FEATURE_NAMES = [
    # --- 짧은 윈도우(2초): 서브캐리어 52개 각각의 값을 '요약'한 것 ---
    "sc_std_mean", "sc_std_max", "sc_std_p90",     # 표준편차: 평균 / 최댓값 / 상위 10% 경계
    "sc_iqr_mean", "sc_iqr_max", "sc_iqr_p90",     # 사분위범위
    "sc_ac1_mean", "sc_ac1_p10",                   # lag-1 자기상관 (신호가 매끄럽게 변하는 정도)
    "sc_crest_mean",                               # crest factor (순간 피크 정도)
    # --- 짧은 윈도우: 52개 서브캐리어를 PCA로 묶은 공통 변화 ---
    "pc1_std", "pc2_std", "pc3_std",               # 주성분 1~3의 세기
    "pc1_var_ratio",                               # 전체 변화 중 주성분1 비율 (사람 움직임은 여러 서브캐리어를 함께 흔듦)
    # --- 짧은 윈도우: RSSI ---
    "rssi_std", "rssi_iqr",
    # --- 긴 윈도우(10초): 느린 변화 ---
    "long_sc_std_mean",                            # 10초 동안의 평균 변동
    "long_pc1_logvar",                             # 10초 주성분1 세기
    "breath_band_ratio",                           # 주성분1 파워 중 호흡 대역 비율
    "motion_band_ratio",                           # 주성분1 파워 중 움직임 대역 비율
]
NUM_FEATURES = len(FEATURE_NAMES)  # 19


# ==========================================================
# 4. 특성 추출
# ==========================================================

def _log(v, eps=1e-4):
    """변동 크기 특성은 분포가 한쪽으로 길게 늘어져 있어서 log를 씌우면 SVM이 다루기 쉬워진다."""
    return float(np.log(v + eps))


def extract_window_features(short_amp: np.ndarray, short_rssi: np.ndarray,
                            long_amp: np.ndarray, cfg: ProcessingConfig) -> np.ndarray:
    """
    short_amp : (짧은 윈도우 샘플 수, 52)   short_rssi : (짧은 윈도우 샘플 수,)
    long_amp  : (긴 윈도우 샘플 수, 52)
    반환      : (19,) 특성 벡터 (순서는 FEATURE_NAMES와 같음)
    """
    eps = 1e-6
    T = len(short_amp)
    c = short_amp - short_amp.mean(axis=0)   # 서브캐리어별 평균 제거 (변동만 남김)

    # (1) 서브캐리어별 통계 → 52개 값을 평균/최대/분위수로 요약
    #     기존 코드는 52개를 전부 특성으로 써서 노드당 210차원이었다.
    #     인접 서브캐리어는 거의 같은 정보라 요약해도 손실이 적고, 샘플 수 대비 차원이 크게 준다.
    sc_std = short_amp.std(axis=0)
    q75, q25 = np.percentile(short_amp, [75, 25], axis=0)
    sc_iqr = q75 - q25
    sc_ac1 = (c[1:] * c[:-1]).sum(axis=0) / ((c ** 2).sum(axis=0) + eps)
    rms = np.sqrt((short_amp ** 2).mean(axis=0))
    sc_crest = np.abs(short_amp).max(axis=0) / (rms + eps)

    # (2) PCA: 사람이 움직이면 여러 서브캐리어가 '같이' 흔들린다 → 첫 주성분에 모임
    sv = np.linalg.svd(c, compute_uv=False)
    pc_var = sv ** 2 / max(T - 1, 1)
    pc_var = np.pad(pc_var, (0, max(0, 3 - len(pc_var))))
    pc1_ratio = pc_var[0] / (pc_var.sum() + eps)

    # (3) 긴 윈도우: 주성분1의 시간 신호를 주파수 분석
    lc = long_amp - long_amp.mean(axis=0)
    _, s_l, vt_l = np.linalg.svd(lc, full_matrices=False)
    pc1_signal = detrend(lc @ vt_l[0])                       # 천천히 흐르는 추세(드리프트) 제거
    f, pxx = periodogram(pc1_signal, fs=cfg.fs, window="hann")
    total = pxx[f >= cfg.breath_band[0]].sum() + eps
    breath_ratio = pxx[(f >= cfg.breath_band[0]) & (f < cfg.breath_band[1])].sum() / total
    motion_ratio = pxx[(f >= cfg.motion_band[0]) & (f < cfg.motion_band[1])].sum() / total
    long_pc1_var = s_l[0] ** 2 / max(len(long_amp) - 1, 1)

    return np.array([
        _log(sc_std.mean()), _log(sc_std.max()), _log(np.percentile(sc_std, 90)),
        _log(sc_iqr.mean()), _log(sc_iqr.max()), _log(np.percentile(sc_iqr, 90)),
        sc_ac1.mean(), np.percentile(sc_ac1, 10),
        sc_crest.mean(),
        _log(np.sqrt(pc_var[0])), _log(np.sqrt(pc_var[1])), _log(np.sqrt(pc_var[2])),
        pc1_ratio,
        float(np.std(short_rssi)), float(np.subtract(*np.percentile(short_rssi, [75, 25]))),
        _log(long_amp.std(axis=0).mean()),
        _log(long_pc1_var),
        breath_ratio,
        motion_ratio,
    ], dtype=np.float32)


# ==========================================================
# 5. CSV 로드 & 전체 처리
# ==========================================================

def _unwrap_esp_clock(ts_us: np.ndarray):
    """
    ESP32 local_timestamp(부팅 후 µs, 32비트) → 첫 행 기준 경과 시간(초).
    32비트 카운터는 약 71.6분마다 0으로 돌아가므로(wrap) 그만큼 더해서 이어 붙인다.
    반환: (경과 초 배열, 정상 여부). 중간에 ESP32가 재부팅되어 시계가 리셋됐으면 False.
    """
    d = np.diff(ts_us.astype(np.float64))
    neg = d < 0
    if np.any(neg):
        # wrap 이면 직전 값이 2^32 근처(큰 값)였어야 함. 아니면 재부팅에 의한 리셋.
        if np.any(ts_us[:-1][neg] < 2 ** 31):
            return None, False
        d[neg] += 2 ** 32
    return np.r_[0.0, np.cumsum(d)] / 1e6, True


def reconstruct_time(df: pd.DataFrame):
    """
    각 패킷의 '실제 수신 시각'(PC 시계 기준, 초)을 복원한다.

    왜 host_timestamp 를 그대로 쓰면 안 되나?
      host_timestamp = PC가 그 줄을 '읽은' 시각이지, ESP32가 패킷을 '받은' 시각이 아니다.
      로거가 시작 시각을 기다리는 동안 시리얼 데이터가 USB/OS 버퍼에 쌓여 있으면,
      녹화가 시작되자마자 그 '옛날 패킷'들이 한꺼번에 쏟아져 들어오고
      전부 현재 시각이 찍힌다. → 60초 녹화에 100초 분량이 들어가 Hz가 부풀고(예: 45Hz),
      시작 전(실험자가 움직이던 때)의 데이터가 섞이고, 노드 간 시간도 어긋난다.

    해결: ESP32 자체 시계(local_timestamp)로 패킷 사이 간격을 정확히 알고,
          PC 시계와의 차이(offset)만 구해서 PC 시각으로 옮긴다.
            offset = min( host_timestamp - esp_time )
          버퍼에 밀려 늦게 읽힌 패킷은 (host - esp) 가 커지므로, 최솟값 = 지연 없이 바로 읽힌 패킷.
          → 실제 수신 시각 = esp_time + offset

    [10/08 수정] offset 을 '파일 전체'의 최솟값이 아니라 '그 패킷까지 받은 데이터'의 최솟값으로 계산한다.
      실시간(Pi)은 미래 데이터를 볼 수 없으므로 이렇게밖에 계산할 수 없다. 학습도 똑같이 계산해야
      두 쪽 시각이 정확히 같아진다. (예전처럼 전체 최솟값을 쓰면 PC 읽기 지연이 들쭉날쭉한 노드에서
      시각이 수십 ms 어긋나고, 특성 값도 조금씩 달라졌다 → replay_test 일치율 저하의 원인)
      단, '녹화 시작 전 밀린 패킷' 판별에는 파일 전체 최솟값을 그대로 쓴다.

    반환: (시각 배열, 버릴 행 mask, 정보 dict)
      버릴 행 = 복원한 시각이 '로거가 첫 줄을 읽은 시각'보다 앞선 행 = 녹화 시작 전에 쌓여 있던 패킷
    """
    n = len(df)
    info = {"time_source": None, "backlog_sec": 0.0, "stale_rows": 0}
    stale = np.zeros(n, dtype=bool)
    if n == 0:
        info["time_source"] = "none"
        return np.empty(0), stale, info

    has_host = "host_timestamp" in df.columns
    esp_t, ok = (None, False)
    if "local_timestamp" in df.columns:
        esp_t, ok = _unwrap_esp_clock(pd.to_numeric(df["local_timestamp"], errors="coerce")
                                      .ffill().fillna(0).to_numpy())

    if has_host and ok:
        host = df["host_timestamp"].to_numpy(dtype=np.float64)
        lag = host - esp_t                                   # 읽기 지연 + 고정된 시계 차이
        offset = lag.min()
        stale = (esp_t + offset) < host[0] - 0.05            # 녹화 시작(첫 줄 읽은 시각) 이전 패킷
        info.update(time_source="esp_clock+causal_offset",
                    backlog_sec=float(lag.max() - offset),   # 가장 많이 밀렸던 정도
                    stale_rows=int(stale.sum()))
        # 실제 시각은 남은 패킷만으로 '실시간과 똑같이' 계산
        raw = pd.to_numeric(df["local_timestamp"], errors="coerce").ffill().fillna(0).to_numpy()
        t = np.full(n, np.nan)
        t_keep = causal_times(raw[~stale], host[~stale])
        if t_keep is None:                                   # 중간 리셋 → PC 시각 사용
            t = host.copy()
            info["time_source"] = "host (ESP32 시계 리셋 감지)"
        else:
            t[~stale] = t_keep
    elif has_host:
        # ESP32 시계가 중간에 리셋됨 → 어쩔 수 없이 PC 시각 사용
        t = df["host_timestamp"].to_numpy(dtype=np.float64)
        info["time_source"] = "host (ESP32 시계 리셋 감지)"
    elif ok:
        # 예전 CSV(host_timestamp 없음): 0초부터 시작하는 상대 시각. 노드 간 정렬은 시작 시각이 같다는 가정에 의존
        t = esp_t
        info["time_source"] = "esp_local"
    else:
        t = np.arange(n, dtype=np.float64) / 25.0
        info["time_source"] = "row_index (시각 정보 없음)"
    return t, stale, info


def load_csi_csv(csv_path: str, target_mac: Optional[str] = None):
    """
    로거가 만든 CSV → (시각[초], 진폭 (N,52), RSSI (N,), 정보 dict)

    target_mac:
        송신기(AP) MAC. None이면 파일 안에서 가장 많이 나온 MAC을 AP로 본다.
        다른 기기가 보낸 패킷은 채널 경로가 달라서 섞이면 큰 노이즈가 된다.
    """
    df = pd.read_csv(csv_path)
    info = {"file": csv_path, "rows_total": len(df)}

    # --- MAC 필터링 ---
    if "mac" in df.columns and len(df) > 0:
        macs = df["mac"].astype(str).str.strip().str.lower()
        if target_mac is None:
            target_mac = macs.mode().iloc[0]
        keep = macs == target_mac.lower()
        info["mac"] = target_mac
        info["mac_ratio"] = float(keep.mean())
        df = df[keep.values]

    # --- 시각 (+ 녹화 시작 전에 밀려 있던 옛날 패킷 제거) ---
    t, stale, tinfo = reconstruct_time(df)
    info.update(tinfo)
    df, t = df[~stale], t[~stale]

    # --- CSI 문자열 → 진폭 ---
    if "first_word" in df.columns:
        fw = pd.to_numeric(df["first_word"], errors="coerce").fillna(0).to_numpy() != 0
    else:
        fw = np.zeros(len(df), dtype=bool)
    rssi_all = pd.to_numeric(df["rssi"], errors="coerce").to_numpy(dtype=np.float64)

    amps, keep_idx = [], []
    for i, (s, bad_first) in enumerate(zip(df["data"].to_numpy(), fw)):
        a = parse_csi_amplitude(s, bad_first)
        if a is not None and np.isfinite(rssi_all[i]):
            amps.append(a)
            keep_idx.append(i)

    keep_idx = np.asarray(keep_idx, dtype=np.int64)
    t = t[keep_idx]
    amp = np.asarray(amps, dtype=np.float64).reshape(-1, NUM_SUBCARRIERS)
    rssi = rssi_all[keep_idx]

    info["rows_used"] = len(t)
    info["rate_hz"] = (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 and t[-1] > t[0] else 0.0
    return t, amp, rssi, info


class CSIDataProcessor:
    """
    학습/실시간 공용 처리기.
      - 학습      : process_csv(경로)  → 파일 전체의 특성
      - 실시간    : process_stream(t, amp, rssi) 에 최근 12초 정도의 버퍼를 넣고
                    마지막 행(가장 최근 윈도우)만 쓰면 된다.
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.cfg = config or ProcessingConfig()

    def preprocess(self, t: np.ndarray, amp: np.ndarray, rssi: np.ndarray, keep_steps: bool = False):
        """
        전처리만 수행 (특성 추출 직전까지). 데이터가 부족하면 None.

        반환 dict
          ticks, amp (리샘플+평활화 완료, (M,52)), rssi (M,), valid (M,)
          keep_steps=True 이면 'steps' 에 단계별 중간 결과도 담는다 (시각화용):
            t_raw  : 실제 패킷 시각
            raw    : 원본 진폭
            agc    : AGC 보정 후
            hampel : Hampel 필터 후
            resampled : 균일 시간축 리샘플 직후 (Savitzky-Golay 전)
        """
        cfg = self.cfg
        if len(t) < 2:
            return None

        # 시간순 정렬 + 같은 시각 중복 제거
        order = np.argsort(t, kind="stable")
        t, amp, rssi = t[order], amp[order], rssi[order]
        uniq = np.r_[True, np.diff(t) > 0]
        t, amp, rssi = t[uniq], amp[uniq], rssi[uniq]
        steps = {"t_raw": t, "raw": amp} if keep_steps else None

        # (1) AGC 보정: 각 패킷을 서브캐리어 평균으로 나눔 → 전체 세기가 통째로 바뀌는 효과 제거
        #     (세기 정보는 RSSI 특성이 따로 담당)
        if cfg.normalize_agc:
            amp = amp / amp.mean(axis=1, keepdims=True)
        if keep_steps:
            steps["agc"] = amp

        # (2) Hampel: 리샘플 '전'에 실제 패킷 순서대로 적용 (보간이 이상치를 번지게 하지 않도록)
        amp = hampel_filter(amp, cfg.hampel_k, cfg.hampel_sigmas)
        if keep_steps:
            steps["hampel"] = amp

        # (3) 균일 시간축으로 리샘플링
        ticks, xu, valid = resample_uniform(t, np.column_stack([amp, rssi]), cfg.fs, cfg.max_gap_sec)
        if len(ticks) == 0:
            return None
        amp_u, rssi_u = xu[:, :NUM_SUBCARRIERS], xu[:, NUM_SUBCARRIERS]
        if keep_steps:
            steps["resampled"] = amp_u.copy()

        # (4) Savitzky-Golay: '스트림 전체'에 한 번 적용 (윈도우마다 따로 하면 양 끝이 틀어짐)
        if len(amp_u) >= cfg.savgol_window > cfg.savgol_polyorder:
            amp_u = savgol_filter(amp_u, cfg.savgol_window, cfg.savgol_polyorder, axis=0)

        return {"ticks": ticks, "amp": amp_u, "rssi": rssi_u, "valid": valid, "steps": steps}

    def process_stream(self, t: np.ndarray, amp: np.ndarray, rssi: np.ndarray,
                       target_end_ticks: Optional[set] = None):
        """
        반환: features (윈도우 수, 19), end_ticks (윈도우 수,)
          end_ticks = 각 윈도우가 끝나는 시각의 정수 눈금 (tick / fs = 초)

        target_end_ticks: 실시간(Pi)용. 이 tick 에서 끝나는 윈도우만 계산한다.
          (버퍼 안에 윈도우가 여러 개 들어가도 '이번 초' 것만 계산해서 Pi 부담을 줄임)
          None 이면 가능한 윈도우를 전부 계산 (학습용).
        """
        cfg = self.cfg
        empty = (np.empty((0, NUM_FEATURES), dtype=np.float32), np.empty(0, dtype=np.int64))
        pre = self.preprocess(t, amp, rssi)
        if pre is None:
            return empty
        ticks, amp_u, rssi_u, valid = pre["ticks"], pre["amp"], pre["rssi"], pre["valid"]

        # (5) 슬라이딩 윈도우
        short_n = int(round(cfg.short_window_sec * cfg.fs))
        long_n = int(round(cfg.long_window_sec * cfg.fs))
        step_n = int(round(cfg.step_sec * cfg.fs))
        bad_cum = np.concatenate([[0], np.cumsum(~valid)])   # 구간 안 '무효 샘플 수'를 빠르게 세기 위한 누적합

        feats, ends = [], []
        for e in range(long_n - 1, len(ticks)):
            # 윈도우 끝을 '절대 시각이 step의 배수'인 곳에만 둔다
            # → 노드 3개가 정확히 같은 시각의 윈도우를 갖게 되어 tick으로 바로 합칠 수 있음
            if ticks[e] % step_n != 0:
                continue
            if target_end_ticks is not None and int(ticks[e]) not in target_end_ticks:
                continue
            s_long = e - long_n + 1
            if bad_cum[e + 1] - bad_cum[s_long] > 0:          # 긴 윈도우 안에 패킷 공백 → 버림
                continue
            s_short = e - short_n + 1
            feats.append(extract_window_features(
                amp_u[s_short:e + 1], rssi_u[s_short:e + 1], amp_u[s_long:e + 1], cfg))
            ends.append(ticks[e])

        if not feats:
            return empty
        return np.vstack(feats), np.asarray(ends, dtype=np.int64)

    def process_csv(self, csv_path: str, target_mac: Optional[str] = None):
        """CSV 1개 → (특성, 윈도우 끝 tick, 정보 dict)"""
        t, amp, rssi, info = load_csi_csv(csv_path, target_mac)
        feats, ends = self.process_stream(t, amp, rssi)
        info["n_windows"] = len(feats)
        return feats, ends, info

    def config_dict(self) -> dict:
        return asdict(self.cfg)


# ==========================================================
# 6-1. 설정 지문(hash) — 학습과 실시간의 전처리가 같은지 확인용
# ==========================================================

PIPELINE_VERSION = 2   # 특성 계산 방식(코드)을 바꾸면 이 숫자를 올릴 것 → 옛 모델과 섞이지 않게 막아 줌
                       # v2 (10/08): 시각 계산을 학습/실시간 동일한 방식(causal offset)으로 통일


def config_from_dict(d: dict) -> ProcessingConfig:
    """
    dict(JSON/pkl 에 저장된 설정) → ProcessingConfig.
    JSON 은 tuple 을 list 로 바꿔 저장하므로 다시 tuple 로 되돌린다 (지문이 같아지도록).
    """
    known = {f.name for f in fields(ProcessingConfig)}
    clean = {k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k in known}
    return ProcessingConfig(**clean)


def make_config_hash(cfg: ProcessingConfig) -> str:
    """
    전처리 설정 + 특성 목록 + 서브캐리어 배치 + 코드 버전 → 짧은 문자열(8자리).
    학습 PC 와 Pi 에서 이 값이 같으면 '같은 방식으로 특성을 만든다'고 믿을 수 있다.
    하나라도 다르면 오류 없이 정확도만 조용히 떨어지므로, 서버가 이 값을 비교해서 막는다.
    """
    payload = {
        "version": PIPELINE_VERSION,
        "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()},
        "features": FEATURE_NAMES,
        "subcarriers": VALID_SUBCARRIER_IDX.tolist(),
    }
    text = json.dumps(payload, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()[:8]


# ==========================================================
# 6-2. 실시간용 시계 복원 (Pi 에서 사용)
# ==========================================================

class OnlineClock:
    """
    reconstruct_time() 의 실시간 버전.
    패킷이 하나씩 들어올 때마다 'ESP32 시계 → Pi 시계' 변환값(offset)을 갱신한다.

      esp_sec  = ESP32 local_timestamp 를 초 단위로 이어 붙인 값 (32비트 wrap 처리)
      offset   = 최근 window_sec 초 동안의 min(host_ts − esp_sec)
                 → 지연 없이 바로 읽힌 패킷 기준 (밀려서 늦게 읽힌 패킷은 이 값이 큼)
      실제 시각 = esp_sec + offset

    최근 구간의 최솟값만 쓰는 이유: ESP32 와 Pi 시계는 아주 조금씩 속도가 달라서(drift)
    오래된 값까지 쓰면 오차가 쌓인다. 60초면 drift 는 1ms 미만이다.
    """

    def __init__(self, window_sec: float = 60.0):
        self.window_sec = window_sec
        self.prev_raw = None
        self.wraps = 0
        self.lags = deque()   # (host_ts, lag). lag 가 증가하는 순서로 유지 → 맨 앞이 최솟값

    def esp_seconds(self, raw_us: int):
        """
        local_timestamp(µs) → (esp_sec, reset 여부)
        reset=True 면 ESP32 가 재부팅되어 시계가 0 부터 다시 시작한 것 → 버퍼를 비워야 함
        """
        reset = False
        if self.prev_raw is not None and raw_us < self.prev_raw:
            if self.prev_raw >= 2 ** 31 and raw_us < 2 ** 31:
                self.wraps += 1               # 약 71.6분마다 생기는 정상적인 32비트 wrap
            else:
                self.wraps = 0                # 재부팅 → 처음부터 다시
                self.lags.clear()
                reset = True
        self.prev_raw = raw_us
        return (raw_us + self.wraps * 2 ** 32) / 1e6, reset

    def observe(self, host_ts: float, esp_sec: float):
        """패킷 하나를 받을 때마다 호출해서 offset 추정치를 갱신"""
        lag = host_ts - esp_sec
        while self.lags and self.lags[-1][1] >= lag:   # 새 값보다 큰 값은 앞으로 최솟값이 될 일 없음
            self.lags.pop()
        self.lags.append((host_ts, lag))
        while self.lags[0][0] < host_ts - self.window_sec:   # 오래된 값 제거
            self.lags.popleft()

    @property
    def offset(self) -> Optional[float]:
        return self.lags[0][1] if self.lags else None


def causal_times(local_us, host) -> Optional[np.ndarray]:
    """
    패킷을 도착 순서대로 OnlineClock 에 넣으면서 '그 순간의 offset'으로 시각을 매긴다.
    Pi(EdgeProcessor)가 실시간으로 하는 계산과 완전히 같다 → 학습/실시간 시각이 일치.
    ESP32 재부팅(시계 리셋)이 있으면 None.
    """
    clock = OnlineClock()
    t = np.empty(len(host))
    for i, (raw, h) in enumerate(zip(local_us, host)):
        e, reset = clock.esp_seconds(int(raw))
        if reset:
            return None
        clock.observe(float(h), e)
        t[i] = e + clock.offset
    return t


# ==========================================================
# 6. 판단 규칙 (여러 초의 예측을 묶어서 최종 결정)
# ==========================================================

def smooth_probabilities(prob_seq: np.ndarray, n: int) -> np.ndarray:
    """
    확률 시퀀스 (시간, 클래스)에 '과거 n개 평균'을 적용 (현재 시점까지만 사용 → 실시간에서도 그대로 가능).
    1초짜리 예측 하나가 튀어도 최종 판단이 흔들리지 않게 한다.
    """
    P = np.asarray(prob_seq, dtype=np.float64)
    cs = np.cumsum(P, axis=0)
    out = np.empty_like(P)
    for i in range(len(P)):
        lo = i - n
        out[i] = (cs[i] - (cs[lo] if lo >= 0 else 0)) / (i - max(lo, -1))
    return out


def apply_temperature(probs, T: float) -> np.ndarray:
    """
    확률 보정 (temperature scaling).
      SVM 이 내놓는 확률은 '실제로 맞을 확률'보다 과하게 확신하는 경향이 있다.
      p_보정 ∝ p ^ (1/T)  (T > 1 이면 확률이 고르게 퍼짐 = 확신을 낮춤, T = 1 이면 그대로)
    가장 높은 클래스는 바뀌지 않고 '얼마나 확신하는가'만 조정된다.
    T 값은 학습 코드가 세션 단위 교차 검증 결과로 정해서 .pkl 에 저장한다.
    """
    P = np.atleast_2d(np.asarray(probs, dtype=np.float64))
    logit = np.log(np.clip(P, 1e-6, 1.0)) / T
    logit -= logit.max(axis=1, keepdims=True)
    e = np.exp(logit)
    return e / e.sum(axis=1, keepdims=True)


def ood_score(X, mean, scale) -> np.ndarray:
    """
    '학습 데이터에서 얼마나 멀리 떨어진 입력인가' 점수.
      각 특성을 학습 데이터 기준으로 표준화(z = (x − 평균) / 표준편차)한 뒤 제곱 평균의 제곱근.
      학습 데이터와 비슷하면 1 근처, 처음 보는 환경(노드 이동, 가구 배치 변경 등)이면 크게 튄다.
    """
    Z = (np.atleast_2d(X) - np.asarray(mean)) / np.asarray(scale)
    return np.sqrt(np.mean(Z ** 2, axis=1))


def decide(prob_history, method: str = "mean"):
    """
    최근 몇 초의 확률들 → 최종 (클래스, 확률, 엔트로피)

    method
      "mean"        : 확률 평균 (기본값, 권장). 튀는 예측 하나에 덜 민감
      "min_entropy" : 가장 확신한(엔트로피 최소) 1개만 채택 (논문 5.1.3 방식, 비교용)
    """
    P = np.atleast_2d(np.asarray(prob_history, dtype=np.float64))
    if method == "mean":
        p = P.mean(axis=0)
    elif method == "min_entropy":
        p = P[int(np.argmin(entropy(P, base=2, axis=1)))]
    else:
        raise ValueError(f"unknown method: {method}")
    return int(np.argmax(p)), p, float(entropy(p, base=2))
