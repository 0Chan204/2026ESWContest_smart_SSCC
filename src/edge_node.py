# edge_node.py
"""
[라즈베리파이에서 실행] ESP32 CSI → 1초마다 특성 19개 → MQTT 로 서버에 전송
=============================================================================

하는 일 (1차 가공)
  ┌ 읽기 스레드 (계속) ───────────────────────────────────────────────┐
  │ 시리얼 덩어리 읽기 → CSI 줄 골라내기 → AP MAC 만 남기기 → 진폭 52개 변환 │
  │ → ESP32 시계로 시각 복원 → 최근 14초 버퍼에 쌓기                        │
  └────────────────────────────────────────────────────────────────┘
  ┌ 메인 루프 (매 정수 초 T + 약 0.45~1.0초) ──────────────────────────┐
  │ 버퍼 → 학습 때와 똑같은 전처리 → T 에서 끝나는 윈도우의 특성 19개       │
  │ → 메시지 1개 발행 (데이터가 나빠도 상태를 담아 '매초' 보냄)             │
  └────────────────────────────────────────────────────────────────┘
  T 뒤를 기다리는 이유: 필터(Hampel·Savitzky-Golay)는 T '뒤의' 샘플 몇 개까지 봐야
  학습 때와 같은 값이 나온다. 그래서 최소 0.3초를 기다린 뒤, T 이후 0.4초 분량의 패킷이
  실제로 도착했는지 확인하고 계산한다. USB 읽기가 밀려 아직 안 왔으면 최대 1.0초까지 더 기다린다.
  (10/08: 고정 0.3초만 기다렸을 때 읽기 지연이 큰 노드에서 특성이 학습과 어긋나는 문제를 고침)

보내는 메시지 (주제: wifi/occupancy/features/{node})
  {"v": 1, "node": "r3", "t_end": 1790000494, "status": "ok",
   "features": [19개], "quality": {"rate_hz": 25.9, "rssi": -50.2, "proc_ms": 85},
   "cfg": "4acc5fe4"}
  status : ok / warming_up(버퍼가 덜 참) / gap(윈도우 안에 패킷 끊김) / no_csi(ESP32 데이터 없음)
           ok 가 아니면 features 는 null

실행 예 (Pi 에서, 이 파일이 있는 폴더로 이동한 뒤)
  python3 edge_node.py --node r3 --broker 192.168.0.10
  python3 edge_node.py --node r3 --broker 192.168.0.10 --port /dev/ttyUSB0
  python3 edge_node.py --node r3 --broker 192.168.0.10 --record raw_r3.csv   # 원본도 저장(디버깅/추가 학습용)

필요한 파일 (같은 폴더): edge_node.py, wifi_occupancy_pipeline.py, csi_serial_logger.py,
                        mqtt_util.py, edge_config.json(학습 PC 에서 만든 것)
"""

import argparse
import csv
import json
import os
import signal
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime

import numpy as np

from wifi_occupancy_pipeline import (
    FEATURE_NAMES, LOCATION_CODES, CSIDataProcessor, OnlineClock,
    config_from_dict, make_config_hash, parse_csi_amplitude,
)

MESSAGE_VERSION = 1      # 메시지 형식 버전. 필드를 바꾸면 서버와 함께 올릴 것
NO_CSI_SEC = 2.0         # 이 시간 동안 패킷이 하나도 없으면 status = no_csi
AUTO_MAC_PACKETS = 50    # AP MAC 자동 선택 시, 처음 이만큼 받아 보고 가장 많은 MAC 으로 고정
GUARD_SEC = 0.4          # T 이후 이만큼의 패킷이 도착해야 계산
                         #   T 의 값은 SG(뒤로 3샘플=0.12초) → 그 샘플들의 보간(다음 패킷) → 그 패킷들의
                         #   Hampel(뒤로 3패킷) 순으로 이어져서, 최대 약 0.35초 뒤 패킷까지 영향을 받음
MAX_WAIT_SEC = 1.0       # 그래도 안 오면 T + 이 시간에는 있는 데이터로 계산

running = True


def _stop(sig, frame):
    global running
    running = False


