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

행동 추론 (낙상/눕기/기상)을 같은 프로세스에서 함께 실행
  같은 폴더에 behavior_svm.pkl 이 있으면 자동으로 켜진다 (--no-behavior 로 끔).
  Pi 메시지의 "behavior" 필드를 behavior_engine.py 가 노드별로 판단 → wifi/behavior/state/<노드> 로 발행
  {"time": ..., "node": "r3", "behavior": "fall", "behavior_confidence": 0.93, "reason": null, "new": true}

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
from presence_tracker import PresenceTracker

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
        self.combined_count = 0
        self._warned = set()
        # 정답 기록 (truth_logger.py / replay_test.py 가 보냄): (적용 시작 시각, 라벨)
        #   다음 정답이 올 때까지 계속 유지. 라벨 "none" = 정답 기록 중단
        self.truth_events = deque(maxlen=1000)

    # 토픽에 방 이름이 들어 있으면(예: home/room/edge/r1/features) 그 방의 노드로 본다.
    #   백엔드의 번호(r1/r2/r3)와 우리 코드의 번호(r2=부엌, r3=방, r4=화장실)가 달라도 토픽의 방 이름으로 맞춘다.
    def node_from_topic(self, topic):
        for part in str(topic).split("/"):
            if part in self.ROOM_TO_NODE:
                return self.ROOM_TO_NODE[part]
        return None

    def on_features(self, topic, msg):
        node = msg.get("node")
        by_topic = self.node_from_topic(topic)
        if by_topic is not None:
            if node != by_topic and by_topic not in self._warned:
                self._warned.add(by_topic)
                print(f"[알림] 토픽 {topic} 의 메시지에 node={node!r} 가 들어 있지만 토픽의 방({by_topic})을 기준으로 처리합니다.")
            node = by_topic
            msg = dict(msg, node=node)
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

    # 백엔드가 노드 메시지를 묶어서 보내는 경우 (예: home/edge/combined)
    #   {"seq": .., "publishedAt": .., "rooms": {"room": {"node": <Pi 메시지 원본>, ...},
    #                                            "kitchen": {...}, "toilet": {...}}}
    #   각 방의 "node" 에 들어 있는 Pi 메시지를 꺼내 on_features 로 넘긴다.
    #   → 묶는 주기·순서와 상관없이 t_end 기준으로 다시 맞춰지고, 같은 메시지가 여러 번 와도 덮어쓸 뿐이라 안전.
    ROOM_TO_NODE = {"kitchen": "r2", "room": "r3", "toilet": "r4"}

    def on_combined(self, topic, msg):
        """백엔드의 구역별 묶음 메시지. 형식이 조금 달라도 받도록 느슨하게 해석한다.
        허용: {"rooms"|"locations"|"zones": {방: X}} 또는 {방: X} 또는 [{"room":방, ...}]
              X = Pi 메시지 자체 | {"node"|"message"|"data"|"payload": Pi 메시지} | 리스트(마지막 것 사용)"""
        if isinstance(msg, dict):
            rooms = next((msg[k] for k in ("rooms", "locations", "zones") if isinstance(msg.get(k), (dict, list))), None)
            if rooms is None and any(r in msg for r in self.ROOM_TO_NODE):
                rooms = msg
        else:
            rooms = msg
        if isinstance(rooms, list):
            rooms = {e.get("room") or e.get("zone") or e.get("location"): e for e in rooms if isinstance(e, dict)}
        if not isinstance(rooms, dict):
            return
        for room, entry in rooms.items():
            if isinstance(entry, list):
                entry = entry[-1] if entry else None
            node_msg = entry
            if isinstance(entry, dict) and "t_end" not in entry:
                node_msg = next((entry[k] for k in ("node", "message", "data", "payload")
                                 if isinstance(entry.get(k), dict)), None)
            if isinstance(node_msg, dict) and "t_end" not in node_msg:
                node_msg = None
            if node_msg is None:
                continue                              # 아직 그 방의 Pi 데이터가 없음 (null)
            if room in self.ROOM_TO_NODE:             # 방 이름(키)이 기준: 백엔드의 노드 번호와 우리 번호가 달라도 맞춰짐
                node_msg = dict(node_msg, node=self.ROOM_TO_NODE[room])
            self.on_features(topic, node_msg)
            self.combined_count += 1

    def on_truth(self, topic, msg):
        label = msg.get("label")
        if not isinstance(label, str):
            return
        # replay_test 는 어느 윈도우의 정답인지(t_end)를 함께 보냄. 사람이 누른 건 받은 시각부터 적용
        start = msg.get("t_end", msg.get("time", time.time()))
        with self.lock:
            self.truth_events.append((float(start), label))

    def truth_at(self, t_end):
        """t_end 시점의 정답 라벨 (없으면 빈 문자열)"""
        with self.lock:
            past = [e for e in self.truth_events if e[0] <= t_end]
        if not past:
            return ""
        label = max(past, key=lambda e: e[0])[1]
        return "" if label == "none" else label

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


