# csi_serial_logger.py
"""
ESP32 CSI 시리얼 수집기
=======================

바뀐 점
  - 각 행 맨 앞에 PC 시각(host_timestamp)을 기록 → 노드 3개를 시간 기준으로 정확히 맞출 수 있음
  - 파일을 학습 코드가 바로 읽는 이름으로 저장 → 수동 이름 변경 불필요
      dataset/{라벨}/{라벨}_{장소}_{세션}.csv   예) dataset/room/room_r3_20260930_143000.csv
  - 세션 이름 = 시작 예약 시각 → 3개 노드에 같은 --start-at 을 주면 세션 이름이 자동으로 같아짐
  - 디스크 flush 를 1초에 한 번만 → 고속 수신 중 패킷 누락 위험 감소
  - 종료 시 실제 수신 속도(Hz)와 MAC 분포 출력 → 데이터 품질 바로 확인
  - [10/02 수정] 대기하는 동안에도 시리얼을 계속 읽어서 버림
      예전에는 대기 중 읽지 않아서 USB/OS 버퍼에 옛날 패킷이 수십 초 분량 쌓였고,
      녹화 시작과 동시에 한꺼번에 쏟아져 들어와 Hz가 부풀어 보였다 (예: 실제 26Hz → 45Hz).
  - [10/02 수정] 한 줄씩이 아니라 '덩어리'로 읽음
      pyserial 의 readline() 은 내부에서 1바이트씩 읽어서 느리다.
      라즈베리파이처럼 느린 기기에서는 다 못 읽어서 줄이 잘리거나 빠질 수 있다.

사용 예 (노드 3개를 동시에 시작, 터미널 3개에서 각각 실행)
  python csi_serial_logger.py --port /dev/cu.usbmodem1101 --label room --loc r2  --start-at 14:30:00
  python csi_serial_logger.py --port /dev/cu.usbmodem1201 --label room --loc r3  --start-at 14:30:00
  python csi_serial_logger.py --port /dev/cu.usbmodem1301 --label room --loc r4  --start-at 14:30:00

※ 노드를 서로 다른 컴퓨터에서 기록한다면 컴퓨터 시계가 맞아 있어야 한다
  (macOS/Windows 자동 시간 동기화 켜 두기). 한 컴퓨터에서 3개를 돌리면 신경 쓸 필요 없음.
"""

import argparse
import csv
import os
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

import serial

# train_multizone_model.py / wifi_occupancy_pipeline.py 의 값과 똑같이 유지할 것
LABELS = ["empty", "room", "kitchen", "toilet"]
LOCATION_CODES = ["r2", "r3", "r4"]    # r2: 부엌, r3: 방, r4: 화장실

DEFAULT_PORT = "/dev/ttyACM0"
BAUD_RATE = 921600
DEFAULT_DURATION = 60        # 초. 긴 윈도우(10초)를 쓰므로 30초보다 길게 모으는 것을 권장
WARMUP_SEC = 1.0             # 녹화 직전에 읽고 버리는 시간 (포트에 남아 있던 데이터 비우기)
DATASET_ROOT = "dataset"
FLUSH_INTERVAL_SEC = 1.0     # 디스크 반영 주기

# 첫 열 host_timestamp 가 새로 추가됨. 나머지 6개는 ESP32가 보내는 그대로.
CSV_HEADER = ["host_timestamp", "local_timestamp", "data", "rssi", "mac", "first_word", "len"]

running = True


def signal_handler(sig, frame):
    """Ctrl+C 를 누르면 루프를 멈추고 파일을 정상적으로 닫는다."""
    global running
    running = False
    print("\n중지 요청 받음...")


def parse_args():
    p = argparse.ArgumentParser(description="ESP32 CSI 수집기")
    p.add_argument("--port", default=DEFAULT_PORT, help="시리얼 포트")
    p.add_argument("--label", required=True, choices=LABELS, help="이번 녹화의 정답 라벨")
    p.add_argument("--loc", required=True, choices=LOCATION_CODES, help="이 ESP32가 설치된 장소 코드")
    p.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="녹화 시간(초)")
    p.add_argument("--start-at", default=None, help="시작 예약 시각 HH:MM:SS (생략하면 즉시 시작)")
    p.add_argument("--session", default=None, help="세션 이름 직접 지정 (생략하면 시작 시각으로 자동)")
    p.add_argument("--root", default=DATASET_ROOT, help="데이터셋 폴더")
    return p.parse_args()


