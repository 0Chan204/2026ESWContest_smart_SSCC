# 실행 가이드 — 재실 감지 + 행동 추론 (Pi ×3 → MQTT → 서버 → 백엔드)

## 1. 전체 구조

```
ESP32 ─시리얼─▶ Pi (edge_node.py)  ──MQTT──▶ 백엔드 ──MQTT──▶ 우리 서버 (occupancy_server.py) ──MQTT──▶ 백엔드
 (노드별 1대)    특징값만 계산                 3개 노드 묶음        재실 판단 + 행동 판단                 최종 결과 → DB
                 home/<방>/edge/<rN>/features  home/edge/combined   → 방별 3건                           home/edge/result
```

- Pi는 **판단하지 않는다.** 1초마다 특징값(재실 19개 + 행동 31개)을 한 메시지로 보낸다.
- 백엔드가 3개 노드의 최신 메시지를 묶어 `home/edge/combined`로 1초마다 보낸다.
- 우리 서버가 묶음을 받아 **재실 + 행동을 모두 판단**하고 `home/edge/result`에 방별 JSON 3건을 발행한다. 백엔드가 DB에 저장한다.

### 노드 ↔ 방 대응

| 방 | 백엔드 표기 | 우리 내부 노드 | Pi 발행 토픽 |
|---|---|---|---|
| room (방) | r1 | r3 | `home/room/edge/r1/features` |
| kitchen (부엌) | r2 | r2 | `home/kitchen/edge/r2/features` |
| toilet (화장실) | r3 | r4 | `home/toilet/edge/r3/features` |

- 서버는 **방 이름(room/kitchen/toilet)** 으로 노드를 정한다. 메시지 안의 `node` 값(r1/r3 등)은 판단에 쓰이지 않는다.
- 모델이 노드 순서·이름(r2, r3, r4)으로 학습되어 있으므로 **내부 이름은 바꾸지 않는다.** 이름만 맞추려면 Pi에 `--wire-id`.

---

## 2. 파일 배치

### Pi (노드마다 동일, `--node`만 다름)

| 파일 | 설명 |
|---|---|
| `edge_node.py` | 실행 파일 |
| `wifi_occupancy_pipeline.py` | 재실 특징 계산 (기존) |
| `behavior_pipeline.py` | 행동 특징 계산 |
| `mqtt_util.py` | MQTT 연결 |
| `csi_serial_logger.py` | ESP32 시리얼 읽기 (기존, 우리 쪽 파일) |
| `edge_config.json` | 재실 설정 (재실 학습 시 생성) |
| `behavior_config.json` | 행동 설정 (`train_behavior_model.py`가 생성) |

설치: `pip install paho-mqtt numpy scipy pyserial` (scikit-learn 불필요)

### 서버

| 파일 | 설명 |
|---|---|
| `occupancy_server.py` | 실행 파일 |
| `occupancy_engine.py` | 재실 판단 엔진 |
| `behavior_engine.py` | 행동 판단 엔진 |
| `result_adapter.py` | 백엔드 결과 형식 변환 |
| `presence_tracker.py` | 재실 유지 단계 (기존) |
| `wifi_occupancy_pipeline.py`, `behavior_pipeline.py`, `mqtt_util.py` | 공용 |
| `multizone_occupancy_svm.pkl` | 재실 모델 |
| `behavior_svm.pkl` | 행동 모델 |

설치: `pip install paho-mqtt numpy scipy scikit-learn pandas`
(학습할 때 쓴 scikit-learn 버전과 같은 버전을 쓸 것 — pkl 로드 경고/오류 방지)

---

## 3. 실행 순서

**① MQTT 브로커(백엔드 쪽) 확인** — 브로커 IP와 포트(기본 1883), 서버·Pi 모두 같은 네트워크에서 접속 가능해야 한다.

**② 서버**
```bash
python occupancy_server.py --broker <브로커IP> \
    --model multizone_occupancy_svm.pkl --behavior-model behavior_svm.pkl \
    --combined-topic home/edge/combined --result-topic home/edge/result
```
시작 로그에 `[엔진] 모델 로드 … cfg 67a75326`, `[행동 엔진] … cfg f6ef98a2`, `백엔드 형식 결과 발행: home/edge/result`가 보여야 한다.
`--combined-topic`을 주면 Pi 개별 토픽은 구독하지 않는다.

