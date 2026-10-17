# 엣지 노드 · 최종 재실 판단 MQTT 명세 (v0.3)

각 구역의 라즈베리파이(엣지 노드)가 보낸 재실·행동 분석 결과를 서버가 하나로 합쳐 재실 판단 담당에게 전달하고,
재실 판단 담당이 만든 최종 결과를 서버가 저장하는 MQTT 규칙입니다.

```
① 엣지 노드      ── home/{구역}/edge/{노드ID}/{occupancy|activity|status} ──> 서버
② 서버           ── home/edge/combined (1초마다, 구역별 최신 메시지를 합침) ──> 재실 판단 담당
③ 재실 판단 담당 ── home/edge/result (최종 판단 결과) ──> 서버: DB 저장
④ AI 중앙 판정 엔진 ── HTTP GET /api/v1/sensing/results/latest 등 ──> 서버 (docs/AI-INTEGRATION.md)
```

**서버는 판단하지 않습니다.** 유효기간, 노드 이상, 온라인 여부 판단은 받는 쪽이 합니다.
서버는 원본 메시지를 그대로 전달하고, 수신 시각(`receivedAt`)만 붙이며, MQTT 중복 수신만 거릅니다.

토픽은 가전(인덕션·전등·정수기)과 같은 규칙 `home/{구역}/{종류}/{ID}/{메시지}`를 따릅니다.
(Edge Device 문서의 `homevis/nodes/...`는 예시였고, 이 문서의 토픽으로 확정합니다.)

## 1. 접속 정보

| 항목 | 값 |
| --- | --- |
| 브로커 | 서버 PC의 LAN IP (테스트: 맥 `ipconfig getifaddr en0`, 대회: 라즈베리파이 4 보드 IP) |
| 포트 | `1883` |
| 인증 | 없음 (시연 전에 아이디·비밀번호 추가 예정) |
| 클라이언트 ID | 노드ID 그대로 (예: `edge-02`). 노드마다 달라야 합니다 |

## 2. 토픽

| 토픽 | 방향 | 내용 | QoS | retain | 보내는 시점 |
| --- | --- | --- | --- | --- | --- |
| `home/{구역}/edge/{노드ID}/occupancy` | 노드 → 서버 | 재실 분석 결과 | 1 | false | 재실 분석을 할 때마다 |
| `home/{구역}/edge/{노드ID}/activity` | 노드 → 서버 | 행동 분석 결과 | 1 | false | 행동 분석을 할 때마다 |
| `home/{구역}/edge/{노드ID}/status` | 노드 → 서버 | 노드 상태(heartbeat) | 1 | **true** | 5초마다 + 비정상 종료 시 Last Will |
| `home/edge/combined` | 서버 → 재실 판단 담당 | 구역별 최신 메시지 묶음 (6장) | 1 | false | 1초마다 |
| `home/edge/result` | 재실 판단 담당 → 서버 | 최종 판단 결과 (7장) | 1 | false | 판단할 때마다 |

- `{구역}`: `room` / `kitchen` / `toilet` (백엔드·가전과 같은 이름)
- `{노드ID}`: `edge-01`, `edge-02`, `edge-03` (가전의 `light-01`, `water-01`과 같은 형식)
- 서버 최종 상태 토픽(예시의 `homevis/state`)은 두지 않습니다. 최종 판단은 AI 중앙 판정 엔진이
  백엔드 API(`POST /api/v1/ai/decisions`)로 보내고, 대시보드는 WebSocket으로 받습니다.

전체 토픽 한눈에 보기 (시연 구성)

```
home/room/light/light-01/{state|command|ack}             전등
home/room/edge/edge-01/{occupancy|activity|status}       방 엣지 노드
home/kitchen/induction/induction-01/{state|command|ack}  인덕션
home/kitchen/water_purifier/water-01/{state|command|ack} 정수기
home/kitchen/edge/edge-02/{occupancy|activity|status}    부엌 엣지 노드
home/toilet/edge/edge-03/{occupancy|activity|status}     화장실 엣지 노드
home/edge/combined                                       서버 → 재실 판단 담당 (합친 메시지)
home/edge/result                                         재실 판단 담당 → 서버 (최종 결과)
```

구독 예시: 엣지 노드 전체 `home/+/edge/#`, 부엌 전체(가전 + 노드) `home/kitchen/#`, 모든 메시지 `home/#`

## 3. 노드 - 구역 매핑

| 노드ID | 구역 | 토픽 앞부분 |
| --- | --- | --- |
| `edge-01` | `room` (방) | `home/room/edge/edge-01/` |
| `edge-02` | `kitchen` (부엌) | `home/kitchen/edge/edge-02/` |
| `edge-03` | `toilet` (화장실) | `home/toilet/edge/edge-03/` |

노드를 다른 구역으로 옮기면 토픽의 구역과 메시지의 `room`만 바꾸면 됩니다.

