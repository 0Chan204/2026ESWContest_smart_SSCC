# occupancy_server.py
"""
[맥북(임시 서버)에서 실행] Pi 3대의 특성을 받아 실시간 재실 결과를 출력
=====================================================================

하는 일
  1) MQTT 로 wifi/occupancy/features/+ 를 구독해서 노드별 메시지를 받음
  2) 같은 t_end(윈도우 끝 시각)끼리 모음
       - 3개가 다 모이면 바로 처리
       - 다 안 모여도 t_end + 2초(마감)가 지나면 있는 것만으로 처리 (빠진 노드는 엔진이 판단)
       - 메시지가 하나도 안 온 초도 빼먹지 않고 순서대로 처리 → node_offline 을 알아챌 수 있음
  3) OccupancyEngine.step() 으로 판단 (occupancy_engine.py)
  4) 결과 출력
       - 콘솔: 사람이 보기 좋은 한 줄
       - MQTT: wifi/occupancy/state (팀원 모듈이 구독. retain → 새로 붙어도 최신값을 바로 받음)
       - CSV : logs/occupancy_날짜_시각.csv (확률, 노드 상태 등 분석용 정보 포함)

출력 예 (MQTT state 주제)
  {"time": "2026-10-06T15:05:03+09:00", "location": "kitchen", "location_confidence": 0.87}
  {"time": "2026-10-06T15:05:04+09:00", "location": "unknown", "location_confidence": null,
   "reason": "node_offline:r3"}

실행 예
  python occupancy_server.py                                   # 브로커가 이 맥북(localhost)일 때
  python occupancy_server.py --model multizone_occupancy_svm.pkl --every 2
  python occupancy_server.py --theta 0.7                        # θ 직접 지정 (기본: .pkl 값)
"""

import argparse
import csv
import os
import signal
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from statistics import median

from occupancy_engine import OccupancyEngine

SCRIPT_DIR = Path(__file__).resolve().parent
running = True


def _stop(sig, frame):
    global running
    running = False


class FeatureCollector:
    """MQTT 로 들어온 노드 메시지를 t_end 별로 모아 두는 곳 (MQTT 스레드와 메인 스레드가 함께 사용)"""

    def __init__(self, nodes):
        self.nodes = set(nodes)
        self.lock = threading.Lock()
        self.pending = defaultdict(dict)          # t_end → {node: msg}
        self.last_done = None                     # 마지막으로 처리한 t_end (이보다 오래된 건 버림)
        self.delay = {n: deque(maxlen=30) for n in nodes}   # 도착 시각 − t_end (시계 어긋남 감시용)
        self.dropped_late = 0
        self.truth = None                         # (도착 시각, 정답 라벨) — replay_test.py 가 보냄

    def on_features(self, topic, msg):
        node = msg.get("node")
        t_end = msg.get("t_end")
        if msg.get("v") != 1 or node not in self.nodes or not isinstance(t_end, int):
            return                                # 형식이 맞지 않는 메시지는 무시
        arrival = time.time()
        with self.lock:
            self.delay[node].append(arrival - t_end)
            if self.last_done is not None and t_end <= self.last_done:
                self.dropped_late += 1            # 이미 마감한 초의 메시지 = 너무 늦게 도착
                return
            self.pending[t_end][node] = msg

    def on_truth(self, topic, msg):
        self.truth = (time.time(), msg.get("label"))

    def pop_ready(self, now, deadline):
        """
        처리할 차례인 (t_end, msgs) 목록을 순서대로 꺼낸다.
          다음 차례(t)의 3개 노드가 다 모였거나, 마감(t + deadline)이 지났으면 꺼냄.
          아니면 거기서 멈춤 (순서를 지키기 위해 뒤의 초도 기다림).
        """
        ready = []
        with self.lock:
            if self.last_done is None:
                self.last_done = int(now - deadline) - 1      # 서버 시작 시점
            while True:
                t = self.last_done + 1
                msgs = self.pending.get(t, {})
                if set(msgs) >= self.nodes or now >= t + deadline:
                    self.pending.pop(t, None)
                    self.last_done = t
                    ready.append((t, msgs))
                else:
                    break
            for t in [t for t in self.pending if t <= self.last_done]:   # 정리
                del self.pending[t]
        return ready


def fmt_console(res, nodes):
    o, d = res["output"], res["debug"]
    conf = f"{o['location_confidence']:.2f}" if o["location_confidence"] is not None else "  - "
    why = o.get("reason", "")
    parts = []
    for n in nodes:
        v = (d["nodes"] or {}).get(n, {})
        rate = f"{v['rate_hz']:.1f}Hz" if v.get("rate_hz") is not None else "  -  "
        parts.append(f"{n} {str(v.get('status', '-')):<10} {rate}")
    return f"{o['time'][11:19]}  {o['location']:<8} {conf}  {why:<26}| " + " | ".join(parts)


