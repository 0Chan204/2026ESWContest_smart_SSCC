# occupancy_engine.py
"""
재실 판단 엔진 (분석 부분만, 통신과 분리)
=========================================

입력 : 시각 t_end 와 그 시각의 노드별 메시지 {"r2": {...}, "r3": {...}, "r4": {...}}
출력 : {"time": ..., "location": ..., "location_confidence": ..., ("reason": ...)}

통신(MQTT 등)과 분리해 둔 이유
  지금은 맥북의 occupancy_server.py 가 이 클래스를 쓰지만,
  나중에 통합 서버로 옮길 때는 이 파일 + .pkl 만 가져가서 똑같이 step() 을 부르면 된다.

판단 순서 (위에서 걸리면 바로 location = "unknown")
  ① warming_up       시작 직후, 또는 최근 5초 확률이 3개 미만 (평활화할 재료 부족)
  ② node_offline     어떤 노드든 3초 이상 메시지가 안 옴
  ③ config_mismatch  Pi 의 전처리 지문(cfg)이 모델과 다름
     poor_signal      Pi 가 데이터 불량을 보고(gap/no_csi) 했거나 수신 속도가 fs×0.7 미만
  ④ low_confidence   최근 5초 평균 확률의 최댓값 < θ, 또는 입력이 학습 범위를 크게 벗어남
  ⑤ 결과 확정        다른 장소로 바꿀 때는 그 장소가 2초 연속 이겨야 바꿈 (깜빡임 방지)
                     기다리는 동안 기존 장소의 신뢰도가 θ 미만이면 그 1초는 unknown(low_confidence)
                     → 출력된 장소는 항상 신뢰도 ≥ θ 가 보장됨

신뢰도(location_confidence)
  = 보정된 확률을 최근 5초 평균한 값 중 '출력한 장소'의 값 (0~1)
  θ 는 학습 때 "신뢰도 ≥ θ 인 결과의 정확도가 90% 이상"이 되도록 고른 값.
"""

import math
from collections import deque
from datetime import datetime

import joblib
import numpy as np

from wifi_occupancy_pipeline import (
    FEATURE_NAMES, NUM_FEATURES, apply_temperature, config_from_dict, make_config_hash, ood_score,
)

# reason 우선순위 (숫자가 작을수록 먼저 보고)
_PRIORITY = {"warming_up": 0, "node_offline": 1, "config_mismatch": 2, "poor_signal": 3}


