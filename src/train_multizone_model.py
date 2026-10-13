# train_multizone_model.py
"""
노드 3개(부엌/방/화장실)의 CSI → 4클래스 재실 위치 분류 모델 학습
===================================================================

클래스 (1인 가구 가정): 0 empty(비재실) / 1 room(방) / 2 kitchen(부엌) / 3 toilet(화장실)

필요한 폴더 구조 (csi_serial_logger.py 가 이 형태로 바로 저장함)
  dataset/
    empty/    empty_r2_20260930_143000.csv  empty_r3_20260930_143000.csv  empty_r4_20260930_143000.csv ...
    room/     room_r2_....csv ...
    kitchen/  ...
    toilet/   ...
  → 같은 세션 이름을 가진 r2/r3/r4 파일 3개가 한 세트

기존 코드에서 바뀐 핵심
  1) 평가를 '세션 단위'로 나눔 (StratifiedGroupKFold)
     - 예전: 1초 조각을 무작위로 섞어서 나눔 → 같은 녹화의 바로 옆 1초가 train/test 양쪽에
       들어가서 점수가 실제보다 훨씬 높게 나왔음 (데이터 누수)
     - 지금: 한 세션은 통째로 train 또는 test 한쪽에만 들어감 → '처음 보는 녹화'에 대한 진짜 성능
  2) 하이퍼파라미터(C, gamma, PCA 사용 여부)를 교차 검증 안에서 자동으로 고름 (중첩 CV)
  3) 클래스 불균형 보정(class_weight="balanced") + macro F1 로 평가
  4) 실시간과 같은 방식(최근 N초 확률 평균)으로 평활화한 성능도 같이 출력
  5) 노드 3개를 '앞에서부터 자르기'가 아니라 '같은 시각' 기준으로 합침
  6) 모델과 함께 전처리 설정·라벨·특성 순서를 저장 → 실시간 코드가 그대로 불러 쓰면 됨
  7) [실시간용 추가] 세션 단위 교차 검증 결과로
       - 확률 보정값(temperature T)   : SVM 확률의 '과한 확신'을 바로잡음
       - 판단 불가 임계값(θ)           : 신뢰도 ≥ θ 일 때 정확도가 TARGET_ACCURACY 이상이 되는 값
       - 학습 범위 기준(OOD threshold) : 처음 보는 환경을 알아채기 위한 기준
     을 계산해 .pkl 에 함께 저장하고, Pi 용 설정 파일(edge_config.json)도 만든다.
"""

import glob
import json
import os
import re

import joblib
import numpy as np
import pandas as pd
import sklearn
from scipy.optimize import minimize_scalar
from sklearn.base import clone
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from wifi_occupancy_pipeline import (
    FEATURE_NAMES, LABELS, LOCATION_CODES, LOCATION_NAMES,
    CSIDataProcessor, ProcessingConfig, smooth_probabilities,
    apply_temperature, make_config_hash, ood_score,
)

# ==========================================================
# 설정
# ==========================================================
DATASET_ROOT = "dataset"
MODEL_PATH = "multizone_occupancy_svm.pkl"
RANDOM_STATE = 42

# 노드별 송신기(AP) MAC. None 이면 파일마다 가장 많이 나온 MAC 을 자동 사용.
# AP MAC 을 알고 있다면 적어 두는 것이 더 안전하다. 예) "b0:38:6c:56:0d:52"
TARGET_MACS = {"r2": None, "r3": None, "r4": None}

# 최종 판단 시 최근 몇 초의 확률을 평균할지 (실시간에서도 같은 값을 쓸 것)
SMOOTH_N = 5

# 자동으로 시험해 볼 하이퍼파라미터 조합
PARAM_GRID = {
    "pca": [PCA(n_components=0.95), "passthrough"],   # PCA 쓸지 말지
    "svm__C": [0.5, 1, 2, 5, 10],                     # 클수록 학습 데이터에 더 딱 맞춤 (과적합 위험↑)
    "svm__gamma": ["scale", 0.01, 0.05, 0.1],         # 클수록 경계가 구불구불해짐
}