def fmt_console(res, final, nodes):
    d = res["debug"]
    o = final
    conf = f"{o['location_confidence']:.2f}" if o["location_confidence"] is not None else "  - "
    if o.get("source") == "held":
        # 유지 중: '유지(관측된 것)'과 남은 시간을 함께 표시
        why = f"유지 ← {o['observed']} ({o['hold_remaining_sec'] // 60}분 남음)"
    else:
        why = o.get("reason", "")
    parts = []
    for n in nodes:
        v = (d["nodes"] or {}).get(n, {})
        rate = f"{v['rate_hz']:.1f}Hz" if v.get("rate_hz") is not None else "  -  "
        parts.append(f"{n} {str(v.get('status', '-')):<10} {rate}")
    return f"{o['time'][11:19]}  {o['location']:<8} {conf}  {why:<30}| " + " | ".join(parts)


def parse_args():
    p = argparse.ArgumentParser(description="실시간 재실 판단 서버")
    p.add_argument("--model", default=str(SCRIPT_DIR / "multizone_occupancy_svm.pkl"), help=".pkl 경로")
    p.add_argument("--broker", default="localhost", help="MQTT 브로커 주소 (맥북에서 브로커를 돌리면 localhost)")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--prefix", default=None, help="MQTT 주제 앞부분 (기본 wifi/occupancy)")
    # --- 통합 서버 연동 ---
    p.add_argument("--features-topic", default=None,
                   help="Pi 특성 메시지를 받을 주제(와일드카드 가능). 예: home/+/edge/+/features  "
                        "(토픽의 방 이름 room/kitchen/toilet 으로 노드를 정함). 기본: <prefix>/features/+")
    p.add_argument("--combined-topic", default=None,
                   help="Pi 메시지를 백엔드가 묶어서 보내는 주제 (예: home/edge/combined). "
                        "지정하면 Pi 개별 주제 대신 이 주제를 구독")
    p.add_argument("--state-topic", default=None, help="최종 결과를 발행할 주제 (기본: <prefix>/state)")
    p.add_argument("--every", type=int, default=1, choices=[1, 2], help="결과를 몇 초마다 내보낼지 (판단은 매초)")
    p.add_argument("--deadline", type=float, default=2.0, help="t_end 후 이 시간까지 노드 메시지를 기다림(초)")
    p.add_argument("--theta", type=float, default=None, help="판단 불가 임계값 (기본: .pkl 에 저장된 값)")
    p.add_argument("--switch", type=int, default=2, help="장소 전환에 필요한 연속 초 수")
    p.add_argument("--no-ood", action="store_true", help="학습 범위 검사 끄기")
    # --- 행동 추론 (behavior_engine.py). 같은 Pi 메시지의 "behavior" 필드를 사용 ---
    default_beh = SCRIPT_DIR / "behavior_svm.pkl"
    p.add_argument("--behavior-model", default=str(default_beh) if default_beh.exists() else None,
                   help="행동 모델 .pkl (기본: 이 폴더의 behavior_svm.pkl 이 있으면 자동 사용)")
    p.add_argument("--no-behavior", action="store_true", help="행동 추론 끄기 (재실만)")
    p.add_argument("--behavior-prefix", default="wifi/behavior", help="행동 결과 주제 앞부분 (<prefix>/state/<노드>)")
    p.add_argument("--behavior-no-ood", action="store_true", help="행동: 학습 범위 검사 끄기")
    p.add_argument("--behavior-settle", type=int, default=8,
                   help="행동: 노드가 시작/복구된 직후 판단을 보류할 초 (기본 8)")
    p.add_argument("--behavior-theta", nargs="*", default=[], metavar="행동=값",
                   help="행동별 발화 임계값 덮어쓰기. 예) --behavior-theta fall=0.6 lie_down=0.7 get_up=0.7 (기본: .pkl 값)")
    p.add_argument("--behavior-confirm", nargs="*", default=[], metavar="행동=횟수",
                   help="발화에 필요한 연속 횟수(초). 예) --behavior-confirm lie_down=1 (기본 fall=1, lie_down=2, get_up=2)")
    p.add_argument("--behavior-hold", nargs="*", default=[], metavar="행동=초",
                   help="발화 후 유지 시간(초). 예) --behavior-hold fall=20 (기본 fall=10, lie_down=5, get_up=5)")
    p.add_argument("--result-topic", default=None,
                   help="백엔드 형식(방별 present/activity)의 최종 결과를 발행할 주제. 예: home/edge/result. 생략하면 발행 안 함")
    p.add_argument("--result-valid-sec", type=int, default=5, help="결과 메시지의 validSec (기본 5)")
    p.add_argument("--model-version", default=None, help="결과 메시지의 modelVersion (기본: 모델 지문 조합)")
    p.add_argument("--log-dir", default=str(SCRIPT_DIR / "logs"), help="CSV 로그 저장 폴더")
    # --- 재실 유지 단계 (presence_tracker.py) ---
    p.add_argument("--no-hold", action="store_true", help="재실 유지 끄기 (엔진 결과를 그대로 출력)")
    p.add_argument("--hold-room", type=float, default=7 * 60, help="방 최대 유지 시간(분), 기본 420")
    p.add_argument("--hold-toilet", type=float, default=30, help="화장실 최대 유지 시간(분), 기본 30")
    p.add_argument("--hold-kitchen", type=float, default=20, help="부엌 최대 유지 시간(분), 기본 20")
    p.add_argument("--enter-conf", type=float, default=0.85, help="유지 시작에 필요한 신뢰도")
    p.add_argument("--enter-sec", type=int, default=3, help="유지 시작에 필요한 연속 초 수")
    p.add_argument("--release-empty", type=int, default=None,
                   help="(선택) empty 가 이 초 수만큼 연속이면 유지 해제. 기본: 사용 안 함")
    return p.parse_args()