## 4. 메시지 형식 (JSON, UTF-8)

공통 필드 (occupancy · activity · status 모두)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `node` | string | 노드ID (`edge-02`) |
| `room` | string | 구역 (`kitchen`) |
| `bootId` | string | 노드 프로그램이 시작될 때마다 새로 만드는 ID. 재시작을 구분하는 용도 |
| `sentAt` | string | 보낸 시각, ISO 8601 + 시간대 (예: `2026-10-17T12:00:00.250+00:00`) |

### occupancy (재실)

```json
{
  "node": "edge-02", "room": "kitchen", "bootId": "a1b2c3d4", "seq": 1024,
  "sentAt": "2026-10-17T12:00:02.100+00:00",
  "windowStart": "2026-10-17T12:00:00.000+00:00",
  "windowEnd": "2026-10-17T12:00:02.000+00:00",
  "pOccupied": 0.87,
  "quality": 0.95,
  "modelVersion": "occ-0.1",
  "validSec": 5
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `seq` | int | 순번. 같은 `bootId` 안에서 1씩 증가 (재실·행동이 따로 셈) |
| `windowStart` / `windowEnd` | string | 분석한 CSI 구간 |
| `pOccupied` | float 0~1 | 사람이 있을 확률 |
| `quality` | float 0~1 | 입력 품질 (패킷 손실 등) |
| `modelVersion` | string | 모델 버전 |
| `validSec` | int | 이 결과를 유효하게 볼 시간(초). `windowEnd` + `validSec`이 지나면 버림 |

### activity (행동)

```json
{
  "node": "edge-02", "room": "kitchen", "bootId": "a1b2c3d4", "seq": 512,
  "sentAt": "2026-10-17T12:00:04.300+00:00",
  "windowStart": "2026-10-17T12:00:00.000+00:00",
  "windowEnd": "2026-10-17T12:00:04.000+00:00",
  "probs": { "standing": 0.10, "walking": 0.70, "sitting": 0.05, "lying": 0.15 },
  "quality": 0.90,
  "modelVersion": "act-0.1",
  "validSec": 5
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `probs` | object | 행동 이름 → 확률(0~1). 행동 이름 목록은 영진님 모델 기준으로 확정 |

나머지 필드는 occupancy와 같습니다.

### status (노드 상태)

```json
{
  "node": "edge-02", "room": "kitchen", "bootId": "a1b2c3d4",
  "sentAt": "2026-10-17T12:00:05.000+00:00",
  "online": true,
  "lastCsiAt": "2026-10-17T12:00:04.950+00:00",
  "lastAnalysisAt": "2026-10-17T12:00:04.300+00:00",
  "skippedWindows": 0
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `online` | bool | 정상 동작 중이면 true |
| `lastCsiAt` | string | 마지막으로 CSI를 받은 시각 (센서 멈춤 감지용) |
| `lastAnalysisAt` | string | 마지막으로 분석한 시각 (분석기 멈춤 감지용) |
| `skippedWindows` | int | 분석이 밀려 건너뛴 윈도우 누적 수 |

Last Will(연결이 비정상으로 끊기면 브로커가 대신 보내는 메시지)은 같은 토픽에 retain으로 등록합니다.

```json
{ "node": "edge-02", "room": "kitchen", "online": false }
```

## 5. 서버 처리 규칙

- 서버는 노드 메시지를 **판단하지 않고** 원본 그대로 전달합니다. 유효기간(`windowEnd + validSec`),
  노드 이상(`lastCsiAt` / `lastAnalysisAt`), 온라인 여부(`online`, Last Will) 판단은 재실 판단 담당이 합니다.
- 중복 제거만 합니다: QoS 1은 같은 메시지가 두 번 올 수 있어서, 같은 `bootId` 안에서 이미 받은 `seq` 이하의
  메시지는 버립니다 (구역 + 노드 + 종류별). `bootId`가 바뀌면(노드 재시작) 다시 받습니다.
  `bootId` / `seq`가 없는 메시지(status 등)는 거르지 않습니다.
- JSON이 아니거나 JSON 객체가 아닌 메시지는 버립니다.
- 시각: 모든 시각은 시간대를 포함해야 합니다. 노드와 서버의 시계가 맞도록 NTP 동기화를 권장합니다.

## 6. 합친 메시지: `home/edge/combined` (서버 → 재실 판단 담당)

서버가 구역별 **가장 최근 메시지**를 맵(구역 이름이 키)에 모아 두었다가 1초마다 통째로 보냅니다.
새 메시지가 오면 그 칸만 덮어씁니다.

```json
{
  "seq": 1234,
  "publishedAt": "2026-10-17T12:00:05.000+00:00",
  "rooms": {
    "kitchen": {
      "node": "edge-02",
      "occupancy": { "receivedAt": "2026-10-17T12:00:04.120+00:00", "message": { "...노드가 보낸 원본 그대로..." } },
      "activity":  { "receivedAt": "2026-10-17T12:00:04.310+00:00", "message": { "...원본..." } },
      "status":    { "receivedAt": "2026-10-17T12:00:01.000+00:00", "message": { "online": true, "...": "..." } }
    },
    "room":   { "node": "edge-01", "occupancy": { "...": "..." }, "activity": { "...": "..." }, "status": { "...": "..." } },
    "toilet": { "node": null, "occupancy": null, "activity": null, "status": null }
  }
}
```

| 필드 | 설명 |
| --- | --- |
| `seq` | 합친 메시지 순번 (서버가 켜질 때마다 1부터) |
| `publishedAt` | 서버가 보낸 시각 |
| `rooms.{구역}.node` | 그 구역에서 마지막으로 메시지를 보낸 노드ID. 아직 없으면 null |
| `rooms.{구역}.{종류}.message` | 노드가 보낸 원본 메시지 그대로 (4장 형식) |
| `rooms.{구역}.{종류}.receivedAt` | 서버가 그 메시지를 받은 시각 |

- `room` / `kitchen` / `toilet`은 메시지가 없어도 항상 들어 있고, 받은 적 없는 칸은 null입니다.
- 이 3개 외의 구역에서 메시지가 오면 그 구역도 추가됩니다.
- 간격은 `.env`의 `EDGE_COMBINED_INTERVAL_SEC`(기본 1초)로 바꿀 수 있습니다.
- 서버의 `GET /api/v1/sensing/combined`로 지금 내용을 미리 볼 수 있습니다 (발행은 하지 않음).

## 7. 최종 판단 결과: `home/edge/result` (재실 판단 담당 → 서버)

```json
{
  "resultId": "res-20261017-000123",
  "observedAt": "2026-10-17T12:00:02+00:00",
  "room": "kitchen",
  "present": true,
  "confidence": 0.91,
  "activity": "standing",
  "activityConfidence": 0.80,
  "modelVersion": "fusion-0.1",
  "validSec": 5
}
```

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `observedAt` | O | 판단 기준 시각 (ISO 8601, 시간대 포함) |
| `resultId` | | 결과 ID. 같은 ID는 한 번만 저장 (재전송 대비). 없으면 서버가 만듦 |
| `room` | | 최종 위치 (`room` / `kitchen` / `toilet`). 아무도 없으면 null |
| `present` | | 사람이 있는지 |
| `confidence`, `activityConfidence` | | 0~1 |
| `activity` | | 행동 (예: `standing`, `lying`) |
| `modelVersion` | | 모델 버전 |
| `validSec` | | 결과를 유효하게 볼 시간(초). 판단은 받는 쪽(AI 중앙 판정 엔진)이 함 |

- 형식이 확정되기 전이라 **위 표에 없는 필드도 그대로 저장·전달**합니다.
- `observedAt`이 없거나 시각 형식이 아니거나, 확률 값이 0~1을 벗어나면 저장하지 않습니다 (서버 로그에 이유 기록).
- 저장할 때 서버가 `savedAt`(저장 시각)을 붙이고, 대시보드에 WebSocket 이벤트 `sensing.result`로 알립니다.
- 저장된 결과는 7일(`SENSING_RESULT_TTL_DAYS`) 뒤 자동으로 지워집니다.

## 8. 연결 테스트

서버에서 들어오는 메시지 보기

```bash
docker exec -it homevis-mosquitto mosquitto_sub -v -t 'home/+/edge/#'   # 노드 메시지
docker exec -it homevis-mosquitto mosquitto_sub -v -t 'home/edge/#'     # 합친 메시지 + 최종 결과
```

노드에서 테스트 메시지 보내기

```bash
mosquitto_pub -h <서버 IP> -p 1883 -t home/kitchen/edge/edge-02/status -q 1 -r \
  -m '{"node":"edge-02","room":"kitchen","bootId":"test","sentAt":"2026-10-17T12:00:00+00:00","online":true}'
```

가짜 노드·가짜 최종 판단으로 전체 흐름 테스트하기

```bash
# 방법 1) Docker로 한 번에 (가짜 인덕션·전등·정수기·엣지 노드·최종 판단 모두)
docker compose --profile sim up -d --build

# 방법 2) 맥 터미널에서 직접 (서버는 docker compose up -d로 띄워 둔 상태)
source venv/bin/activate
python tests/simulate_edge_nodes.py                 # 가짜 엣지 노드 (다른 PC 브로커면 --host <서버 IP>)
python tests/simulate_fusion.py                     # 가짜 최종 판단 (다른 터미널에서)

# 저장된 최종 결과 확인
curl localhost:8000/api/v1/sensing/results/latest
```

`tests/simulate_fusion.py`는 재실 확률이 가장 높은 구역을 고르는 단순 규칙이라 실제 모델이 아닙니다.
재실 판단 담당이 `home/edge/combined`를 받아 `home/edge/result`로 보내는 코드의 참고용입니다.