# --- 실시간 판단 기준 관련 ---
EDGE_CONFIG_PATH = "edge_config.json"   # Pi 에 복사할 설정 파일
TARGET_ACCURACY = 0.90   # "신뢰도 ≥ θ 인 결과는 이만큼 맞아야 한다" → θ 를 이 기준으로 고름
DEFAULT_THETA = 0.60     # 교차 검증을 못 했을 때(세션 부족) 쓰는 임시 θ
OOD_PERCENTILE = 99.9    # 학습 데이터의 99.9% 가 통과하는 점수를 기준으로 삼고
OOD_MARGIN = 1.5         # 거기에 1.5 배 여유를 줌 → 정상 상황에서는 거의 걸리지 않음

processor = CSIDataProcessor(ProcessingConfig())


# ==========================================================
# 1. 데이터셋 만들기
# ==========================================================

def load_session(folder: str, label: str, suffix: str):
    """
    한 세션의 r2/r3/r4 CSV 3개 → 같은 시각끼리 옆으로 이어 붙인 DataFrame
    (행 = 1초 윈도우, 열 = 19 × 3 = 57개 특성, index = 윈도우 끝 tick)
    """
    per_loc, sources = [], set()
    for loc in LOCATION_CODES:
        path = os.path.join(folder, f"{label}_{loc}_{suffix}.csv")
        if not os.path.exists(path):
            print(f"    [건너뜀] {loc} 파일 없음: {os.path.basename(path)}")
            return None

        feats, ticks, info = processor.process_csv(path, TARGET_MACS[loc])
        sources.add(info["time_source"])
        warn = ""
        if info.get("mac_ratio", 1.0) < 0.8:
            warn += " [주의: AP 패킷 비율 낮음]"
        if info.get("stale_rows"):
            warn += f" [녹화 전 밀린 패킷 {info['stale_rows']}행 제외]"
        if abs(info["rate_hz"] - processor.cfg.fs) > 0.3 * processor.cfg.fs:
            warn += f" [주의: 수신 속도가 fs={processor.cfg.fs:g}Hz 와 많이 다름]"
        print(f"    {loc}({LOCATION_NAMES[loc]}): {info['rows_used']}/{info['rows_total']}행 사용, "
              f"{info['rate_hz']:.1f}Hz, 윈도우 {len(feats)}개{warn}")
        if len(feats) == 0:
            print("    [건너뜀] 윈도우가 하나도 안 나옴 (녹화가 너무 짧거나 공백이 많음)")
            return None

        cols = [f"{loc}__{name}" for name in FEATURE_NAMES]
        per_loc.append(pd.DataFrame(feats, index=ticks, columns=cols))

    if "esp_local" in sources:
        print("    [참고] host_timestamp 없는 예전 CSV → 녹화 시작 시점이 같다고 가정하고 합침")

    # 같은 tick(= 같은 시각)을 가진 윈도우만 남겨서 옆으로 합치기
    merged = pd.concat(per_loc, axis=1, join="inner").sort_index()
    if merged.empty:
        print("    [건너뜀] 세 노드의 시간이 겹치지 않음 (시작 시각/PC 시계 확인)")
        return None
    return merged


