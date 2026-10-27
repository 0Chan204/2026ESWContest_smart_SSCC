# behavior_engine.py
"""
행동 판단 엔진 (분석 부분만, 통신과 분리) + 서버에 붙이는 러너
=============================================================

occupancy_engine.py 와 같은 모양: step(t_end, msgs) 를 1초마다 '빠짐없이 순서대로' 부르면 된다.
  입력 : t_end 와 그 시각의 노드별 Pi 메시지 {"r2": {...}, "r3": {...}, "r4": {...}}  (msg["behavior"] 를 사용)
  출력 : 노드마다 {"time", "node", "behavior", "behavior_confidence", "reason", "new"}

재실과 다른 점: 노드마다 '독립'으로 판단한다 (r2 의 낙상은 r2 의 데이터만으로).
  → 3개 노드가 다 모일 때까지 기다릴 필요 없이 그 노드 메시지가 오는 즉시 처리해도 됨 (통합 시 재사용)

판단 순서 (노드별)
  ① 문제 검사 (걸리면 unknown + reason)
       warming_up       시작 직후, 또는 Pi 가 6초 윈도우를 아직 못 채움
       node_offline     그 노드 메시지가 3초 이상 안 옴
       config_mismatch  Pi 의 행동 설정 지문이 모델과 다름
       behavior_off     Pi 가 행동 특성을 안 보냄 (behavior_config.json 없음)
       poor_signal      Pi 가 gap/no_csi 보고, 또는 수신 속도 < min_rate_hz
       low_confidence   모델이 확신 못함 / 학습 범위 이탈
  ② 확률 계산: SVM → 온도 보정 → 노드 제약 (r2·r4 는 눕기/기상 확률을 none 으로 합침)
  ③ 이벤트 발화: 가장 높은 클래스가 이벤트이고 신뢰도 ≥ θ(클래스별)가 confirm_k 번 연속이면 발화
  ④ 유지(hold): 발화한 이벤트는 hold_sec 동안 그대로 내보낸다 (이벤트는 몇 초짜리 순간 동작이고,
       6초 윈도우를 1초씩 밀기 때문에 같은 이벤트가 4~5번 연속 잡힌다 → 한 번만 알리고 유지).
       낙상은 다른 이벤트 유지 중에도 덮어쓴다. 유지가 끝난 뒤 refractory_sec 동안 같은 이벤트 재발화 금지.
  ⑤ 이벤트가 아니면: none 확률 ≥ none_min_conf 이면 none, 아니면 unknown(low_confidence)

신뢰도(behavior_confidence): 보정된 확률. 이벤트는 '발화 순간'의 값, none 은 이번 윈도우의 none 확률, unknown 은 null.
"""

import csv
import os
from datetime import datetime

import joblib
import numpy as np

from behavior_pipeline import LABELS, NODE_CLASSES, NODES, FEATURE_NAMES, NUM_FEATURES
from wifi_occupancy_pipeline import apply_temperature, ood_score

NONE_IDX = LABELS.index("none")
DEFAULT_CONFIRM = {"fall": 1, "lie_down": 2, "get_up": 2}     # 몇 번 연속 잡혀야 발화
DEFAULT_HOLD = {"fall": 10.0, "lie_down": 5.0, "get_up": 5.0}  # 발화 후 유지 시간(초)