def resolve_start_time(start_at):
    """
    'HH:MM:SS' → 오늘 또는 내일의 datetime.
    이미 12시간 넘게 지난 시각이면 '내일'로 본다. (예: 23:58에 00:05 입력 → 내일 00:05)
    조금 지난 시각이면 오늘 그 시각 그대로 두고, 즉시 시작한다.
    """
    if start_at is None:
        return None
    now = datetime.now()
    target = datetime.strptime(start_at, "%H:%M:%S").replace(
        year=now.year, month=now.month, day=now.day)
    if target < now - timedelta(hours=12):
        target += timedelta(days=1)
    return target


class LineReader:
    """
    시리얼에서 '그때 와 있는 만큼' 한꺼번에 읽고, 줄바꿈 기준으로 잘라서 돌려준다.
    줄 끝이 아직 안 온 마지막 조각은 다음 읽기 때까지 들고 있다가 이어 붙인다.
    """

    def __init__(self, ser):
        self.ser = ser
        self.buf = bytearray()

    def read_lines(self):
        # in_waiting = 이미 도착해 있는 바이트 수. 0이면 1바이트를 최대 timeout(0.1초)까지 기다린다.
        chunk = self.ser.read(max(1, self.ser.in_waiting))
        if not chunk:
            return []
        self.buf.extend(chunk)
        *lines, rest = self.buf.split(b"\n")
        self.buf = bytearray(rest)
        return lines

    def discard_all(self):
        """지금까지 도착한 데이터를 전부 버린다."""
        self.ser.reset_input_buffer()
        self.buf.clear()


def drain_until(reader: LineReader, until_ts: float, show_countdown: bool):
    """
    until_ts(초, time.time() 기준)까지 시리얼을 '계속 읽어서 버린다'.
    그냥 sleep 으로 기다리면 그동안 들어온 패킷이 버퍼에 쌓였다가 녹화 시작 때 한꺼번에 들어온다.
    """
    last_print = 0.0
    while running:
        now = time.time()
        if now >= until_ts:
            break
        reader.read_lines()                      # 읽고 바로 버림
        if show_countdown and now - last_print >= 0.2:
            print(f"\r시작까지 {until_ts - now:6.1f}초", end="", flush=True)
            last_print = now
    reader.discard_all()


def is_csi_line(line: str) -> bool:
    """
    ESP32가 보내는 줄 중 CSI 데이터 줄만 골라낸다 (ESP-IDF 로그 등은 버림).
    예상 형식: 3995688,"[0,0,0,...]",-51,b0:38:6c:56:0d:52,0,256
    """
    line = line.strip()
    if not line or not line[0].isdigit():          # 타임스탬프(숫자)로 시작해야 함
        return False
    first_comma = line.find(",")
    if first_comma == -1 or not line[first_comma + 1:].startswith('"['):
        return False
    return ']"' in line                              # CSI 배열이 끝까지 들어왔는지


