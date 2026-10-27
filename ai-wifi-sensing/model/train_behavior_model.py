# train_behavior_model.py
"""
행동 추론 모델 학습 (낙상 / 눕기 / 기상 / none)  → behavior_svm.pkl, behavior_config.json
==========================================================================================

입력
  --events-dir   이벤트 CSV 폴더. 아래처럼 클래스 이름의 하위 폴더에 CSV 를 넣는다 (CSV 1개 = 이벤트 1개)
                   dataset_behavior/fall/*.csv
                   dataset_behavior/lie_down/*.csv
                   dataset_behavior/get_up/*.csv
  --none         'none'(아무 일 없음)으로 쓸 재실 CSV 들 (폴더 또는 글롭, 여러 개 가능)
                   예) --none dataset/empty dataset/room dataset/kitchen dataset/toilet

이벤트 파일에서 윈도우(6초)를 라벨링하는 방법  (이벤트 시작 시점이 제각각이라 자동으로 찾는다)
  1) 파일에서 움직임 에너지가 가장 큰 곳 = 이벤트 중심 c
  2) 윈도우 끝 E 에 대해
       E-5 ≤ c ≤ E-1            → 그 이벤트 클래스 (이벤트가 윈도우 안에 통째로 들어옴)
       c < E-8  또는  c > E+2    → none (이벤트와 무관한 조용한 구간)
       그 외                     → 버림 (이벤트가 윈도우 가장자리에 걸쳐 애매함)

'none' 데이터: 재실 세션(26Hz)을 그대로 쓰면 이벤트 데이터(16Hz)와 속도가 달라 특성 분포가 어긋난다.
  → 이벤트 파일의 수신 속도 중앙값에 맞춰 패킷을 무작위로 솎은 복사본을 함께 학습한다 (--thin-none auto).

평가: 파일 단위(또는 날짜 단위) 교차 검증. 같은 파일의 윈도우는 학습·시험에 나뉘어 들어가지 않는다.
"""

import argparse
import warnings
import glob
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GridSearchCV, GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from behavior_pipeline import (
    EVENT_LABELS, FEATURE_NAMES, LABELS, NODE_CLASSES, BehaviorConfig, BehaviorProcessor,
    PIPELINE_VERSION, load_behavior_csv, make_behavior_hash,
)
from wifi_occupancy_pipeline import apply_temperature, ood_score

NONE_IDX = LABELS.index("none")
warnings.filterwarnings("ignore", message=".*probability.*deprecated.*", category=FutureWarning)


def parse_args():
    p = argparse.ArgumentParser(description="행동 추론 SVM 학습")
    p.add_argument("--events-dir", default="dataset_behavior")
    p.add_argument("--none", nargs="+", required=True, help="none 으로 쓸 재실 CSV 폴더/글롭 (여러 개)")
    p.add_argument("--out", default="behavior_svm.pkl")
    p.add_argument("--edge-out", default="behavior_config.json", help="Pi 용 설정 파일")
    p.add_argument("--stride", type=float, default=0.25, help="이벤트 파일 윈도우 간격(초)")
    p.add_argument("--none-stride", type=float, default=2.0, help="재실(none) 파일 윈도우 간격(초)")
    p.add_argument("--thin-none", default="auto", help="auto = 이벤트 파일 속도에 맞춘 복사본 추가 / off / 숫자(Hz)")
    p.add_argument("--max-none", type=int, default=4000, help="none 윈도우 최대 개수(넘으면 무작위 추림)")
    p.add_argument("--group-by", choices=["file", "day"], default="file",
                   help="교차 검증 단위. day = 파일 이름의 YYYYMMDD 로 묶어 '다른 날' 성능을 잼")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--target-precision", type=float, default=0.90, help="눕기/기상 임계값 기준 정밀도")
    p.add_argument("--fall-precision", type=float, default=0.80,
                   help="낙상 임계값 기준 정밀도 (놓치면 위험하니 더 낮게 = 더 민감하게)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--diag", action="store_true", help="이벤트 파일별 진단표(중심 위치, 피크 대비, 라벨 윈도우 수, 신호 크기) 출력")
    return p.parse_args()