def main():
    args = parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    from mqtt_util import DEFAULT_PREFIX, MqttLink, topic_features, topic_state, topic_truth
    prefix = args.prefix or DEFAULT_PREFIX
    topic_observed = f"{prefix}/observed"     # 유지 없이 '이번 초에 관측된 것' (디버깅·참고용)

    if not os.path.exists(args.model):
        raise SystemExit(f"[오류] 모델 파일이 없습니다: {args.model}  (--model 로 경로를 지정하세요)")
    engine = OccupancyEngine(args.model, theta=args.theta, switch_k=args.switch, use_ood=not args.no_ood)
    nodes = engine.locs
    collector = FeatureCollector(nodes)
    os.makedirs(args.log_dir, exist_ok=True)
    tracker = None if args.no_hold else PresenceTracker(
        max_hold_sec={"room": args.hold_room * 60, "toilet": args.hold_toilet * 60,
                      "kitchen": args.hold_kitchen * 60},
        enter_conf=args.enter_conf, enter_sec=args.enter_sec, release_empty_sec=args.release_empty,
        state_path=os.path.join(args.log_dir, "presence_state.json"))   # 재시작 대비 상태 저장

    # --- CSV 로그 ---
    os.makedirs(args.log_dir, exist_ok=True)
    log_path = os.path.join(args.log_dir, f"occupancy_{datetime.now():%Y%m%d_%H%M%S}.csv")
    log_f = open(log_path, "w", newline="", encoding="utf-8")
    log_w = csv.writer(log_f)
    # location / location_confidence / reason = 최종 결과 (발행하는 값)
    # observed_* = 엔진이 이번 초에 실제로 관측한 값 (유지 적용 전)
    log_w.writerow(["time", "location", "location_confidence", "reason", "source", "last_seen",
                    "observed_location", "observed_confidence", "observed_reason"]
                   + [f"p_{lb}" for lb in engine.labels] + ["ood_score"]
                   + [f"{n}_{k}" for n in nodes for k in ("status", "rate_hz", "proc_ms")] + ["truth"])

    # --- MQTT ---
    link = MqttLink(args.broker, args.mqtt_port, client_id=f"occupancy-server-{os.getpid()}")
    if args.combined_topic:
        link.subscribe(args.combined_topic, collector.on_combined)     # 백엔드가 묶은 주제
        input_topic = args.combined_topic
    else:
        input_topic = args.features_topic or topic_features(prefix)
        link.subscribe(input_topic, collector.on_features)             # Pi 가 보내는 개별 주제
    state_topic = args.state_topic or topic_state(prefix)
    link.subscribe(topic_truth(prefix), collector.on_truth)
    link.start()

    # --- 행동 추론 (선택) ---
    beh = None
    if args.behavior_model and not args.no_behavior:
        if not os.path.exists(args.behavior_model):
            raise SystemExit(f"[오류] 행동 모델 파일이 없습니다: {args.behavior_model}  (--no-behavior 로 끌 수 있음)")
        from behavior_engine import BehaviorEngine, BehaviorRunner
        def kv(items, cast):
            out = {}
            for it in items:
                k, _, v = it.partition("=")
                out[k.strip()] = cast(v)
            return out
        beh_engine = BehaviorEngine(
            args.behavior_model, nodes=nodes, use_ood=not args.behavior_no_ood, settle_sec=args.behavior_settle,
            theta=kv(args.behavior_theta, float), confirm_k=kv(args.behavior_confirm, int),
            hold_sec=kv(args.behavior_hold, float))
        beh = BehaviorRunner(beh_engine, link, prefix=args.behavior_prefix, log_dir=args.log_dir)
    result_builder = None
    if args.result_topic:
        from result_adapter import BackendResultBuilder
        mv = args.model_version or f"occ-{engine.cfg_hash}" + (f"+beh-{beh.engine.cfg_hash}" if beh is not None else "")
        result_builder = BackendResultBuilder(model_version=mv, valid_sec=args.result_valid_sec)
        print(f"백엔드 형식 결과 발행: {args.result_topic} (방별 3건/초, modelVersion={mv}, validSec={args.result_valid_sec})")
    print(f"구독: {input_topic}  →  발행: {state_topic} (최종), {topic_observed} (관측)"
          f"  |  로그: {log_path}")
    print("재실 유지: " + ("꺼짐" if tracker is None else
          f"방 {args.hold_room:g}분 / 화장실 {args.hold_toilet:g}분 / 부엌 {args.hold_kitchen:g}분, "
          f"시작 조건 신뢰도 ≥ {args.enter_conf} × {args.enter_sec}초"))
    print("시각      장소     신뢰도 이유                      | 노드 상태")

    last_skew_check = time.time()
    try:
        while running:
            now = time.time()
            for t_end, msgs in collector.pop_ready(now, args.deadline):
                res = engine.step(t_end, msgs)
                beh_res = None
                if beh is not None:                            # 행동 추론은 매초 (every 와 무관: 낙상 알림 지연 방지)
                    beh_res = beh.step(t_end, msgs)
                o, d = res["output"], res["debug"]             # o = 이번 초 관측 결과
                # 재실 유지 단계: 관측 결과 → 최종 결과 (유지 꺼짐이면 그대로)
                final = tracker.update(t_end, o) if tracker else dict(o, source="observed", observed=o["location"])
                # 판단은 매초 하고, 내보내기만 every 초마다
                if t_end % args.every == 0:
                    link.publish(state_topic, final, retain=True)
                    link.publish(topic_observed, o)
                    if result_builder is not None:
                        for rmsg in result_builder.build(t_end, final, None if beh_res is None else beh_res["outputs"]):
                            link.publish(args.result_topic, rmsg)
                    print(fmt_console(res, final, nodes))
                truth = collector.truth_at(t_end)
                probs = d["probs"] or {}
                log_w.writerow([final["time"], final["location"], final["location_confidence"],
                                final.get("reason", ""), final["source"], final.get("last_seen", ""),
                                o["location"], o["location_confidence"], o.get("reason", "")]
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
        if beh is not None:
            beh.close()
        print(f"\n종료. 로그: {log_path}")


if __name__ == "__main__":
    main()