**③ Pi 3대** (각각)
```bash
# 방
python edge_node.py --node r3 --wire-id r1 --broker <브로커IP> --port /dev/ttyUSB0 \
    --config edge_config.json --behavior-config behavior_config.json \
    --topic home/room/edge/r1/features
# 부엌
python edge_node.py --node r2 --broker <브로커IP> --port /dev/ttyUSB0 \
    --config edge_config.json --behavior-config behavior_config.json \
    --topic home/kitchen/edge/r2/features
# 화장실
python edge_node.py --node r4 --wire-id r3 --broker <브로커IP> --port /dev/ttyUSB0 \
    --config edge_config.json --behavior-config behavior_config.json \
    --topic home/toilet/edge/r3/features
```
- `--port`는 `ls /dev/ttyUSB* /dev/ttyACM*`로 확인.
- 처리 시간(`proc_ms`)이 계속 500ms를 넘으면 `--every 2`. (실측: r2/r3 약 180ms, r4 약 50ms)
- 시작 후 약 6초(첫 윈도우) 동안 `warming_up`.

**④ 확인**
```bash
mosquitto_sub -h <브로커IP> -t 'home/#' -v          # 전체 흐름
mosquitto_sub -h <브로커IP> -t home/edge/result -v   # 최종 결과 (초당 3건)
```

---

## 4. 메시지 형식

### 4-1. Pi → 백엔드 (노드 메시지)
```json
{"v":1, "node":"r3", "t_end":1793083741, "status":"ok",
 "features":[… 19개 …],
 "quality":{"rate_hz":14.7, "rssi":-60.6, "proc_ms":188.4},
 "cfg":"67a75326",
 "behavior":{"status":"ok", "features":[… 31개 …], "rate_hz":14.7, "cfg":"f6ef98a2"}}
```
- `t_end`: 윈도우 끝 시각(초, 정수). 3개 노드가 같은 `t_end`끼리 한 번에 판단된다.
- `status`: `ok` / `warming_up` / `gap` / `no_csi`
- `cfg`: 설정 지문. 서버 모델과 다르면 `config_mismatch`.

### 4-2. 백엔드 → 서버 (`home/edge/combined`)
```json
{"seq":1905, "publishedAt":"…", "locations":{
   "room":   {"node": {<노드 메시지>}},
   "kitchen":{"node": {<노드 메시지>}},
   "toilet": {"node": {<노드 메시지>}} }}
```
- 방 값이 null이면 그 방은 데이터 없음으로 처리. `seq`, `publishedAt`은 사용하지 않음.
- 서버는 이미 처리한 `t_end`는 버린다(재전송 중복 방지).

### 4-3. 서버 → 백엔드 (`home/edge/result`) — **방마다 1건, 초당 3건**
```json
{"resultId":"res-20261027-000123", "observedAt":"2026-10-27T21:00:02+09:00",
 "room":"kitchen",
 "present":true, "confidence":0.91, "presenceReason":null,
 "activity":"fall", "activityConfidence":0.94, "activityReason":null,
 "modelVersion":"occ-67a75326+beh-f6ef98a2", "validSec":5}
```

| 필드 | 값 |
|---|---|
| `room` | `room` / `kitchen` / `toilet` |
| `present` | 이 방에 사람이 있으면 true, 없으면 false, **판단 불가면 null** |
| `confidence` | 재실 신뢰도(0~1). 판단 불가면 null |
| `presenceReason` | 판단 불가일 때만: `warming_up`, `node_offline`, `poor_signal`, `config_mismatch`, `low_confidence` |
| `activity` | `none` / `fall` / `lie_down` / `get_up`, **판단 불가면 null** |
| `activityConfidence` | 행동 신뢰도(0~1). 판단 불가면 null (낙상 등 이벤트 → 해당 확률, none → none 확률) |
| `activityReason` | 판단 불가일 때만: `warming_up`, `node_offline`, `poor_signal`, `config_mismatch`, `low_confidence`, `behavior_off` |
| `modelVersion` | `occ-<재실 cfg>+beh-<행동 cfg>` (`--model-version`으로 지정 가능) |
| `validSec` | 5 (`--result-valid-sec`) |
| `resultId` | `res-<날짜>-<그날 0시부터의 초×3 + 방순번(room 0, kitchen 1, toilet 2)>` |