class OccupancyEngine:
    def __init__(self, model_path: str, theta: float = None, switch_k: int = 2,
                 carry_sec: int = 2, offline_sec: int = 3, min_rate_ratio: float = 0.7,
                 use_ood: bool = True, log=print):
        """
        model_path    : 학습으로 만든 .pkl
        theta         : 판단 불가 임계값. None 이면 .pkl 에 저장된 값 사용
        switch_k      : 장소를 바꾸려면 새 장소가 몇 초 연속 이겨야 하는지
        carry_sec     : 노드 메시지가 잠깐 빠졌을 때 직전 특성을 재사용해 버티는 최대 시간
        offline_sec   : 이 시간 이상 메시지가 없으면 node_offline
        min_rate_ratio: 수신 속도가 fs × 이 값보다 낮으면 poor_signal
        use_ood       : 학습 범위 검사 사용 여부
        """
        b = joblib.load(model_path)
        self.model = b["model"]
        self.labels = list(b["labels"])                       # ["empty", "room", "kitchen", "toilet"]
        self.locs = list(b["location_codes"])                 # ["r2", "r3", "r4"]
        self.cfg = config_from_dict(b["processing_config"])
        self.cfg_hash = b.get("cfg_hash") or make_config_hash(self.cfg)
        self.smooth_n = int(b.get("smooth_n", 5))
        self.min_hist = max(1, math.ceil(self.smooth_n * 0.6))   # 5초 중 최소 3개는 있어야 판단
        self.T = float(b.get("calibration", {}).get("T", 1.0))
        self.theta = float(theta if theta is not None else b.get("theta", 0.6))
        ood = b.get("ood") if use_ood else None
        self.ood = None if ood is None else {
            "mean": np.asarray(ood["mean"]), "scale": np.asarray(ood["scale"]),
            "threshold": float(ood["threshold"])}
        self.switch_k, self.carry_sec, self.offline_sec = switch_k, carry_sec, offline_sec
        self.min_rate = self.cfg.fs * min_rate_ratio

        # 모델이 기대하는 특성 순서 확인: r2 의 19개 → r3 의 19개 → r4 의 19개
        expected = [f"{loc}__{n}" for loc in self.locs for n in FEATURE_NAMES]
        if list(b.get("feature_columns", expected)) != expected:
            raise ValueError("모델의 특성 순서가 현재 코드와 다릅니다. 같은 버전의 코드로 다시 학습하세요.")
        # 모델이 어떤 클래스 번호를 출력하는지 (학습 때 특정 클래스가 없었을 수도 있으므로)
        self.class_idx = [int(c) for c in self.model.classes_]

        if "calibration" not in b:
            log("[주의] 예전 형식의 .pkl 입니다 (보정/θ/학습 범위 없음). "
                "train_multizone_model.py 로 다시 학습하는 것을 권장합니다.")
        log(f"[엔진] 모델 로드: {model_path} | 클래스 {self.labels} | 노드 {self.locs} | "
            f"T={self.T:.2f} θ={self.theta:.2f} | 학습 범위 검사 {'켬' if self.ood else '끔'} | "
            f"cfg {self.cfg_hash}")

        # ---- 상태 ----
        self.first_t = None
        self.last_msg_t = {}      # 노드별 마지막으로 메시지를 받은 t_end
        self.last_ok = {}         # 노드별 마지막 정상 특성 (t_end, np.array)
        self.node_view = {}       # 노드별 최근 상태 (출력/로그용)
        self.hist = deque()       # (t_end, 보정 확률(4,), 학습범위밖 여부, 점수)
        self.current = None       # 현재 확정된 장소
        self.cand, self.cand_streak = None, 0

    # ------------------------------------------------------
    def _check_nodes(self, t_end, msgs):
        """노드별 메시지를 검사해서 (특성 57개 또는 None, 문제 목록) 반환"""
        feats, problems = [], []
        for node in self.locs:
            m = msgs.get(node)
            if m is not None:
                self.last_msg_t[node] = t_end
                q = m.get("quality") or {}
                self.node_view[node] = {"status": m.get("status"), "rate_hz": q.get("rate_hz"),
                                        "proc_ms": q.get("proc_ms")}
                f = m.get("features")
                if m.get("cfg") != self.cfg_hash:
                    problems.append(("config_mismatch", node))
                elif m.get("status") == "warming_up":
                    problems.append(("warming_up", node))
                elif m.get("status") != "ok" or f is None or len(f) != NUM_FEATURES:
                    problems.append(("poor_signal", node))           # gap / no_csi
                elif q.get("rate_hz") is not None and q["rate_hz"] < self.min_rate:
                    problems.append(("poor_signal", node))           # 패킷이 너무 적게 들어옴
                else:
                    arr = np.asarray(f, dtype=np.float64)
                    self.last_ok[node] = (t_end, arr)
                    feats.append(arr)
                continue

            # 메시지가 안 옴: 잠깐(≤ carry_sec)이면 직전 정상 특성으로 버팀
            self.node_view[node] = {"status": "missing", "rate_hz": None, "proc_ms": None}
            lo = self.last_ok.get(node)
            if lo is not None and t_end - lo[0] <= self.carry_sec:
                feats.append(lo[1])
                continue
            lm = self.last_msg_t.get(node)
            if lm is None and t_end - self.first_t < self.offline_sec:
                problems.append(("warming_up", node))                # 서버 막 켜짐
            elif lm is None or t_end - lm >= self.offline_sec:
                problems.append(("node_offline", node))
            else:
                problems.append(("poor_signal", node))
        return (np.concatenate(feats) if not problems else None), problems

    @staticmethod
    def _reason_text(problems):
        """가장 우선순위가 높은 문제 하나를 'node_offline:r3,r4' 형태로"""
        top = min(problems, key=lambda p: _PRIORITY[p[0]])[0]
        nodes = sorted({n for r, n in problems if r == top})
        return f"{top}:{','.join(nodes)}"

    def _unknown(self, out, reason):
        out.update(location="unknown", location_confidence=None, reason=reason)
        self.current, self.cand, self.cand_streak = None, None, 0
        return out

    # ------------------------------------------------------
    def step(self, t_end: int, msgs: dict) -> dict:
        """
        t_end 의 결과를 계산. 서버는 1초마다 '빠짐없이 순서대로' 호출해야 한다
        (메시지가 하나도 안 온 초도 msgs={} 로 호출 → 그래야 node_offline 을 알 수 있음).
        반환: {"output": 출력용 dict, "debug": 로그용 dict}
        """
        if self.first_t is None:
            self.first_t = t_end
        out = {"time": datetime.fromtimestamp(t_end).astimezone().isoformat(timespec="seconds")}
        debug = {"t_end": t_end, "probs": None, "ood_score": None, "nodes": None}

        # ①~③ 데이터 검사
        x, problems = self._check_nodes(t_end, msgs)
        debug["nodes"] = {n: dict(v) for n, v in self.node_view.items()}

        # 최근 smooth_n 초 밖의 확률은 버림 (시간 기준이라 빠진 초가 있어도 올바르게 동작)
        while self.hist and self.hist[0][0] <= t_end - self.smooth_n:
            self.hist.popleft()

        if problems:
            return {"output": self._unknown(out, self._reason_text(problems)), "debug": debug}

        # 모델 → 4클래스 확률 → 보정
        raw = self.model.predict_proba(x.reshape(1, -1))[0]
        p = np.zeros(len(self.labels))
        p[self.class_idx] = raw
        p_cal = apply_temperature(p, self.T)[0]
        score = float(ood_score(x, self.ood["mean"], self.ood["scale"])[0]) if self.ood else None
        is_ood = bool(self.ood and score > self.ood["threshold"])
        self.hist.append((t_end, p_cal, is_ood, score))
        debug["ood_score"] = score

        # ④ 최근 5초 평균
        if len(self.hist) < self.min_hist:
            return {"output": self._unknown(out, "warming_up"), "debug": debug}
        p_bar = np.mean([h[1] for h in self.hist], axis=0)
        debug["probs"] = {lb: round(float(v), 4) for lb, v in zip(self.labels, p_bar)}
        ood_frac = np.mean([h[2] for h in self.hist])
        top = int(np.argmax(p_bar))
        if p_bar[top] < self.theta or ood_frac > 0.5:
            return {"output": self._unknown(out, "low_confidence"), "debug": debug}

        # ⑤ 장소 전환 확인 (깜빡임 방지)
        label = self.labels[top]
        if self.current is None or label == self.current:
            self.current, self.cand, self.cand_streak = label, None, 0
        else:
            self.cand_streak = self.cand_streak + 1 if self.cand == label else 1
            self.cand = label
            if self.cand_streak >= self.switch_k:
                self.current, self.cand, self.cand_streak = label, None, 0
        # 전환 확인 중에는 기존 장소를 유지한다. 단, 기존 장소의 신뢰도가 이미 θ 아래로 떨어졌으면
        # '확실하지 않은 장소'를 내보내지 않고 unknown 으로 둔다 (전환 대기 상태는 그대로 유지).
        conf = float(p_bar[self.labels.index(self.current)])
        if conf < self.theta:
            out.update(location="unknown", location_confidence=None, reason="low_confidence")
        else:
            out.update(location=self.current, location_confidence=round(conf, 3))
        return {"output": out, "debug": debug}