# ==========================================================
# 1. 1차 가공 핵심 (시리얼/MQTT 와 무관 → replay_test.py 도 그대로 사용)
# ==========================================================

class EdgeProcessor:
    """
    노드 1개의 실시간 처리기.
      add_row(host_ts, row)  : ESP32 한 줄(6개 값)을 받을 때마다 호출
      compute(T)             : 시각 T 에서 끝나는 윈도우의 메시지(dict)를 만들어 돌려줌
    """

    def __init__(self, node: str, edge_cfg: dict, log=print):
        self.node = node
        self.log = log
        self.cfg = config_from_dict(edge_cfg["processing_config"])
        self.processor = CSIDataProcessor(self.cfg)

        # 이 Pi 의 코드로 계산한 설정 지문. 학습 PC 가 만든 값과 다르면 코드/설정이 어긋난 것
        self.cfg_hash = make_config_hash(self.cfg)
        expected = edge_cfg.get("cfg_hash")
        if expected and expected != self.cfg_hash:
            self.log(f"[경고] 설정 지문 불일치! edge_config.json={expected}, 이 Pi 계산값={self.cfg_hash}\n"
                     f"       → 학습 PC 와 wifi_occupancy_pipeline.py 버전이 다릅니다. 같은 파일로 맞추세요.\n"
                     f"         (이대로면 서버가 이 노드의 데이터를 config_mismatch 로 거부합니다)")

        # 정수 초마다 윈도우가 끝나려면 fs × step 이 정수여야 함 (예: 25Hz × 1초 = 25)
        if abs(self.cfg.fs * self.cfg.step_sec - round(self.cfg.fs * self.cfg.step_sec)) > 1e-9:
            raise ValueError(f"fs({self.cfg.fs}) × step_sec({self.cfg.step_sec}) 가 정수가 아닙니다.")

        self.target_mac = ((edge_cfg.get("target_macs") or {}).get(node) or "").lower() or None
        self.mac_votes = Counter()
        self.pending = []                 # AP MAC 을 정하는 동안 받은 패킷 (정해지면 다시 처리)
        self.clock = OnlineClock()
        # 버퍼 길이: 긴 윈도우(10초) + 앞쪽 필터 여유(1초) + 뒤쪽 지연·여유(3초)
        self.buffer_sec = self.cfg.long_window_sec + 4.0
        self.buf = deque()                # (t, amp(52,), rssi)  t = 도착 순간의 offset 으로 계산한 시각
        self.last_rx_host = None          # 마지막으로 패킷을 받은 Pi 시각
        self.lock = threading.Lock()
        self.stats = Counter()

    # ---------- 패킷 받기 ----------
    def add_row(self, host_ts: float, row):
        """row = ESP32 가 보낸 6개 값 [local_timestamp, data, rssi, mac, first_word, len]"""
        if len(row) != 6:
            self.stats["bad_row"] += 1
            return
        local_ts, data, rssi, mac, first_word, _ = row
        mac = mac.strip().lower()

        # AP MAC 자동 선택: 처음 50개를 보고 가장 많이 나온 MAC 으로 고정
        # (그동안 받은 패킷은 버리지 않고 보관했다가, MAC 이 정해지면 순서대로 다시 처리)
        if self.target_mac is None:
            self.mac_votes[mac] += 1
            self.pending.append((host_ts, row))
            if sum(self.mac_votes.values()) >= AUTO_MAC_PACKETS:
                self.target_mac, n = self.mac_votes.most_common(1)[0]
                self.log(f"[{self.node}] AP MAC 자동 선택: {self.target_mac} "
                         f"({n}/{AUTO_MAC_PACKETS}개). 고정하려면 edge_config.json 의 target_macs 에 적으세요.")
                pending, self.pending = self.pending, []
                for h, r in pending:
                    self.add_row(h, r)
            return
        if mac != self.target_mac:
            self.stats["other_mac"] += 1
            return

        try:
            raw_us = int(local_ts)
            rssi = float(rssi)
        except ValueError:
            self.stats["bad_row"] += 1
            return
        amp = parse_csi_amplitude(data, first_word.strip() not in ("", "0"))
        if amp is None:
            self.stats["bad_csi"] += 1
            return

        with self.lock:
            esp_sec, reset = self.clock.esp_seconds(raw_us)
            if reset:   # ESP32 재부팅 → 옛 데이터와 시계가 이어지지 않으므로 버퍼를 비움
                self.buf.clear()
                self.stats["esp_reset"] += 1
                self.log(f"[{self.node}] ESP32 시계 리셋 감지 (재부팅?) → 버퍼 초기화, 10초 뒤 정상화")
            self.clock.observe(host_ts, esp_sec)
            # 이 패킷의 시각 = ESP32 시계 + '지금까지 받은 데이터 기준' offset (학습 코드와 같은 계산)
            t_pkt = esp_sec + self.clock.offset
            self.buf.append((t_pkt, amp, rssi))
            self.last_rx_host = host_ts
            while self.buf and self.buf[0][0] < t_pkt - self.buffer_sec:
                self.buf.popleft()
            self.stats["ok"] += 1

    # ---------- 계산해도 되는지 ----------
    def ready(self, T: int, now: float, min_delay: float = 0.3) -> bool:
        """
        T 윈도우를 계산할 준비가 됐는지.
          - 최소 T + min_delay 까지는 기다리고
          - 그 뒤로는 'T + GUARD_SEC 이후 시각의 패킷'이 들어왔으면 바로 계산
          - 끝까지 안 오면 T + MAX_WAIT_SEC 에 그냥 계산 (끊김이면 gap/no_csi 로 보고됨)
        """
        if now < T + min_delay:
            return False
        if now >= T + MAX_WAIT_SEC:
            return True
        with self.lock:
            return bool(self.buf) and self.buf[-1][0] >= T + GUARD_SEC

    # ---------- 1초마다 메시지 만들기 ----------
    def compute(self, T: int, now: float = None) -> dict:
        """
        T: 윈도우가 끝나는 시각(정수 초, 유닉스 시간). 보통 '현재 시각 − 0.3초'를 내림한 값.
        now: 현재 Pi 시각 (테스트에서 과거 데이터를 재생할 때 바꿔 넣으려고 인자로 둠)
        """
        start = time.perf_counter()
        now = time.time() if now is None else now
        cfg = self.cfg
        msg = {"v": MESSAGE_VERSION, "node": self.node, "t_end": int(T), "status": None,
               "features": None, "quality": {"rate_hz": None, "rssi": None, "proc_ms": None},
               "cfg": self.cfg_hash}

        with self.lock:                                  # 읽기 스레드와 겹치지 않게 복사만 빨리
            snap = list(self.buf)
            last_rx = self.last_rx_host

        if not snap or last_rx is None or now - last_rx > NO_CSI_SEC:
            msg["status"] = "no_csi"
        else:
            # 각 패킷의 시각은 받을 때 이미 계산해 둠 (학습 때 reconstruct_time 과 같은 계산)
            t = np.fromiter((p[0] for p in snap), dtype=np.float64, count=len(snap))
            amp = np.vstack([p[1] for p in snap])
            rssi = np.fromiter((p[2] for p in snap), dtype=np.float64, count=len(snap))

            # 품질 정보 (판단에 직접 쓰는 건 rate_hz, rssi 는 진단용)
            in_long = (t > T - cfg.long_window_sec) & (t <= T)
            in_short = (t > T - cfg.short_window_sec) & (t <= T)
            msg["quality"]["rate_hz"] = round(float(in_long.sum() / cfg.long_window_sec), 1)
            if in_short.any():
                msg["quality"]["rssi"] = round(float(rssi[in_short].mean()), 1)

            if t[0] > T - cfg.long_window_sec + 1.0 / cfg.fs:
                msg["status"] = "warming_up"             # 10초 윈도우를 채울 만큼 아직 안 쌓임
            else:
                # 필요한 구간(긴 윈도우 + 앞 1초 여유)만 잘라서 학습 때와 같은 함수로 처리
                keep = t >= T - cfg.long_window_sec - 1.0
                end_tick = int(round(T * cfg.fs))
                feats, ends = self.processor.process_stream(
                    t[keep], amp[keep], rssi[keep], target_end_ticks={end_tick})
                if len(feats):
                    msg["status"] = "ok"
                    # 소수 6자리 유효숫자로 반올림 → 메시지 크기 절약 (예측에는 영향 없음)
                    msg["features"] = [float(f"{v:.6g}") for v in feats[0]]
                else:
                    msg["status"] = "gap"                # 윈도우 안에 0.5초 넘는 패킷 공백

        msg["quality"]["proc_ms"] = round((time.perf_counter() - start) * 1000, 1)
        return msg