---

## 5. 판단 조건

### 5-1. 재실 (occupancy_engine + presence_tracker)
- 3개 노드의 19개 특징 → SVM(RBF)으로 `empty / room / kitchen / toilet` 중 하나. 방 3개 결과로 변환: 해당 방만 `present=true`, 나머지 false (`empty`면 전부 false).
- 신뢰도가 임계값(θ, 기본 0.5) 미만이면 판단 불가(`low_confidence`).
- 노드 문제(판단 불가): 
  - `poor_signal`: Pi가 gap/no_csi 보고, 또는 **수신 속도 < 17.5 Hz** (fs 25 × 0.7)
  - `node_offline`: 메시지가 3초 이상 없음 (최대 2초는 직전 정상값으로 버팀)
  - `config_mismatch`: 설정 지문 불일치
  - `warming_up`: 시작 직후
- 장소 전환은 같은 결과가 연속 2초(`--switch`) 필요.
- **재실 유지(presence_tracker)**: 신뢰도 0.85 이상이 3초 연속이면 그 방을 "유지" 상태로 두고, 움직임이 없어도 방 7시간 / 화장실 30분 / 부엌 20분까지 재실로 유지. 옵션 `--hold-room/--hold-toilet/--hold-kitchen/--enter-conf/--enter-sec/--no-hold`.

### 5-2. 행동 (behavior_engine)
- 노드마다 독립 판단(31개 특징 → SVM). 클래스: `none, fall, lie_down, get_up`.
- **노드별 허용 행동**: 방(r3)은 fall/lie_down/get_up, 부엌(r2)·화장실(r4)은 fall만 (나머지는 none으로 처리).
- 발화 조건: 클래스별 임계값 θ(기본 fall 0.5, lie_down 0.82, get_up 0.7 — 학습 시 저장) 이상이 **연속 횟수** 이상 (기본 fall 1, lie_down 2, get_up 2). 학습 범위 밖(OOD) 입력은 판단 불가.
- **유지**: 한 번 발화하면 fall 10초, lie_down/get_up 5초 동안 같은 결과 유지. 직후 4초는 재발화 금지(refractory). → 낙상은 **10초 동안 `activity=fall`이 계속 나간다.** 새 이벤트 여부는 결과에 없음(백엔드가 처음 나타난 시점을 기준으로 알림 처리해야 함).
- 시작/복구 직후 8초(`--behavior-settle`)는 판단 보류(`warming_up`) — 시작 때 오탐 방지.
- 판단 불가: `none`이지만 신뢰도 0.5 미만 → `low_confidence`, 노드 문제는 재실과 동일한 이유 코드 (행동은 수신 속도 기준이 10 Hz).
- 행동 신뢰도 임계값 변경: `--behavior-theta fall=0.85`, `--behavior-confirm fall=2`, `--behavior-hold fall=20`.

### 5-3. 두 결과의 결합 규칙 (result_adapter.py)
- 재실은 방별로 `present` 계산, 행동은 **그 방 노드의 결과**를 그대로 사용.
- **사람이 없다고 판단된 방(`present=false`)에서 감지된 낙상은 무시** → `activity="none"`, `activityConfidence=null`.
  재실이 판단 불가(`present=null`)인 방의 낙상은 안전을 위해 그대로 내보낸다. (눕기/일어나기에는 적용하지 않음)

---

## 6. 주의할 점