def parse_args():
    p = argparse.ArgumentParser(description="실시간 재실 판단 서버")
    p.add_argument("--model", default=str(SCRIPT_DIR / "multizone_occupancy_svm.pkl"), help=".pkl 경로")
    p.add_argument("--broker", default="localhost", help="MQTT 브로커 주소 (맥북에서 브로커를 돌리면 localhost)")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--prefix", default=None, help="MQTT 주제 앞부분 (기본 wifi/occupancy)")
    p.add_argument("--every", type=int, default=1, choices=[1, 2], help="결과를 몇 초마다 내보낼지 (판단은 매초)")
    p.add_argument("--deadline", type=float, default=2.0, help="t_end 후 이 시간까지 노드 메시지를 기다림(초)")
    p.add_argument("--theta", type=float, default=None, help="판단 불가 임계값 (기본: .pkl 에 저장된 값)")
    p.add_argument("--switch", type=int, default=2, help="장소 전환에 필요한 연속 초 수")
    p.add_argument("--no-ood", action="store_true", help="학습 범위 검사 끄기")
    p.add_argument("--log-dir", default=str(SCRIPT_DIR / "logs"), help="CSV 로그 저장 폴더")
    return p.parse_args()


def main():
    args = parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    from mqtt_util import DEFAULT_PREFIX, MqttLink, topic_features, topic_state, topic_truth
    prefix = args.prefix or DEFAULT_PREFIX

    if not os.path.exists(args.model):
        raise SystemExit(f"[오류] 모델 파일이 없습니다: {args.model}  (--model 로 경로를 지정하세요)")
    engine = OccupancyEngine(args.model, theta=args.theta, switch_k=args.switch, use_ood=not args.no_ood)
    nodes = engine.locs
    collector = FeatureCollector(nodes)

    # --- CSV 로그 ---
    os.makedirs(args.log_dir, exist_ok=True)
    log_path = os.path.join(args.log_dir, f"occupancy_{datetime.now():%Y%m%d_%H%M%S}.csv")
    log_f = open(log_path, "w", newline="", encoding="utf-8")
    log_w = csv.writer(log_f)
    log_w.writerow(["time", "location", "location_confidence", "reason"]
                   + [f"p_{lb}" for lb in engine.labels] + ["ood_score"]
                   + [f"{n}_{k}" for n in nodes for k in ("status", "rate_hz", "proc_ms")] + ["truth"])

    # --- MQTT ---
    link = MqttLink(args.broker, args.mqtt_port, client_id=f"occupancy-server-{os.getpid()}")
    link.subscribe(topic_features(prefix), collector.on_features)
    link.subscribe(topic_truth(prefix), collector.on_truth)
    link.start()
    print(f"구독: {topic_features(prefix)}  →  발행: {topic_state(prefix)}  |  로그: {log_path}")
    print("시각      장소     신뢰도 이유                      | 노드 상태")

    last_skew_check = time.time()
    try:
        while running:
            now = time.time()
            for t_end, msgs in collector.pop_ready(now, args.deadline):
                res = engine.step(t_end, msgs)
                o, d = res["output"], res["debug"]
                # 판단은 매초 하고, 내보내기만 every 초마다
                if t_end % args.every == 0:
                    link.publish(topic_state(prefix), o, retain=True)
                    print(fmt_console(res, nodes))
                truth = collector.truth[1] if collector.truth and now - collector.truth[0] < 5 else ""
                probs = d["probs"] or {}
                log_w.writerow([o["time"], o["location"], o["location_confidence"], o.get("reason", "")]
                               + [probs.get(lb, "") for lb in engine.labels]
                               + ["" if d["ood_score"] is None else round(d["ood_score"], 3)]
                               + [(d["nodes"] or {}).get(n, {}).get(k, "") for n in nodes
                                  for k in ("status", "rate_hz", "proc_ms")] + [truth])
            log_f.flush()

            # 30초마다: 노드 시계가 서버와 맞는지 점검 (정상이면 도착 지연이 0.3~1초 정도)
            if now - last_skew_check > 30:
                last_skew_check = now
                for n, dq in collector.delay.items():
                    if len(dq) >= 5:
                        dly = median(dq)
                        if dly < 0 or dly > args.deadline - 0.2:
                            print(f"[주의] {n} 의 메시지 도착 지연이 {dly:+.2f}초입니다. "
                                  f"{'Pi 시계가 서버보다 빠름' if dly < 0 else 'Pi 시계가 느리거나 처리/네트워크 지연'}"
                                  f" → 양쪽 NTP 시간 동기화를 확인하세요.")
                if collector.dropped_late:
                    print(f"[주의] 마감 후 늦게 도착해 버린 메시지 {collector.dropped_late}개")
                    collector.dropped_late = 0
            time.sleep(0.05)
    finally:
        link.stop()
        log_f.close()
        print(f"\n종료. 로그: {log_path}")


if __name__ == "__main__":
    main()