def list_csvs(spec):
    p = Path(spec)
    files = sorted(str(x) for x in p.rglob("*.csv")) if p.is_dir() else sorted(glob.glob(spec, recursive=True))
    # 같은 이름의 잘라낸 파일(X.csv)과 앞뒤 여유가 붙은 raw 파일(X.raw.csv)이 같이 있으면 raw 만 쓴다 (중복 방지)
    raws = {f[:-len(".raw.csv")] for f in files if f.endswith(".raw.csv")}
    kept = [f for f in files if f.endswith(".raw.csv") or f[:-len(".csv")] not in raws]
    if len(kept) < len(files):
        print(f"  [알림] {spec}: 같은 이름의 .raw.csv 가 있는 {len(files) - len(kept)}개는 raw 쪽만 사용")
    return kept


def day_of(path):
    m = re.search(r"(20\d{6})", os.path.basename(path))
    return m.group(1) if m else None


def main():
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    cfg = BehaviorConfig()
    proc = BehaviorProcessor(cfg)
    cfg_hash = make_behavior_hash(cfg)
    print(f"행동 전처리 설정 지문 {cfg_hash} | fs {cfg.fs:g}Hz | 윈도우 {cfg.window_sec:g}초 | 특성 {len(FEATURE_NAMES)}개")

    # ---------------- 1) 이벤트 파일 ----------------
    X, y, grp, src, fid = [], [], [], [], []
    ev_info = []           # (파일, 클래스, 속도, 길이, 중심 위치)
    ev_rates, ev_amp, diag_rows = [], [], []
    n_files = Counter()
    skipped = []
    for lb in EVENT_LABELS:
        files = list_csvs(os.path.join(args.events_dir, lb))
        if not files:
            sys.exit(f"[오류] {args.events_dir}/{lb}/ 에 CSV 가 없습니다.")
        for f in files:
            t, amp, rssi, info = load_behavior_csv(f)
            ei = proc.event_info(t, amp, rssi)
            c, dur = (None, 0.0) if ei is None else (ei["center"], ei["dur"])
            if c is None or dur < cfg.window_sec + 1.0:
                skipped.append((f, f"길이 {dur:.1f}초 (윈도우 {cfg.window_sec:g}초 + 여유 1초 필요)"))
                continue
            feats, ends = proc.process_stream(t, amp, rssi, stride_sec=args.stride)
            E = ends / cfg.fs
            lab = np.full(len(E), -1)
            lab[(c >= E - 5.0) & (c <= E - 1.0)] = LABELS.index(lb)
            lab[(c < E - 8.0) | (c > E + 2.0)] = NONE_IDX
            keep = lab >= 0
            n_ev = int((lab == LABELS.index(lb)).sum())
            diag_rows.append((lb, os.path.basename(f), dur, ei["center_rel"], ei["peak_ratio"], n_ev, info["amp_mean"]))
            if n_ev == 0:
                skipped.append((f, f"이벤트로 라벨된 윈도우가 없음 (중심 {ei['center_rel']:.1f}초 / 길이 {dur:.1f}초 — 이벤트가 파일 가장자리?)"))
                continue
            X.append(feats[keep]); y.append(lab[keep])
            g = day_of(f) if args.group_by == "day" else f
            grp += [g or f] * int(keep.sum())
            src += [lb] * int(keep.sum())
            fid += [f] * int(keep.sum())
            ev_rates.append(info["rate_hz"])
            ev_amp.append(info["amp_mean"])
            ev_info.append((f, lb, info["rate_hz"], dur, c - (t[0] if t[0] > 1e8 else 0)))
            n_files[lb] += 1
    for f, why in skipped:
        print(f"  [건너뜀] {os.path.basename(f)}: {why}")
    if args.diag:
        print("\n[진단] 이벤트 파일별  (피크비 = 에너지 피크 ÷ 중앙값. 1.8 미만이면 이벤트가 에너지로 안 보임)")
        print(f"  {'클래스':9s}{'파일':28s}{'길이':>6s}{'중심':>6s}{'피크비':>7s}{'라벨':>5s}{'진폭':>6s}")
        for lb_, nm, du, ce, pr, ne, am in diag_rows:
            flag = "  ← 이벤트 불분명" if pr < 1.8 else ("  ← 라벨 윈도우 부족" if ne < 4 else "")
            print(f"  {lb_:9s}{nm[:27]:28s}{du:6.1f}{ce:6.1f}{pr:7.2f}{ne:5d}{am:6.1f}{flag}")
    ev_rate = float(np.median(ev_rates)) if ev_rates else 16.0
    print(f"\n이벤트 파일: " + ", ".join(f"{lb} {n_files[lb]}개" for lb in EVENT_LABELS)
          + f" | 수신 속도 중앙값 {ev_rate:.1f}Hz (범위 {min(ev_rates):.1f}~{max(ev_rates):.1f})")
    for lb in EVENT_LABELS:
        if n_files[lb] < 20:
            print(f"  [주의] {lb} 파일이 {n_files[lb]}개뿐입니다. 최소 30개, 권장 50개 (3일 이상 분산).")

    # ---------------- 2) none: 재실 CSV ----------------
    none_files = sorted({f for s in args.none for f in list_csvs(s)})
    if not none_files:
        sys.exit("[오류] --none 에서 CSV 를 찾지 못했습니다.")
    thin_hz = None if args.thin_none == "off" else (ev_rate if args.thin_none == "auto" else float(args.thin_none))
    Xn, gn = [], []
    n_thin = 0
    none_amp = []
    for f in none_files:
        variants = [None]
        t0, a0, r0, i0 = load_behavior_csv(f)
        none_amp.append(i0["amp_mean"])
        if thin_hz and i0["rate_hz"] > thin_hz * 1.15:
            variants.append(thin_hz)
        for th in variants:
            if th is None:
                t, amp, rssi = t0, a0, r0
            else:
                t, amp, rssi, _ = load_behavior_csv(f, thin_to_hz=th, rng=rng)
                n_thin += 1
            feats, _ = proc.process_stream(t, amp, rssi, stride_sec=args.none_stride)
            if len(feats):
                Xn.append(feats)
                gn += [(day_of(f) if args.group_by == "day" else f) or f] * len(feats)
    Xn = np.vstack(Xn)
    gn = np.asarray(gn)
    if len(Xn) > args.max_none:
        sel = rng.choice(len(Xn), args.max_none, replace=False)
        Xn, gn = Xn[sel], gn[sel]
    print(f"none(재실 CSV) {len(none_files)}개 파일 → 윈도우 {len(Xn)}개 (솎은 복사본 {n_thin}개 포함, 목표 {thin_hz and round(thin_hz, 1)}Hz)")

    # ---- 신호 크기 점검: 이벤트와 none 이 다른 환경에서 수집됐는지 ----
    ea, na = float(np.median(ev_amp)), float(np.median(none_amp))
    print(f"신호 크기(평균 진폭, 중앙값): 이벤트 파일 {ea:.1f} (범위 {min(ev_amp):.1f}~{max(ev_amp):.1f}) | none 파일 {na:.1f}")
    if max(ea, na) / max(min(ea, na), 1e-6) > 2.0:
        print("  [경고] 이벤트와 none 의 신호 크기가 2배 넘게 다릅니다. 수집 장비/위치/AP 가 달랐던 것으로 보입니다.\n"
              "         이대로면 모델이 '움직임'이 아니라 '신호 크기·잡음 수준' 차이로 이벤트/none 을 가를 수 있어서\n"
              "         교차 검증 점수가 부풀려지고 실제 Pi 에서는 동작하지 않을 수 있습니다.\n"
              "         → none 을 이벤트 수집과 같은 장비·배치로 새로 수집하세요 (아무 일 없는 상태 5~10분).")
    if ea < 4.0:
        print(f"  [주의] 이벤트 파일 평균 진폭이 {ea:.1f} 로 작습니다 (CSI 정수값이 0~몇 정도 → 양자화 잡음이 큼).")

    X = np.vstack(X + [Xn])
    y = np.concatenate(y + [np.full(len(Xn), NONE_IDX)])
    grp = np.asarray(grp + list(gn))
    src = np.asarray(src + ["occ"] * len(Xn))
    fid = np.asarray(fid + [""] * len(Xn))
    print("학습 윈도우: " + ", ".join(f"{lb} {(y == i).sum()}" for i, lb in enumerate(LABELS)))
    missing = [lb for i, lb in enumerate(LABELS) if not (y == i).any()]
    if missing:
        sys.exit(f"[오류] 윈도우가 없는 클래스: {missing}")
    n_groups = len(set(grp))
    folds = min(args.folds, n_groups)
    if folds < 3:
        sys.exit(f"[오류] 교차 검증 단위가 {n_groups}개뿐입니다. 파일(또는 날짜)을 더 모으세요.")
    if args.group_by == "day" and n_groups < 3:
        print("[주의] 날짜가 3일 미만이라 day 단위 평가는 신뢰하기 어렵습니다.")
    splits = list(GroupKFold(n_splits=folds).split(X, y, grp))
    print(f"교차 검증: {args.group_by} 단위 {folds}-fold ({n_groups}개 묶음)")

    # ---------------- 3) 모델 선택 ----------------
    base = Pipeline([("sc", StandardScaler()),
                     ("svm", SVC(kernel="rbf", class_weight="balanced", random_state=args.seed))])
    grid = {"svm__C": [1, 3, 10, 30], "svm__gamma": ["scale", 0.003, 0.01, 0.03]}
    gs = GridSearchCV(base, grid, cv=splits, scoring="f1_macro", n_jobs=-1)
    gs.fit(X, y)
    best = {k.split("__")[1]: v for k, v in gs.best_params_.items()}
    print(f"\n최적 하이퍼파라미터 {best} (교차 검증 macro F1 {gs.best_score_:.3f})")

    final = Pipeline([("sc", StandardScaler()),
                      ("svm", SVC(kernel="rbf", class_weight="balanced", probability=True,
                                  random_state=args.seed, **best))])
    P = cross_val_predict(clone(final), X, y, cv=splits, method="predict_proba", n_jobs=-1)

    # ---------------- 4) 확률 보정 (temperature) ----------------
    def nll(T):
        Pc = apply_temperature(P, T)
        return -np.mean(np.log(np.clip(Pc[np.arange(len(y)), y], 1e-9, 1.0)))
    Ts = np.linspace(0.5, 3.0, 26)
    T = float(Ts[int(np.argmin([nll(t) for t in Ts]))])
    Pc = apply_temperature(P, T)
    pred = Pc.argmax(axis=1)
    print(f"확률 보정 T = {T:.2f}")

    print("\n[윈도우 단위, 교차 검증]")
    print(classification_report(y, pred, labels=range(len(LABELS)), target_names=LABELS, digits=3, zero_division=0))
    print("혼동 행렬 (행=정답, 열=예측: " + " ".join(LABELS) + ")")
    print(confusion_matrix(y, pred, labels=range(len(LABELS))))

    # ---------------- 5) 클래스별 임계값 θ ----------------
    theta = {}
    for lb in EVENT_LABELS:
        i = LABELS.index(lb)
        target = args.fall_precision if lb == "fall" else args.target_precision
        chosen = None
        for th in np.arange(0.50, 0.981, 0.01):
            sel = (pred == i) & (Pc[:, i] >= th)
            if sel.sum() >= 5 and (y[sel] == i).mean() >= target:
                chosen = float(round(th, 2))
                break
        if chosen is None:
            chosen = 0.90
            print(f"  [주의] {lb}: 정밀도 {target:.0%} 를 만족하는 θ 가 없어 0.90 으로 둡니다 (데이터 부족/분리 어려움)")
        theta[lb] = chosen
    print("클래스별 임계값 θ:", theta)

    # ---------------- 6) 이벤트 단위 평가 ----------------
    def fires(rows):
        out = set()
        for lb in EVENT_LABELS:
            i = LABELS.index(lb)
            if ((pred[rows] == i) & (Pc[rows, i] >= theta[lb])).any():
                out.add(lb)
        return out

    print("\n[이벤트(파일) 단위] 파일 안에서 한 번이라도 발화한 클래스 (교차 검증 예측 기준)")
    for lb in EVENT_LABELS:
        files = [f for f, l, *_ in ev_info if l == lb]
        ok = wrong_only = miss = 0
        for f in files:
            rows = np.where(fid == f)[0]
            if len(rows) == 0:
                continue
            fired = fires(rows)
            if lb in fired:
                ok += 1
            elif fired:
                wrong_only += 1
            else:
                miss += 1
        n = max(ok + wrong_only + miss, 1)
        print(f"  {lb:9s} 감지 {ok}/{n} ({ok / n:.0%}) | 다른 이벤트로만 발화 {wrong_only} | 미감지 {miss}")
    occ = src == "occ"
    if occ.any():
        fa = sum(((pred[occ] == LABELS.index(lb)) & (Pc[occ, LABELS.index(lb)] >= theta[lb])).sum() for lb in EVENT_LABELS)
        hours = occ.sum() * args.none_stride / 3600.0
        print(f"\n[오탐] 재실(none) 윈도우 {int(occ.sum())}개 중 이벤트로 발화 {int(fa)}개 → 약 {fa / hours:.1f}회/시간 (윈도우 기준)")
        print("   ※ 걷기·뛰기·앉기 같은 오탐 유발 동작은 학습/평가에 없어서, 실제 오탐은 이보다 많을 수 있습니다.")

    # ---------------- 7) 학습 범위(OOD) 기준 + 최종 학습 ----------------
    mean = X.mean(axis=0)
    scale = X.std(axis=0) + 1e-6
    sc = ood_score(X, mean, scale)
    ood = {"mean": mean.tolist(), "scale": scale.tolist(), "threshold": float(np.percentile(sc, 99.9) * 1.5)}
    final.fit(X, y)

    bundle = {
        "model": final, "labels": LABELS, "feature_names": FEATURE_NAMES, "feature_dim": len(FEATURE_NAMES),
        "processing_config": asdict(cfg), "cfg_hash": cfg_hash, "pipeline_version": PIPELINE_VERSION,
        "calibration": {"T": T}, "theta": theta, "ood": ood,
        "node_classes": NODE_CLASSES, "train_rate_hz": ev_rate,
        "counts": {lb: int((y == i).sum()) for i, lb in enumerate(LABELS)},
        "files": dict(n_files),
    }
    joblib.dump(bundle, args.out)
    with open(args.edge_out, "w", encoding="utf-8") as fh:
        json.dump({"processing_config": asdict(cfg), "cfg_hash": cfg_hash, "feature_names": FEATURE_NAMES}, fh,
                  ensure_ascii=False, indent=2)
    print(f"\n저장: {args.out} (서버용), {args.edge_out} (Pi 용 — Pi 의 edge_node.py 폴더로 복사)")
    print("서버와 학습 PC 의 scikit-learn 버전이 같아야 모델이 열립니다.")


if __name__ == "__main__":
    main()