1. **수신 속도 ≥ 17.5 Hz** — 이보다 낮으면 재실이 `poor_signal`(present=null). 공유 Wi-Fi(10대 연결)에서는 14~16 Hz까지 떨어졌고, 전용 핫스팟에서는 회복됨. 시리얼 한 줄이 약 780바이트라 115200 baud에서는 초당 약 14.8줄이 한계 → **ESP32 시리얼 baud를 올릴 수 있으면 올릴 것.** 샘플 묶음의 rate_hz는 14~15 Hz였으므로 현재 설정 그대로면 재실이 판단 불가가 된다.
2. **모델 배포 일치** — `behavior_pipeline.py`를 수정(max_gap_sec 1.0)해서 행동 설정 지문이 `f6ef98a2`로 바뀌었다. **반드시 이 파일로 행동 모델을 재학습**하고, `behavior_svm.pkl`(서버)과 `behavior_config.json`·`behavior_pipeline.py`(Pi)를 같은 버전으로 맞출 것. 다르면 전부 `config_mismatch`. 재실도 마찬가지(`edge_config.json` ↔ 재실 pkl, 지문 `67a75326`).
3. **학습 속도와 실제 속도 차이** — 행동 모델은 약 25 Hz 데이터로 학습했는데 실제가 14~15 Hz면 특징이 달라져 정확도가 떨어질 수 있다. 가능하면 수신 속도를 올리거나, 낮은 속도로 데이터를 다시 만들어 재학습.
4. **행동 정확도는 낮다** — 독립 이벤트가 낙상 4개/눕기 7개/일어나기 7개뿐이고, 장치가 바뀌면 이벤트 종류 분류가 잘 안 옮겨진다. 실사용에서 **낙상 오탐**이 나올 수 있다. 오탐이 많으면 `--behavior-theta fall=0.85 --behavior-confirm fall=2`로 보수적으로, `logs/behavior_*.csv`(p_none/p_fall/…/ood_score/rate)로 확인. 정확도를 보장하는 값이 아니므로 알림은 "의심" 수준으로 다루는 것을 권장.
5. **노드 시각 동기화** — 3개 Pi의 시계가 어긋나면 `t_end`가 맞지 않아 묶이지 않는다. Pi들 `timedatectl`/NTP 확인. 서버는 시계 어긋남을 감시해 경고를 출력한다.
6. **QoS 0 / 인증 없음** — 메시지 유실이 있을 수 있고(서버는 최대 2초까지 기다림 `--deadline`), 브로커 인증/TLS는 쓰지 않는다. 브로커가 인증을 요구하면 `mqtt_util.py` 수정 필요.
7. **재시작** — 서버를 재시작하면 재실 유지 상태와 행동 유지 상태가 초기화된다. 시작 후 약 8초는 행동이 `warming_up`.
8. **resultId** — 서버 재시작과 상관없이 같은 날 안에서 초 단위로 증가하므로 겹치지 않는다(같은 초 재발행 제외).

---

## 7. 문제 해결

| 증상 | 원인 / 조치 |
|---|---|
| 서버가 전 노드 `node_offline` | 브로커 IP 오타, 묶음 토픽 불일치, 백엔드 묶음 미발행 → `mosquitto_sub -t 'home/#' -v`로 확인 |
| `no_csi` / `gap` | ESP32 시리얼 포트, baud, 연결 상태 확인 (Pi 콘솔) |
| 전 방 `present=null`, `poor_signal` | 수신 속도 17.5 Hz 미만 (rate_hz 확인) — 위 주의 1 |
| `config_mismatch` | 모델과 Pi 설정 파일 버전 불일치 — 주의 2 |
| 낙상 오탐 | 임계값 상향, 연속 횟수 증가 — 주의 4 |
| 서버 콘솔에 "늦게 도착" 증가 | 묶음 재전송 또는 노드 지연. 결과 중복은 없음 |
| Pi `proc_ms` > 500 | `--every 2` |

## 8. 로그

- 재실: `logs/occupancy_*.csv` (최종/관측 결과, 확률, 노드 상태)
- 행동: `logs/behavior_*.csv` (행동, 신뢰도, 클래스별 확률, OOD 점수, 수신 속도)
- 상태 토픽(retained): `wifi/occupancy/state`, `wifi/occupancy/observed`, `wifi/behavior/state/<노드>`