# ==========================================================
# 2. 시리얼 읽기 스레드
# ==========================================================

def serial_reader(port: str, proc: EdgeProcessor, record_path: str = None):
    """
    ESP32 시리얼을 계속 읽어서 proc.add_row() 로 넘긴다. 연결이 끊기면 3초 뒤 다시 연다.
    record_path 가 있으면 csi_serial_logger.py 와 같은 형식의 CSV 로 원본도 저장.
    """
    import serial
    from csi_serial_logger import BAUD_RATE, CSV_HEADER, LineReader, is_csi_line

    rec_f = rec_w = None
    if record_path:
        new = not os.path.exists(record_path)
        rec_f = open(record_path, "a", newline="", encoding="utf-8")
        rec_w = csv.writer(rec_f)
        if new:
            rec_w.writerow(CSV_HEADER)

    last_flush = time.time()
    while running:
        try:
            ser = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=0.1)
        except serial.SerialException as e:
            print(f"[{proc.node}] 시리얼 열기 실패: {e} → 3초 뒤 재시도")
            time.sleep(3)
            continue
        reader = LineReader(ser)
        reader.discard_all()                     # 열기 전에 쌓여 있던 옛 데이터 버리기
        print(f"[{proc.node}] 시리얼 연결: {port}")
        try:
            while running:
                lines = reader.read_lines()
                host_ts = time.time()            # 이 덩어리를 받은 Pi 시각
                for raw in lines:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not is_csi_line(line):
                        continue
                    try:
                        row = next(csv.reader([line]))
                    except Exception:
                        continue
                    proc.add_row(host_ts, row)
                    if rec_w is not None and len(row) == 6:
                        rec_w.writerow([f"{host_ts:.6f}"] + row)
                if rec_f is not None and host_ts - last_flush > 1.0:
                    rec_f.flush()
                    last_flush = host_ts
        except serial.SerialException as e:
            print(f"[{proc.node}] 시리얼 오류: {e} → 다시 연결합니다")
        finally:
            ser.close()
        time.sleep(1)
    if rec_f:
        rec_f.close()