def main():
    global running
    args = parse_args()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- 저장 경로 결정 ---
    target = resolve_start_time(args.start_at)
    session = args.session or (target or datetime.now()).strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.root, args.label)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{args.label}_{args.loc}_{session}.csv")
    if os.path.exists(out_path):
        print(f"이미 같은 이름의 파일이 있습니다: {out_path}  (덮어쓰지 않고 종료)")
        sys.exit(1)

    print(f"시리얼 포트 열기: {args.port} @ {BAUD_RATE}")
    try:
        # timeout=0.1: 데이터가 없을 때 최대 0.1초만 기다림 (대기/종료 확인을 자주 하기 위해)
        ser = serial.Serial(port=args.port, baudrate=BAUD_RATE, timeout=0.1)
    except serial.SerialException as e:
        print(f"시리얼 포트를 열 수 없습니다: {e}")
        sys.exit(1)

    reader = LineReader(ser)

    # --- 시작 시각까지 대기 (기다리는 동안에도 계속 읽어서 버림) ---
    start_ts = time.time() + WARMUP_SEC
    if target is not None:
        if target.timestamp() <= time.time():
            print(f"예약 시각 {target:%H:%M:%S} 이 이미 지나서 {WARMUP_SEC:g}초 뒤 시작합니다.")
        else:
            print(f"{target:%H:%M:%S} 까지 대기합니다. (Ctrl+C 로 취소)")
            start_ts = target.timestamp()
    drain_until(reader, start_ts, show_countdown=target is not None)
    if not running:
        ser.close()
        sys.exit(0)
    print("\n녹화 시작!")

    print(f"저장 파일: {out_path}")
    print(f"녹화 시간: {args.duration:.0f}초  (Ctrl+C 로 조기 종료)\n")

    n_rows = 0
    mac_counter = Counter()
    esp_first = esp_last = None   # ESP32 시계(µs) 첫/마지막 값 → 실제 수신 속도 계산용
    start = time.time()
    last_flush = last_print = start

    try:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)

            while running:
                if time.time() - start >= args.duration:
                    break

                try:
                    raw_lines = reader.read_lines()
                except serial.SerialException as e:
                    print(f"\n시리얼 읽기 오류: {e}")
                    break
                host_ts = time.time()           # 이 덩어리를 받은 PC 시각
                # ※ 정확한 패킷 시각은 학습 코드가 ESP32 시계(local_timestamp)로 다시 계산한다.

                for raw_line in raw_lines:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not is_csi_line(line):
                        continue
                    try:
                        row = next(csv.reader([line]))
                    except Exception:
                        continue
                    if len(row) != 6:
                        continue

                    writer.writerow([f"{host_ts:.6f}"] + row)
                    n_rows += 1
                    mac_counter[row[3].strip().lower()] += 1
                    try:
                        esp = int(row[0])
                        esp_first = esp if esp_first is None else esp_first
                        esp_last = esp
                    except ValueError:
                        pass

                # 매 행마다 flush 하면 느려서 패킷을 놓칠 수 있음 → 1초에 한 번만
                if host_ts - last_flush >= FLUSH_INTERVAL_SEC:
                    f.flush()
                    last_flush = host_ts
                if host_ts - last_print >= 1.0:
                    elapsed = host_ts - start
                    print(f"\r저장 {n_rows}행 | 평균 {n_rows / elapsed:5.1f} Hz | "
                          f"남은 시간 {max(0, args.duration - elapsed):4.0f}초", end="", flush=True)
                    last_print = host_ts
    finally:
        ser.close()

    # --- 요약: 데이터 품질 바로 확인 ---
    elapsed = time.time() - start
    print("\n\n===== 녹화 요약 =====")
    print(f"파일        : {out_path}")
    print(f"총 행 수    : {n_rows}  ({elapsed:.1f}초, 평균 {n_rows / max(elapsed, 1e-9):.1f} Hz)")
    if mac_counter:
        print("MAC 분포    :")
        for mac, cnt in mac_counter.most_common(5):
            print(f"  {mac}  {cnt:6d}행 ({cnt / n_rows * 100:5.1f}%)")
        top_ratio = mac_counter.most_common(1)[0][1] / n_rows
        if top_ratio < 0.8:
            print("  [주의] 주 송신기(AP) 비율이 80% 미만입니다. 다른 기기 패킷이 많이 섞였습니다.")
    if esp_first is not None and esp_last is not None:
        esp_span = ((esp_last - esp_first) % 2 ** 32) / 1e6
        if esp_span > 0:
            print(f"ESP32 기준  : {esp_span:.1f}초 동안 수신 → 실제 수신 속도 {n_rows / esp_span:.1f} Hz")
            if esp_span > elapsed + 2:
                print("  [주의] ESP32 기준 시간이 녹화 시간보다 깁니다. 녹화 전 데이터가 밀려 들어왔습니다.\n"
                      "         (학습 코드가 자동으로 잘라내지만, 반복되면 USB 케이블/포트를 확인하세요)")
    if n_rows / max(elapsed, 1e-9) < 20:
        print("  [주의] 수신 속도가 20Hz 미만입니다. 송신 측 패킷 속도(ping 주기 등)를 확인하세요.")


if __name__ == "__main__":
    main()