class BehaviorEngine:
    def __init__(self, model_path: str, nodes=None, theta: dict = None, confirm_k: dict = None,
                 hold_sec: dict = None, refractory_sec: float = 4.0, none_min_conf: float = 0.5,
                 offline_sec: int = 3, min_rate_hz: float = 10.0, use_ood: bool = True,
                 settle_sec: int = 8, log=print):
        b = joblib.load(model_path)
        self.model = b["model"]
        self.labels = list(b["labels"])
        if self.labels != LABELS:
            raise ValueError("모델의 클래스 목록이 현재 코드와 다릅니다. 같은 버전의 코드로 다시 학습하세요.")
        if list(b.get("feature_names", FEATURE_NAMES)) != FEATURE_NAMES or b.get("feature_dim") != NUM_FEATURES:
            raise ValueError("모델의 특성 목록이 현재 코드와 다릅니다. 같은 버전의 코드로 다시 학습하세요.")
        self.cfg_hash = b["cfg_hash"]
        self.T = float(b.get("calibration", {}).get("T", 1.0))
        self.theta = {**b.get("theta", {}), **(theta or {})}
        for lb in LABELS[1:]:
            self.theta.setdefault(lb, 0.9)
        self.confirm_k = {**DEFAULT_CONFIRM, **(confirm_k or {})}
        self.hold_sec = {**DEFAULT_HOLD, **(hold_sec or {})}
        self.refractory_sec, self.none_min_conf = refractory_sec, none_min_conf
        self.offline_sec, self.min_rate_hz = offline_sec, min_rate_hz
        # 노드가 (재)시작하거나 끊겼다 돌아온 직후 이만큼은 판단을 보류한다.
        #  이유: 직후 윈도우에 시작 구간의 시계 보정 흔들림이 섞여 가짜 이벤트가 나온 적이 있음(통합 테스트)
        self.settle_sec = int(settle_sec)
        self.train_rate = b.get("train_rate_hz")
        ood = b.get("ood") if use_ood else None
        self.ood = None if ood is None else {"mean": np.asarray(ood["mean"]), "scale": np.asarray(ood["scale"]),
                                             "threshold": float(ood["threshold"])}
        self.class_idx = [int(c) for c in self.model.classes_]

        self.nodes = list(nodes or NODES)
        nc = b.get("node_classes") or NODE_CLASSES
        # 노드가 낼 수 없는 클래스의 인덱스 (그 확률은 none 으로 합친다)
        self.masked = {n: [i for i, lb in enumerate(LABELS) if lb not in nc.get(n, LABELS)] for n in self.nodes}

        self.first_t = None
        self.st = {n: {"last_msg_t": None, "cand": None, "streak": 0, "event": None, "event_conf": None,
                       "hold_until": 0.0, "refractory": {}, "ok_streak": 0} for n in self.nodes}
        log(f"[행동 엔진] 모델 로드: {model_path} | 노드 {self.nodes} | T={self.T:.2f} | θ={self.theta} | "
            f"유지 {self.hold_sec} | 연속 {self.confirm_k} | 학습 범위 검사 {'켬' if self.ood else '끔'} | cfg {self.cfg_hash}")
        log("  노드별 허용 행동: " + ", ".join(f"{n}={[LABELS[i] for i in range(len(LABELS)) if i not in self.masked[n]]}"
                                         for n in self.nodes))

    # ------------------------------------------------------
    def _probs(self, node, x):
        raw = self.model.predict_proba(x.reshape(1, -1))[0]
        p = np.zeros(len(LABELS))
        p[self.class_idx] = raw
        pc = apply_temperature(p, self.T)[0]
        for i in self.masked[node]:        # 그 노드에서 일어날 수 없는 이벤트 → '이벤트 아님'으로
            pc[NONE_IDX] += pc[i]
            pc[i] = 0.0
        return pc

    def _step_node(self, node, t_end, m):
        s = self.st[node]
        dbg = {"status": None, "rate_hz": None, "probs": None, "ood_score": None, "rate_warn": False}
        problem, p = None, None

        if m is None:                                    # 이번 초에 메시지가 안 옴
            lm = s["last_msg_t"]
            if lm is None:
                problem = "warming_up" if t_end - self.first_t < self.offline_sec else "node_offline"
            elif t_end - lm >= self.offline_sec:
                problem = "node_offline"
            else:
                problem = "poor_signal"
        else:
            s["last_msg_t"] = t_end
            b = m.get("behavior")
            if b is None:
                problem = "behavior_off"
            else:
                dbg["status"], dbg["rate_hz"] = b.get("status"), b.get("rate_hz")
                f = b.get("features")
                rate = b.get("rate_hz")
                if b.get("cfg") != self.cfg_hash:
                    problem = "config_mismatch"
                elif b.get("status") == "warming_up":
                    problem = "warming_up"
                elif b.get("status") != "ok" or f is None or len(f) != NUM_FEATURES:
                    problem = "poor_signal"
                elif rate is not None and rate < self.min_rate_hz:
                    problem = "poor_signal"
                else:
                    x = np.asarray(f, dtype=np.float64)
                    p = self._probs(node, x)
                    dbg["probs"] = {lb: round(float(v), 4) for lb, v in zip(LABELS, p)}
                    if self.ood is not None:
                        sc = float(ood_score(x, self.ood["mean"], self.ood["scale"])[0])
                        dbg["ood_score"] = sc
                        if sc > self.ood["threshold"]:
                            problem = "low_confidence"
                    if self.train_rate and rate and abs(rate - self.train_rate) / self.train_rate > 0.4:
                        dbg["rate_warn"] = True          # 학습 때 수신 속도와 많이 다름 (참고용)

        # ---- 시작 직후 안정화 (데이터 문제가 없던 초가 settle_sec 번 이어질 때까지 보류) ----
        if problem in (None, "low_confidence"):
            s["ok_streak"] += 1
            if problem is None and s["ok_streak"] <= self.settle_sec:
                problem = "warming_up"
        else:
            s["ok_streak"] = 0

        # ---- 이벤트 발화 ----
        fired = None
        if problem is None:
            top = int(np.argmax(p))
            lb = LABELS[top]
            cand = lb if (lb != "none" and p[top] >= self.theta[lb]) else None
            if cand is not None and cand == s["cand"]:
                s["streak"] += 1
            else:
                s["cand"], s["streak"] = cand, (1 if cand else 0)
            if cand and s["streak"] >= self.confirm_k[cand] and t_end >= s["refractory"].get(cand, 0.0):
                holding = s["event"] is not None and t_end < s["hold_until"]
                if (not holding) or (cand == "fall" and s["event"] != "fall"):
                    s["event"], s["event_conf"] = cand, float(p[top])
                    s["hold_until"] = t_end + self.hold_sec[cand]
                    s["refractory"][cand] = s["hold_until"] + self.refractory_sec
                    fired = cand
        else:
            s["cand"], s["streak"] = None, 0

        # ---- 출력 ----
        out = {"time": datetime.fromtimestamp(t_end).astimezone().isoformat(timespec="seconds"), "node": node}
        if s["event"] is not None and t_end < s["hold_until"]:
            out.update(behavior=s["event"], behavior_confidence=round(s["event_conf"], 3), reason=None)
        else:
            s["event"] = None
            if problem is not None:
                out.update(behavior="unknown", behavior_confidence=None, reason=problem)
            elif p[NONE_IDX] >= self.none_min_conf:
                out.update(behavior="none", behavior_confidence=round(float(p[NONE_IDX]), 3), reason=None)
            else:
                out.update(behavior="unknown", behavior_confidence=None, reason="low_confidence")
        out["new"] = fired is not None          # 이번 초에 새로 발화했는가 (알림은 이 값이 True 일 때 한 번만)
        return out, dbg

    def step(self, t_end: int, msgs: dict) -> dict:
        """반환: {"outputs": {노드: 출력 dict}, "debug": {노드: 로그용 dict}}"""
        if self.first_t is None:
            self.first_t = t_end
        outs, dbgs = {}, {}
        for node in self.nodes:
            outs[node], dbgs[node] = self._step_node(node, t_end, msgs.get(node))
        return {"outputs": outs, "debug": dbgs}