def build_dataset(root_dir: str):
    """반환: X (샘플, 57), y (샘플,), groups (세션 이름), ticks (시각), 특성 열 이름"""
    X_list, y_list, g_list, t_list, columns = [], [], [], [], None

    for class_id, label in enumerate(LABELS):
        folder = os.path.join(root_dir, label)
        if not os.path.isdir(folder):
            print(f"[정보] 폴더 없음: {folder} (건너뜀)")
            continue

        # 파일 이름에서 세션 이름 뽑기: {label}_{loc}_{세션}.csv
        pattern = re.compile(rf"^{re.escape(label)}_({'|'.join(LOCATION_CODES)})_(.+)\.csv$")
        suffixes = sorted({m.group(2) for f in glob.glob(os.path.join(folder, "*.csv"))
                           if (m := pattern.match(os.path.basename(f)))})
        print(f"\n[{label}] 세션 {len(suffixes)}개 발견")

        for suffix in suffixes:
            print(f"  세션 '{suffix}'")
            df = load_session(folder, label, suffix)
            if df is None:
                continue
            columns = list(df.columns)
            X_list.append(df.to_numpy())
            y_list.append(np.full(len(df), class_id))
            g_list.append(np.full(len(df), f"{label}/{suffix}", dtype=object))
            t_list.append(df.index.to_numpy())
            print(f"    → 합친 윈도우 {len(df)}개")

    if not X_list:
        raise ValueError("유효한 세션이 없습니다. 폴더 구조와 파일 이름을 확인하세요.")
    return (np.vstack(X_list), np.concatenate(y_list), np.concatenate(g_list),
            np.concatenate(t_list), columns)


def print_summary(y, groups):
    print("\n" + "=" * 60)
    print(f"전체: {len(y)}개 윈도우, 세션 {len(np.unique(groups))}개")
    for cid, name in enumerate(LABELS):
        mask = y == cid
        print(f"  {name:<8} 세션 {len(np.unique(groups[mask])):3d}개 | "
              f"윈도우 {mask.sum():5d}개 ({mask.mean() * 100:5.1f}%)")
    print("=" * 60)


# ==========================================================
# 2. 모델 & 튜닝
# ==========================================================