# ==========================================================
# 3. 실행
# ==========================================================

def parse_args():
    p = argparse.ArgumentParser(description="Pi 용 CSI 1차 가공 + MQTT 전송")
    p.add_argument("--node", required=True, choices=LOCATION_CODES, help="이 Pi 가 맡은 노드 (r2/r3/r4)")
    p.add_argument("--broker", required=True, help="MQTT 브로커(맥북/통합 서버) IP 주소")
    p.add_argument("--mqtt-port", type=int, default=1883, help="MQTT 포트 (기본 1883)")
    p.add_argument("--port", default="/dev/ttyUSB0",
                   help="ESP32 시리얼 포트 (기본 /dev/ttyUSB0. ls /dev/ttyUSB* /dev/ttyACM* 로 확인)")
    p.add_argument("--config", default="edge_config.json", help="학습 PC 에서 만든 설정 파일")
    p.add_argument("--prefix", default=None, help="MQTT 주제 앞부분 (기본 wifi/occupancy)")
    p.add_argument("--delay", type=float, default=0.3, help="윈도우 끝(T) 이후 최소로 기다리는 시간(초)")
    p.add_argument("--every", type=int, default=1, choices=[1, 2],
                   help="몇 초마다 보낼지. Pi 처리 시간이 계속 500ms 를 넘으면 2 로")
    p.add_argument("--record", default=None, help="원본 CSI 를 이 CSV 파일에도 저장")
    p.add_argument("--quiet", action="store_true", help="콘솔 출력을 10초에 한 번으로 줄임")
    return p.parse_args()