# ==========================================================
# 서버에 붙이는 러너: 엔진 결과를 MQTT 로 발행 + CSV 로그 + 콘솔
# ==========================================================
class BehaviorRunner:
    """
    occupancy_server.py 의 루프에서 매 t_end 마다 step(t_end, msgs) 만 부르면 된다.
    발행 주제: <prefix>/state/<node>  (retain=True → 새로 구독해도 최신 결과를 바로 받음)
    """

    def __init__(self, engine: BehaviorEngine, link, prefix: str = "wifi/behavior", log_dir: str = "logs"):
        self.engine, self.link, self.prefix = engine, link, prefix.rstrip("/")
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, f"behavior_{datetime.now():%Y%m%d_%H%M%S}.csv")
        self._f = open(self.log_path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(["time", "node", "behavior", "behavior_confidence", "reason", "new"]
                         + [f"p_{lb}" for lb in LABELS] + ["ood_score", "status", "rate_hz", "rate_warn"])
        self._last_printed = {}
        print(f"행동 추론: 발행 {self.prefix}/state/<노드> | 로그 {self.log_path}")

    def topic(self, node):
        return f"{self.prefix}/state/{node}"

    def step(self, t_end, msgs):
        res = self.engine.step(t_end, msgs)
        for node, o in res["outputs"].items():
            d = res["debug"][node]
            self.link.publish(self.topic(node), o, retain=True)
            probs = d["probs"] or {}
            self._w.writerow([o["time"], node, o["behavior"], o["behavior_confidence"], o["reason"] or "", int(o["new"])]
                             + [probs.get(lb, "") for lb in LABELS]
                             + ["" if d["ood_score"] is None else round(d["ood_score"], 3),
                                d["status"] or "", d["rate_hz"] if d["rate_hz"] is not None else "", int(d["rate_warn"])])
            key = (o["behavior"], o["reason"])
            if o["new"] or self._last_printed.get(node) != key:      # 바뀔 때만 콘솔에 (매초 찍으면 재실 출력이 묻힘)
                self._last_printed[node] = key
                conf = f"{o['behavior_confidence']:.2f}" if o["behavior_confidence"] is not None else " - "
                tag = "  ★ 새 이벤트" if o["new"] else ""
                why = f" ({o['reason']})" if o["reason"] else ""
                print(f"{o['time'][11:19]}  [행동 {node}] {o['behavior']:<9} {conf}{why}{tag}")
        self._f.flush()
        return res

    def close(self):
        self._f.close()