def make_model(probability: bool = False) -> Pipeline:
    """스케일링 → (PCA) → SVM(RBF). class_weight='balanced' 로 적은 클래스에 가중치를 더 줌."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=0.95)),
        ("svm", SVC(kernel="rbf", C=2.0, gamma="scale", class_weight="balanced",
                    probability=probability, random_state=RANDOM_STATE)),
    ])


def min_sessions_per_class(y, groups) -> int:
    """클래스별 세션 수 중 가장 작은 값 (교차 검증을 몇 겹으로 할 수 있는지 결정)"""
    return min(len(np.unique(groups[y == c])) for c in np.unique(y))


def tune(X, y, groups):
    """
    세션 단위 교차 검증으로 가장 좋은 하이퍼파라미터를 찾는다.
    세션이 클래스당 2개 미만이면 튜닝이 불가능하므로 기본값을 쓴다.
    (속도를 위해 튜닝 중에는 probability=False)
    """
    n_splits = min(4, min_sessions_per_class(y, groups))
    if n_splits < 2 or len(np.unique(y)) < len(LABELS):
        return {}, None
    gs = GridSearchCV(
        make_model(), PARAM_GRID, scoring="f1_macro", n_jobs=-1,
        cv=StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE),
    )
    gs.fit(X, y, groups=groups)
    return gs.best_params_, gs.best_score_


def build_with_params(params: dict, probability: bool) -> Pipeline:
    model = make_model(probability=probability)
    # 튜닝 결과 안의 PCA 객체는 복사해서 써야 서로 간섭하지 않음
    return model.set_params(**{k: (clone(v) if hasattr(v, "fit") else v) for k, v in params.items()})


# ==========================================================
# 3. 세션 단위 평가 (중첩 교차 검증)
# ==========================================================

def smooth_by_session(probs, groups, ticks, n):
    """세션마다 시간순으로 정렬한 뒤 '최근 n초 확률 평균' 적용 (실시간 판단 방식과 동일)"""
    out = np.zeros_like(probs)
    for g in np.unique(groups):
        idx = np.where(groups == g)[0]
        idx = idx[np.argsort(ticks[idx])]
        out[idx] = smooth_probabilities(probs[idx], n)
    return out


def report(title, y_true, y_pred):
    names = LABELS
    print(f"\n--- {title} ---")
    print(f"Accuracy {accuracy_score(y_true, y_pred):.4f} | "
          f"Macro F1 {f1_score(y_true, y_pred, average='macro', labels=range(len(names))):.4f}")
    print(classification_report(y_true, y_pred, labels=range(len(names)),
                                target_names=names, zero_division=0))
    cm = confusion_matrix(y_true, y_pred, labels=range(len(names)))
    print("Confusion Matrix (행 = 정답, 열 = 예측)")
    print(pd.DataFrame(cm, index=names, columns=names).to_string())


def evaluate(X, y, groups, ticks):
    """
    바깥 루프: 세션을 k겹으로 나눠 test 세션은 학습에 전혀 쓰지 않음
    안쪽 루프: train 세션만으로 하이퍼파라미터 튜닝
    → test 점수에 튜닝 과정의 낙관 편향까지 들어가지 않는 '정직한' 성능
    """
    n_outer = min(5, min_sessions_per_class(y, groups))
    if n_outer < 2:
        print("\n[평가 생략] 클래스마다 세션이 최소 2개는 있어야 세션 단위 평가가 가능합니다.")
        return None

    print(f"\n세션 단위 {n_outer}겹 교차 검증 시작 (안쪽에서 하이퍼파라미터 튜닝 포함)...")
    outer = StratifiedGroupKFold(n_splits=n_outer, shuffle=True, random_state=RANDOM_STATE)
    probs = np.zeros((len(y), len(LABELS)))

    for fold, (tr, te) in enumerate(outer.split(X, y, groups), 1):
        params, score = tune(X[tr], y[tr], groups[tr])
        model = build_with_params(params, probability=True).fit(X[tr], y[tr])
        # 어떤 fold 의 train 에 특정 클래스가 없을 수도 있으므로 클래스 번호에 맞춰 넣기
        probs[np.ix_(te, model.classes_)] = model.predict_proba(X[te])
        score_txt = f"{score:.3f}" if score is not None else "-"
        print(f"  fold {fold}: test 세션 {len(np.unique(groups[te]))}개, "
              f"안쪽 CV F1 {score_txt}, 선택 {_fmt(params)}")

    raw_pred = probs.argmax(axis=1)
    smooth_pred = smooth_by_session(probs, groups, ticks, SMOOTH_N).argmax(axis=1)
    report("1초 단위 예측 (평활화 없음)", y, raw_pred)
    report(f"최근 {SMOOTH_N}초 확률 평균 (실시간 판단 방식)", y, smooth_pred)

    # 정확도가 낮은 세션 = 녹화 실수(라벨 오류, 사람 위치 잘못 등)일 가능성 → 직접 확인해 볼 것
    per_session = (pd.DataFrame({"session": groups, "correct": smooth_pred == y})
                   .groupby("session")["correct"].mean().sort_values())
    print("\n정확도가 낮은 세션 Top 5 (녹화 상태 점검 권장)")
    print(per_session.head(5).map(lambda v: f"{v * 100:.1f}%").to_string())

    # 각 1초 윈도우가 'test 세션'이었을 때 받은 확률 = 처음 보는 데이터에 대한 확률
    # → 실시간 판단 기준(보정, θ)을 정하는 재료로 쓴다
    return probs


# ==========================================================
# 3-1. 실시간 판단 기준 만들기
# ==========================================================

def fit_temperature(probs, y) -> float:
    """
    교차 검증 확률(probs)이 실제 정답(y)과 가장 잘 맞도록 T 를 고른다.
    '정답 클래스에 준 확률의 -log 평균'(NLL)이 가장 작아지는 T 를 찾는다.
      예) 확률 0.95 로 확신했는데 실제 정확도가 80% 라면 → T > 1 이 나와서 확신을 낮춤
    """
    def nll(T):
        P = apply_temperature(probs, T)
        return -np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-9, 1)))
    # T 범위를 0.5~10 으로 제한: 데이터가 적을 때 극단적인 값(확률을 0/1 로 만들어 버리는 등)을 막음
    res = minimize_scalar(nll, bounds=(0.5, 10.0), method="bounded")
    return float(res.x)


def choose_theta(conf, correct):
    """
    신뢰도 임계값 θ 후보(0.50~0.95)마다
      - 통과율: 신뢰도 ≥ θ 인 결과 비율 (나머지는 '판단 불가'로 출력됨)
      - 정확도: 통과한 결과 중 맞은 비율
    을 계산하고, 정확도가 TARGET_ACCURACY 이상이 되는 가장 작은 θ 를 고른다.
    (θ 가 클수록 정확하지만 '판단 불가'가 늘어나므로, 기준을 넘는 선에서 가장 작게)
    """
    rows, chosen = [], None
    # 0.5 미만은 '4개 중 과반도 아닌' 확신이라 후보에서 제외
    for th in np.round(np.arange(0.50, 0.96, 0.05), 2):
        m = conf >= th
        cov, acc = m.mean(), (correct[m].mean() if m.sum() else np.nan)
        rows.append((th, cov, acc, int(m.sum())))
        if chosen is None and m.sum() >= 30 and acc >= TARGET_ACCURACY:
            chosen = float(th)
    print(f"\n신뢰도 임계값 θ 후보 (목표: 통과한 결과의 정확도 ≥ {TARGET_ACCURACY:.0%})")
    print("   θ    통과율   정확도   개수")
    for th, cov, acc, n in rows:
        mark = "  ← 선택" if chosen is not None and th == chosen else ""
        acc_txt = f"{acc:6.1%}" if not np.isnan(acc) else "    - "
        print(f"  {th:.2f}  {cov:6.1%}  {acc_txt}  {n:5d}{mark}")
    if chosen is None:
        chosen = 0.90
        print(f"  [주의] 목표 정확도를 만족하는 θ 가 없어 {chosen} 로 둡니다. 데이터를 더 모으세요.")
    return chosen, rows


def build_realtime_criteria(probs, y, groups, ticks):
    """교차 검증 확률 → (temperature T, θ, 리포트). 교차 검증을 못 했으면 기본값."""
    if probs is None:
        print(f"\n[주의] 세션이 부족해 확률 보정을 못 했습니다. T=1.0, θ={DEFAULT_THETA} (임시값)")
        return 1.0, DEFAULT_THETA, None
    T = fit_temperature(probs, y)
    cal = apply_temperature(probs, T)
    smooth = smooth_by_session(cal, groups, ticks, SMOOTH_N)   # 실시간과 같은 평활화
    conf = smooth.max(axis=1)
    correct = smooth.argmax(axis=1) == y
    print(f"\n확률 보정: temperature T = {T:.2f}  "
          f"({'과한 확신을 낮춤' if T > 1 else '확신이 부족해서 올림' if T < 1 else '변화 없음'})")
    print(f"  보정 전 평균 신뢰도 {smooth_by_session(probs, groups, ticks, SMOOTH_N).max(axis=1).mean():.2f}"
          f" → 보정 후 {conf.mean():.2f}  (실제 정확도 {correct.mean():.2f})")
    theta, rows = choose_theta(conf, correct)
    return T, theta, [dict(theta=r[0], coverage=r[1], accuracy=r[2], n=r[3]) for r in rows]


def build_ood_reference(model, X):
    """
    최종 모델의 StandardScaler(학습 데이터 평균·표준편차)로 학습 데이터 자체의 점수를 구하고,
    99.9% 지점 × 1.5 를 '학습 범위를 크게 벗어남' 기준으로 삼는다.
    """
    sc = model.named_steps["scaler"]
    scores = ood_score(X, sc.mean_, sc.scale_)
    thr = float(np.percentile(scores, OOD_PERCENTILE) * OOD_MARGIN)
    print(f"\n학습 범위 기준: 학습 데이터 점수 중앙값 {np.median(scores):.2f}, "
          f"{OOD_PERCENTILE}% 지점 {np.percentile(scores, OOD_PERCENTILE):.2f} → 기준 {thr:.2f}")
    return {"mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(), "threshold": thr}


def export_edge_config(path, cfg_hash):
    """
    Pi(edge_node.py)가 읽을 설정 파일. Pi 에는 sklearn 이나 .pkl 이 필요 없고 이 파일만 있으면 된다.
    """
    edge_cfg = {
        "cfg_hash": cfg_hash,                       # 서버가 비교하는 전처리 지문
        "processing_config": processor.config_dict(),
        "feature_names": FEATURE_NAMES,
        "location_codes": LOCATION_CODES,
        "target_macs": TARGET_MACS,                 # 노드별 AP MAC (None = 자동)
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(edge_cfg, f, ensure_ascii=False, indent=2)
    print(f"Pi 설정 파일 저장: {path}  (cfg_hash={cfg_hash})")


def _fmt(params: dict) -> str:
    if not params:
        return "기본값"
    return ", ".join(f"{k}={'PCA' if isinstance(v, PCA) else v}" for k, v in params.items())


# ==========================================================
# 4. 실행
# ==========================================================

def main():
    print(f"데이터셋 불러오는 중: {DATASET_ROOT}")
    X, y, groups, ticks, columns = build_dataset(DATASET_ROOT)
    print_summary(y, groups)

    # (1) 정직한 성능 평가 (+ 처음 보는 세션에 대한 확률 확보)
    oof_probs = evaluate(X, y, groups, ticks)

    # (1-1) 실시간 판단 기준: 확률 보정 T, 판단 불가 임계값 θ
    temperature, theta, theta_table = build_realtime_criteria(oof_probs, y, groups, ticks)

    # (2) 전체 데이터로 최종 모델 학습
    print("\n최종 모델 학습 (전체 세션 사용)...")
    params, score = tune(X, y, groups)
    final_model = build_with_params(params, probability=True).fit(X, y)
    print(f"  선택된 하이퍼파라미터: {_fmt(params)}")

    # (2-1) 학습 범위 기준 (최종 모델의 스케일러 기준)
    ood_ref = build_ood_reference(final_model, X)
    cfg_hash = make_config_hash(processor.cfg)

    # (3) 저장: 모델만이 아니라 '어떻게 전처리했는지'까지 함께 저장
    #     실시간 코드는 이 설정으로 CSIDataProcessor 를 만들고, feature_columns 순서대로 특성을 넣으면 됨
    bundle = {
        "model": final_model,
        "labels": LABELS,
        "location_codes": LOCATION_CODES,
        "feature_columns": columns,
        "processing_config": processor.config_dict(),
        "target_macs": TARGET_MACS,
        "smooth_n": SMOOTH_N,
        "best_params": _fmt(params),
        # --- 실시간용 (occupancy_engine.py 가 사용) ---
        "feature_names": FEATURE_NAMES,
        "cfg_hash": cfg_hash,
        "calibration": {"method": "temperature", "T": temperature},
        "theta": theta,
        "theta_table": theta_table,
        "ood": ood_ref,
        "sklearn_version": sklearn.__version__,   # 다른 PC 에서 열 때 버전이 같아야 함
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"\n저장 완료: {MODEL_PATH}  (scikit-learn {sklearn.__version__})")
    print(f"  실시간 기준: T={temperature:.2f}, θ={theta:.2f}, 학습 범위 기준={ood_ref['threshold']:.2f}")
    export_edge_config(EDGE_CONFIG_PATH, cfg_hash)


if __name__ == "__main__":
    main()