def main():
    args = parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    from mqtt_util import DEFAULT_PREFIX, MqttLink, topic_features
    prefix = args.prefix or DEFAULT_PREFIX

    # --- 설정 파일 (경로는 이 스크립트 위치 기준으로도 찾아 줌) ---
    cfg_path = args.config
    if not os.path.exists(cfg_path):
        alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.config)
        if os.path.exists(alt):
            cfg_path = alt
        else:
            sys.exit(f"[오류] 설정 파일이 없습니다: {args.config}\n"
                     f"       학습 PC 에서 train_multizone_model.py 를 실행하면 edge_config.json 이 생깁니다.\n"
                     f"       그 파일을 이 폴더로 복사하세요.")
    with open(cfg_path, encoding="utf-8") as f:
        edge_cfg = json.load(f)
    if edge_cfg.get("feature_names") and edge_cfg["feature_names"] != FEATURE_NAMES:
        print("[경고] edge_config.json 의 특성 목록이 이 Pi 의 코드와 다릅니다. 파일 버전을 확인하세요.")

    proc = EdgeProcessor(args.node, edge_cfg)
    print(f"노드 {args.node} | 설정 지문 {proc.cfg_hash} | fs {proc.cfg.fs:g}Hz | "
          f"{args.every}초마다 전송 → {args.broker}:{args.mqtt_port} ({topic_features(prefix, args.node)})")

    link = MqttLink(args.broker, args.mqtt_port, client_id=f"edge-{args.node}-{os.getpid()}")
    link.start()

    reader = threading.Thread(target=serial_reader, args=(args.port, proc, args.record), daemon=True)
    reader.start()

    # --- 메인 루프: 매 'T + delay' 시각에 T 에서 끝나는 윈도우를 계산해서 전송 ---
    def aligned_next(now):
        T = int(now - args.delay) + 1
        return T + (-T % args.every)            # every=2 면 짝수 초에만

    wait_ms = deque(maxlen=60)                  # T 이후 실제로 기다린 시간 (진단용)

    next_T = aligned_next(time.time())
    last_print, slow_count = 0.0, 0
    while running:
        # T + delay 이후, T 뒤 패킷이 충분히 도착할 때까지(최대 T + 1초) 기다림
        while running and not proc.ready(next_T, time.time(), args.delay):
            time.sleep(0.02)
        if not running:
            break

        wait_ms.append((time.time() - next_T) * 1000)
        msg = proc.compute(next_T)
        link.publish(topic_features(prefix, args.node), msg)

        q = msg["quality"]
        slow_count = slow_count + 1 if (q["proc_ms"] or 0) > 500 else 0
        if slow_count == 10:
            print("[주의] 처리 시간이 10초 연속 500ms 를 넘었습니다. --every 2 로 실행해 보세요.")
        now = time.time()
        if not args.quiet or now - last_print >= 10:
            mqtt_txt = "MQTT ok" if link.connected.is_set() else "MQTT 끊김"
            print(f"{datetime.fromtimestamp(next_T):%H:%M:%S} {args.node} {msg['status']:<10} "
                  f"{q['rate_hz'] if q['rate_hz'] is not None else '-':>5}Hz "
                  f"rssi {q['rssi'] if q['rssi'] is not None else '-':>6} "
                  f"처리 {q['proc_ms']:6.1f}ms 대기 {wait_ms[-1]:4.0f}ms | {mqtt_txt}")
            last_print = now

        next_T += args.every
        if time.time() > next_T + MAX_WAIT_SEC + args.every:   # 너무 밀렸으면 따라잡지 말고 현재로 점프
            skipped = aligned_next(time.time()) - next_T
            print(f"[주의] 처리가 밀려 {skipped}초를 건너뜁니다.")
            next_T = aligned_next(time.time())

    print("\n종료 중...")
    link.stop()
    s = proc.stats
    print(f"받은 패킷: 사용 {s['ok']} / 다른 MAC {s['other_mac']} / 깨진 줄 {s['bad_row'] + s['bad_csi']}"
          f" / ESP32 리셋 {s['esp_reset']}")


if __name__ == "__main__":
    main()
