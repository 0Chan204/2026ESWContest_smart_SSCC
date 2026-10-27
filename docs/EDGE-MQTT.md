# 엣지 노드 · 최종 재실 판단 MQTT 명세 (v0.5)

각 구역의 라즈베리파이(엣지 노드)가 보낸 특징값(features) 메시지를 서버가 하나로 합쳐 재실 판단 담당에게 전달하고,
재실 판단 담당이 만든 최종 결과를 서버가 저장하는 MQTT 규칙입니다.

```
① 엣지 노드      ── home/{구역}/edge/{노드ID}/features ──> 서버
② 서버           ── home/edge/combined (1초마다, 구역별 최신 메시지를 합침) ──> 재실 판단 담당
③ 재실 판단 담당 ── home/edge/result (최종 판단 결과) ──> 서버: DB 저장
④ AI 중앙 판정 엔진 ── HTTP GET /api/v1/sensing/results/latest 등 ──> 서버 (docs/AI-INTEGRATION.md)
```

**서버는 판단하지 않습니다.** 노드 상태(`status`), 품질(`quality`), 시각(`t_end`) 판단은 받는 쪽이 합니다.
서버는 노드 메시지를 원본 그대로 전달하고, MQTT 중복 수신만 거릅니다.

## 1. 접속 정보

| 항목 | 값 |
| --- | --- |
| 브로커 | 서버 PC의 LAN IP (확인: 리눅스 `ip route get 1.1.1.1`, 맥 `ipconfig getifaddr en0`) |
| 포트 | `1883` |
| 인증 | 없음 (시연 전에 아이디·비밀번호 추가 예정) |
| 클라이언트 ID | 노드ID 그대로 (예: `r2`). 노드마다 달라야 합니다 |

## 2. 토픽

| 토픽 | 방향 | 내용 | QoS | retain | 보내는 시점 |
| --- | --- | --- | --- | --- | --- |
| `home/{구역}/edge/{노드ID}/features` | 노드 → 서버 | 특징값 메시지 (3장) | 1 | false | 분석할 때마다 |
| `home/edge/combined` | 서버 → 재실 판단 담당 | 구역별 최신 메시지 묶음 (4장) | 1 | false | 1초마다 |
| `home/edge/result` | 재실 판단 담당 → 서버 | 최종 판단 결과 (6장) | 1 | false | 판단할 때마다 |

노드 - 구역 매핑 (시연 구성)

| 구역 | 노드ID | 노드 토픽 |
| --- | --- | --- |
| `room` (방) | `r1` | `home/room/edge/r1/features` |
| `kitchen` (부엌) | `r2` | `home/kitchen/edge/r2/features` |
| `toilet` (화장실) | `r3` | `home/toilet/edge/r3/features` |

- 노드 상태는 메시지 안의 `status`로 알리므로 별도 상태 토픽은 없습니다.
- 서버 최종 상태 토픽은 두지 않습니다. 최종 판단은 AI 중앙 판정 엔진이 백엔드 API(`POST /api/v1/ai/decisions`)로 보내고,
  대시보드는 WebSocket으로 받습니다.
- 노드를 다른 구역으로 옮기면 토픽의 구역만 바꾸면 됩니다.

전체 토픽 한눈에 보기 (시연 구성)

```
home/room/light/light-01/{state|command|ack}             방 전등
home/room/air_purifier/air-01/{state|command|ack}        방 공기청정기
home/room/edge/r1/features                               방 엣지 노드
home/kitchen/induction/induction-01/{state|command|ack}  인덕션
home/kitchen/light/light-02/{state|command|ack}          부엌 전등
home/kitchen/water_purifier/water-01/{state|command|ack} 정수기
home/kitchen/fan/fan-01/{state|command|ack}              부엌 환풍기
home/kitchen/edge/r2/features                            부엌 엣지 노드
home/toilet/light/light-00/{state|command|ack}           화장실 전등
home/toilet/fan/fan-02/{state|command|ack}               화장실 환풍기
home/toilet/edge/r3/features                             화장실 엣지 노드
home/edge/combined                                       서버 → 재실 판단 담당 (합친 메시지)
home/edge/result                                         재실 판단 담당 → 서버 (최종 결과)
home/voice/request                                       서버 → AI 판정 엔진 (음성 명령 문장)
```

구독 예시: 엣지 노드 전체 `home/+/edge/#`, 합친 메시지·최종 결과 `home/edge/#`, 모든 메시지 `home/#`

## 3. 노드 메시지: `home/{구역}/edge/{노드ID}/features` (노드 → 서버)

```json
{
  "v": 1,
  "node": "r2",
  "t_end": 1792215837,
  "status": "ok",
  "features": [-4.61, -4.12, -4.35, -4.20, -3.70, -3.95, 0.92, 0.86, 1.03,
               -3.52, -4.30, -4.66, 0.16, 1.12, 1.0, -4.40, -6.90, 0.22, 0.31],
  "quality": { "rate_hz": 26.8, "rssi": -51.2, "proc_ms": 118.3 },
  "cfg": "67a75326"
}
```

| 필드 | 설명 |
| --- | --- |
| `v` | 메시지 형식 버전 |
| `node` | 노드ID |
| `t_end` | 분석 구간이 끝난 시각 (유닉스 시간, 초) |
| `status` | 노드 상태 (예: `ok`) |
| `features` | 특징값 배열 (19개) |
| `quality` | 수신 품질 (`rate_hz` 수신 속도, `rssi` 신호 세기, `proc_ms` 처리 시간) |
| `cfg` | 노드 설정 식별값 |

서버는 이 메시지를 해석하지 않고 그대로 4장의 `node` 칸에 넣습니다. 필드가 바뀌어도 서버 수정은 필요 없습니다.

## 4. 합친 메시지: `home/edge/combined` (서버 → 재실 판단 담당)

서버가 구역별 **가장 최근 노드 메시지**를 맵(구역 이름이 키)에 모아 두었다가 1초마다 통째로 보냅니다.
새 메시지가 오면 그 구역만 덮어씁니다.

```json
{
  "seq": 1905,
  "publishedAt": "2026-10-17T05:43:58.245+00:00",
  "locations": {
    "room":    { "node": { "v": 1, "node": "r1", "t_end": 1792215837, "status": "ok", "features": ["..."], "quality": {"...": "..."}, "cfg": "67a75326" } },
    "kitchen": { "node": { "v": 1, "node": "r2", "t_end": 1792215837, "status": "ok", "features": ["..."], "quality": {"...": "..."}, "cfg": "67a75326" } },
    "toilet":  { "node": null }
  }
}
```

| 필드 | 설명 |
| --- | --- |
| `seq` | 합친 메시지 순번 (서버가 켜질 때마다 1부터) |
| `publishedAt` | 서버가 보낸 시각 |
| `locations.{구역}.node` | 그 구역 노드가 보낸 가장 최근 메시지 (3장 형식 그대로). 아직 없으면 null |

- `room` / `kitchen` / `toilet`은 메시지가 없어도 항상 들어 있습니다 (`.env`의 `EDGE_ROOMS`).
- 이 3개 외의 구역에서 메시지가 오면 그 구역도 추가됩니다.
- 간격은 `.env`의 `EDGE_COMBINED_INTERVAL_SEC`(기본 1초)로 바꿀 수 있습니다.
- 서버의 `GET /api/v1/sensing/combined`로 지금 내용을 미리 볼 수 있습니다 (발행은 하지 않음).

## 5. 서버 처리 규칙

- 서버는 노드 메시지를 **판단하지 않고** 원본 그대로 전달합니다. `status`가 `ok`가 아니거나 품질이 나빠도 그대로 넣습니다.
- 중복 제거만 합니다: QoS 1은 같은 메시지가 두 번 올 수 있어서, 같은 노드에서 이미 받은 `t_end` 이하의 메시지는 버립니다.
  `t_end`가 없는 메시지는 거르지 않습니다.
- 토픽 마지막 칸이 `features`가 아닌 엣지 토픽, JSON이 아니거나 JSON 객체가 아닌 메시지는 버립니다.
- 시각: 노드와 서버의 시계가 맞도록 NTP 동기화를 권장합니다.

## 6. 최종 판단 결과: `home/edge/result` (재실 판단 담당 → 서버)

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

## 7. 연결 테스트

서버에서 들어오는 메시지 보기

```bash
docker exec -it homevis-mosquitto mosquitto_sub -v -t 'home/+/edge/#'   # 노드 메시지
docker exec -it homevis-mosquitto mosquitto_sub -v -t 'home/edge/#'     # 합친 메시지 + 최종 결과
docker exec -it homevis-mosquitto mosquitto_sub -v -t '#'               # 전부
```

노드에서 테스트 메시지 보내기

```bash
mosquitto_pub -h <서버 IP> -p 1883 -t home/kitchen/edge/r2/features -q 1 \
  -m '{"v":1,"node":"r2","t_end":1792215837,"status":"ok","features":[-1.0,-1.2],"quality":{"rate_hz":26.8,"rssi":-51.2,"proc_ms":118.3},"cfg":"test"}'
```

가짜 노드·가짜 최종 판단으로 전체 흐름 테스트하기

```bash
# 방법 1) Docker로 한 번에 (가짜 인덕션·전등·정수기·엣지 노드·최종 판단 모두)
docker compose --profile sim up -d --build

# 방법 2) 터미널에서 직접 (서버는 docker compose up -d로 띄워 둔 상태)
source venv/bin/activate
python tests/simulate_edge_nodes.py                 # 가짜 엣지 노드 (다른 PC 브로커면 --host <서버 IP>)
python tests/simulate_fusion.py                     # 가짜 최종 판단 (다른 터미널에서)

# 합친 메시지 미리보기, 저장된 최종 결과 확인
curl localhost:8000/api/v1/sensing/combined
curl localhost:8000/api/v1/sensing/results/latest
```

`tests/simulate_fusion.py`는 특징값 평균이 가장 높은 구역을 고르는 단순 규칙이라 실제 모델이 아닙니다.
재실 판단 담당이 `home/edge/combined`를 받아 `home/edge/result`로 보내는 코드의 참고용입니다.
