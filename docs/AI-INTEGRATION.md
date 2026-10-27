# AI 중앙 판정 엔진 · 가전 연동 명세 (v0.7)

모든 제어 판단은 AI 중앙 판정 엔진이 하고, 백엔드는 판단 결과를 받아 가전을 제어하고 기록합니다.
Swagger(`/docs`)의 **AI 중앙 제어**, **가전 제어**, **음성 명령** 섹션에서 바로 호출해 볼 수 있습니다.

## 1. 판정 엔진 → 백엔드 (REST)

### 기기 상태 조회: `GET /api/v1/ai/device-states`

```json
{
  "items": [
    { "device": "stove", "deviceId": "induction-01", "room": "kitchen", "online": true, "is_on": true,
      "current_state": { "state": "on", "level": 5, "temperature": 120.0 },
      "control_state": "user", "updatedAt": "2026-10-16T14:00:00+00:00" },
    { "device": "light", "deviceId": "light-01", "room": "room", "online": true, "is_on": false,
      "current_state": { "reportedAt": "...", "power": "on", "brightness": 20, "mode": "fadeout", "powerSaving": true },
      "control_state": "homevis", "updatedAt": "..." },
    { "device": "fan", "deviceId": "fan-01", "room": "kitchen", "online": true, "is_on": true,
      "current_state": { "reportedAt": "...", "power": "on", "speed": "mid" },
      "control_state": "user", "updatedAt": "..." },
    { "device": "water_purifier", "deviceId": "water-01", "room": "kitchen", "online": true, "is_on": false,
      "current_state": { "reportedAt": "...", "status": "idle", "lastDispensedMl": 250 },
      "control_state": null, "updatedAt": "..." },
    { "device": "air_purifier", "deviceId": "air-01", "room": "room", "online": true, "is_on": true,
      "current_state": { "reportedAt": "...", "power": "on", "mode": "auto",
                         "airQuality": { "pm25": 42, "pm10": 60, "level": "bad" } },
      "control_state": "homevis", "updatedAt": "..." }
  ]
}
```

- `is_on`: 인덕션은 화구가 켜져 있으면, 전등·환풍기·공기청정기는 켜져 있으면(절전 밝기여도 켜짐), 정수기는 출수 중이면 `true`
- 공기청정기 `current_state.airQuality`: 기기가 보낸 공기질(`pm25`, `pm10`, `level`). 공기질이 나빠 기기가 스스로 켜면
  `control_state`가 `homevis`입니다 (사용자가 켠 것이 아님)
- 전등 `current_state.brightness`: 밝기(%). 밝기를 보내지 않는 전등은 켜져 있으면 100, 꺼져 있으면 0으로 채웁니다.
  `powerSaving`: 절전(`power_saving`)으로 낮춘 전등이면 `true`
- `control_state`: 마지막으로 상태를 바꾼 주체. `user`(사용자), `homevis`(HomeVIS 자동 제어), 기록 없으면 `null`

### 최종 재실 판단 결과 조회: `GET /api/v1/sensing/results/latest`, `GET /api/v1/sensing/results` (v0.4)

재실 판단 담당이 MQTT(`home/edge/result`)로 보낸 최종 결과를 서버가 저장해 두고, 판정 엔진은 HTTP로 꺼내 씁니다.
서버는 값을 판단하지 않고 저장된 그대로 돌려줍니다. 결과가 오래됐는지는 `observedAt`, `validSec`으로 판정 엔진이 판단합니다.

`GET /api/v1/sensing/results/latest` (아직 결과가 없으면 404)

```json
{
  "resultId": "res-20261017-000123",
  "observedAt": "2026-10-17T12:00:02+00:00",
  "savedAt": "2026-10-17T12:00:02.150+00:00",
  "room": "kitchen",
  "present": true,
  "confidence": 0.91,
  "activity": "standing",
  "activityConfidence": 0.80,
  "modelVersion": "fusion-0.1",
  "validSec": 5
}
```

`GET /api/v1/sensing/results?since=2026-10-17T11:40:00%2B00:00&until=...&limit=500`

- `observedAt` 기준으로 기간 안의 결과 중 최근 `limit`개(기본 500, 최대 5000)를 오래된 것부터 돌려줍니다 (`items`, `total`).
- 예: "20분째 누워 있음" 같은 판단에 지난 결과가 필요할 때 사용합니다.
- 서버 메모리의 최근 5000건(1초마다면 약 1시간 20분) 안에서 찾습니다.
- 주소에 넣을 때 `+`는 `%2B`로 바꾸거나, `Z`(UTC)로 끝나는 시각을 쓰세요.

결과 형식과 MQTT 규칙은 `docs/EDGE-MQTT.md` 7장 참고.

### 판단 결과 전송: `POST /api/v1/ai/decisions`

```json
{
  "decisionId": "dec-001",
  "scenario": "bedtime_light_off",
  "confidence": 0.88,
  "reason": "누운 상태 20분 지속",
  "timestamp": "2026-10-16T23:10:00+09:00",
  "room": "room",
  "actions": [ { "device": "light", "action": "off" } ],
  "announcement": "주무실 시간이라 불을 끌게요.",
  "expiresAt": "2026-10-16T23:10:30+09:00"
}
```

| 필드 | 설명 |
| --- | --- |
| `decisionId` | 판단 id. **같은 id로 다시 보내면 다시 실행하지 않고** 처음 결과를 돌려줍니다 (재전송 대비) |
| `scenario` | 시나리오 이름 (아래 표) |
| `room` | 판단 대상 구역. `deviceId`를 생략하면 이 구역의 기기를 우선 사용 |
| `actions` | 실행할 제어 목록. 순서대로 실행하며, 하나가 실패해도 나머지는 실행 |
| `announcement` | (선택) 대시보드가 화면에 띄우고 **음성으로 읽을 안내 문장** (최대 500자). 제어 없이 안내만 보내도 됩니다 |
| `expiresAt` | (선택) 만료 시각. 이 시각이 지나서 도착한 판단은 **실행하지 않고** `status: "expired"`로 기록합니다 |
| `weatherBriefing` | `true`면 서버가 날씨 안내 문장을 만들어 대시보드에 보내고 응답의 `weather`에 담습니다 (아래 "날씨 안내"). 판정 엔진이 `announcement`로 안내를 만든다면 보내지 마세요 (두 번 읽힘) |

`actions[]` 항목

| device | action | 추가 값 |
| --- | --- | --- |
| `stove` | `turn_off`, `turn_on`, `set_level`, `restore_power` | `set_level`은 `level`(1~9) 필수 |
| `light` | `on`(100%), `off`, `blink`, `fadeout`(절전 밝기 20%로 서서히) | `blink`는 `durationSec` (없으면 10초) |
| `water_purifier` | `dispense` | `amountMl` **필수** (판정 엔진이 출수량을 정함) |
| `fan` | `on`, `off`, `set_speed` | `set_speed`는 `speed` **필수**: `low`(약) / `mid`(중) / `high`(강) |
| `air_purifier` | `on`, `off`, `set_mode` | `set_mode`는 `mode` **필수**: `auto`(공기질 자동) / `manual` |

`deviceId`는 생략할 수 있습니다(같은 `room`의 기기를 먼저 고름). 시연 구성:
인덕션 `induction-01`(부엌), 전등 `light-01`(방)·`light-00`(화장실)·`light-02`(부엌), 정수기 `water-01`(부엌), 환풍기 `fan-01`(부엌)·`fan-02`(화장실),
공기청정기 `air-01`(방)

환풍기 자동 운전(조리할 때 켜기 등)과 "인덕션이 켜지면 공기청정기 켜기"는 판정 엔진이 기기 상태를 보고 판단해서
`fan` / `air_purifier` 동작으로 보냅니다. 백엔드는 실행만 합니다. 공기질이 나쁠 때 자동 작동은 공기청정기가 스스로 합니다.

시나리오별 처리

| scenario | 백엔드 동작 |
| --- | --- |
| `bedtime_light_off` | `actions` 실행 (예: 전등 off) |
| `stove_absence` | `actions` 실행. 인덕션을 끄거나 낮추면 직전 화력을 저장하고, `restore_power`로 그 화력으로 다시 켭니다 |
| `water_dispense` | `actions` 실행 (예: 정수기 dispense 250ml). `weatherBriefing: true`면 날씨 안내도 함께 |
| `power_saving` | (v0.5) `room`에 사람이 없다는 판단. 그 구역에서 켜져 있는 전등을 **20%로 서서히 낮춤**(`fadeout`, 전원은 켜진 채). `actions`는 비워도 됩니다 |
| `power_saving_end` | (v0.5) `room`에 사람이 다시 들어왔다는 판단. **절전으로 낮췄던 전등만 100%로 복귀**. 그 사이 사용자가 끈 전등은 다시 켜지 않습니다 |
| `away_all_off` | (v0.7) 집을 비웠다는 판단. **켜져 있는 인덕션·전등·환풍기·공기청정기를 모두 끔** (정수기 제외). `actions`는 비워도 됩니다. 인덕션은 끄기 직전 화력을 저장해 `restore_power`로 복구할 수 있습니다. `announcement`가 없으면 "외출하신 것 같아 켜져 있던 가전 N개를 껐어요."로 안내합니다 |
| `fall_detected` | 낙상 단계별 대응 실행 (아래 표). 인덕션 `turn_off`와 전등 `blink`는 서버가 직접 하므로 `actions`는 비워도 됩니다 |
| 그 외 | `actions` 실행 |

낙상 단계별 대응 (`fall_detected`, 또는 `POST /api/v1/safety/fall-events`)

| 단계 | 시점 | 서버 동작 |
| --- | --- | --- |
| 즉시 | 감지 | 인덕션 비상 차단, 전등 10초 깜빡임(낙상 구역 전등, 없으면 첫 번째 전등), 대시보드 경고(`fall_detected`) |
| 1차 | 감지 | 사용자 본인에게 확인 링크 문자 |
| 2차 | 감지 + `userAlertWaitSec`(기본 30초) | 응답이 없으면 보호자에게 확인 링크 문자, 대시보드에 `fall_escalated` |
| 3차 | 보호자 알림 + `autoReportSec`(기본 60초) | 응답이 없으면 자동 신고(`fall_auto_reported`) |

- 1차 알림에는 대시보드 경고도 포함되므로, 사용자 문자를 못 보내도(미등록, 인터넷 불안정) 대기 시간은 그대로 지킵니다.
  `userAlertWaitSec`를 0으로 하면 사용자와 보호자에게 동시에 보냅니다.
- 링크에서 "괜찮음"(resolve) 또는 "신고"(report)를 누르면 그 뒤 단계는 진행되지 않습니다.
- 대기 시간은 `GET/PUT /api/v1/policies/fall-safety`로 바꿉니다. 서버를 다시 켜도 진행 중인 단계를 이어갑니다.
- 판단 응답의 `actions`에 인덕션 `turn_off`, 전등 `blink` 결과가 들어 있고, 단계 진행 상황은
  `GET /api/v1/fall-incidents/{fallIncidentId}`의 `stage`(user/guardian), `status`로 확인합니다.

음성 안내 (`announcement`)

- 대시보드에 WebSocket 이벤트 `ai.announcement`로 보내고, 대시보드가 화면 표시 + 음성(TTS) 재생을 합니다.
  `{ "decisionId", "scenario", "room", "text", "announcedAt" }`
- 날씨를 안내에 넣으려면 판정 엔진이 `GET /api/v1/weather`로 날씨를 가져가 문장을 만듭니다.
  `available: false`면 날씨 문장을 빼고, `stale: true`면 `basedOn` 기준 시각을 붙이면 됩니다.
- 안내 문장은 판단 기록(`announcement`)과 안전 이벤트(`ai_control`의 action)에도 남습니다.

판단 만료 (`expiresAt`)

- 판정 엔진의 outbox가 네트워크 장애 뒤 늦게 재전송한 판단이 엉뚱한 때 실행되지 않도록 합니다.
- 만료된 판단은 가전 제어, 안내, 안전 이벤트를 모두 하지 않고, 기록만 `status: "expired"`로 남깁니다.
- 응답은 그대로 **202**입니다 (outbox가 실패로 보고 계속 재전송하지 않도록). 응답의 `status`로 구분하세요.
- **낙상(`fall_detected`)은 늦게 도착해도 안전을 위해 항상 실행합니다.**
- 시간대가 있는 ISO 8601 시각으로 보내세요 (`+09:00` 또는 `Z`). 서버와 판정 엔진의 시계가 맞아야 합니다.

날씨 안내 (`weatherBriefing: true`)

- 서버가 30분마다 Open-Meteo에서 날씨를 미리 받아 저장해 두고, 판단이 오면 그 값으로 바로 안내합니다.
  그래서 대회장 인터넷이 끊겨 있어도 응답이 늦어지지 않고, 마지막으로 받은 날씨로 안내합니다.
- 1시간보다 오래된 날씨면 문장 앞에 "(오후 3시 05분 기준)"처럼 기준 시각을 붙이고 `stale: true`입니다.
- 한 번도 받지 못했으면 `available: false`, 문장은 "날씨 정보를 아직 가져오지 못했어요."입니다. 출수는 그대로 실행됩니다.
- 대시보드에는 WebSocket 이벤트 `weather.briefing`으로 보내고, `GET /api/v1/weather`로도 조회할 수 있습니다.
- `weather.hourly` (v0.4.3): 지금 시간부터 12시간(`WEATHER_HOURLY_HOURS`)의 시간대별 예보입니다.
  `time`은 그 시간의 시작 시각(`+09:00` 포함)이고, 이미 지나간 시간은 응답할 때 빠집니다.
  `precipitationProbability`는 그 시간의 강수 확률(%)입니다. (바깥의 `precipitationProbability`는 오늘 최대 강수 확률)

```json
"weather": {
  "available": true,
  "text": "현재 서울은 맑음, 기온 18도예요. 오늘 최고 22도, 최저 12도이고 비 올 확률은 10%예요.",
  "stale": false,
  "basedOn": "2026-10-16T12:45:00+00:00",
  "weather": { "location": "서울", "temperature": 18.3, "humidity": 60, "condition": "맑음",
               "tempMax": 22.4, "tempMin": 11.6, "precipitationProbability": 10, "...": "...",
               "hourly": [
                 { "time": "2026-10-16T21:00:00+09:00", "temperature": 17.5, "weatherCode": 3, "condition": "흐림", "precipitationProbability": 0 },
                 { "time": "2026-10-16T22:00:00+09:00", "temperature": 17.0, "weatherCode": 61, "condition": "약한 비", "precipitationProbability": 60 }
               ] }
}
```

`restore_power`가 거부되는 경우: 저장된 화력이 없을 때(HomeVIS가 끄거나 낮춘 적이 없거나, 그 사이 사용자가 직접 조작함), 화구가 과열 상태일 때.

응답 (202, 중복이면 200)

```json
{
  "decisionId": "dec-001", "scenario": "bedtime_light_off", "confidence": 0.88, "...": "...",
  "actions": [
    { "device": "light", "deviceId": "light-01", "action": "off", "status": "sent", "commandId": "cmd-20261016-9f8e7d6c" }
  ],
  "eventId": "evt-0a1b2c3d4e5f",
  "fallIncidentId": null,
  "feedback": null,
  "weather": null,
  "announcement": "주무실 시간이라 불을 끌게요.",
  "expiresAt": "2026-10-16T23:10:30+09:00",
  "status": "executed",
  "duplicate": false
}
```

`actions[].status`: `sent`(기기로 전송), `rejected`(조건이 맞지 않아 거부, `message`에 이유), `failed`(전송 실패)

`status`: `executed`(실행함), `expired`(만료 시각이 지나 도착해서 실행하지 않음, `actions`는 빈 목록)

### 판단 기록과 피드백 조회: `GET /api/v1/ai/decisions?limit=50`, `GET /api/v1/ai/decisions/{decisionId}`

판단마다 안전 이벤트(`ai_control`)가 만들어지고, 사용자가 대시보드에서 그 이벤트에 피드백
(`POST /api/v1/safety-events/{eventId}/feedback`)을 남기면 판단 기록의 `feedback`에 복사됩니다.
판정 엔진은 이 값을 가중치 조정에 사용합니다.

절전 (`power_saving` / `power_saving_end`, v0.5)

- 흐름: 재실 판단 담당의 최종 결과 → 판정 엔진이 구역별 out/in 판단 → 서버가 전등 제어
- 절전 밝기(20%)와 복귀 밝기(100%)는 서버가 정합니다. `room`이 없으면 `rejected`로 기록합니다.
- 이미 절전 중인 전등, 꺼져 있는 전등, 이미 20% 이하인 전등은 다시 보내지 않습니다.
- 절전 중인 전등 목록은 DB에 저장되어 서버를 다시 켜도 복귀할 수 있습니다.

```json
{ "decisionId": "dec-ps-001", "scenario": "power_saving", "confidence": 0.9,
  "timestamp": "2026-10-17T21:00:00+09:00", "room": "room", "actions": [] }
```

음성 명령 (`voiceId`, `requiresConfirmation`, v0.6)

- 대시보드 음성 명령의 문장은 MQTT `home/voice/request`로 받고, 판단은 이 API에 `voiceId`를 담아 보냅니다.
- `requiresConfirmation: true`면 서버가 제어를 보류하고 사용자 확인을 받은 뒤 실행합니다.
- 메시지 형식과 상태 흐름은 `docs/VOICE.md`에 정리되어 있습니다.

## 2. 전등 · 정수기 · 환풍기 ↔ 백엔드 (MQTT)

토픽 규칙 (인덕션과 같음): `home/{구역}/{종류}/{deviceId}/{state | command | ack}`

| 기기 | 토픽 앞부분 |
| --- | --- |
| 전등 `light-01` (방) | `home/room/light/light-01/` |
| 전등 `light-00` (화장실) | `home/toilet/light/light-00/` |
| 전등 `light-02` (부엌) | `home/kitchen/light/light-02/` |
| 정수기 `water-01` (부엌) | `home/kitchen/water_purifier/water-01/` |
| 환풍기 `fan-01` (부엌) | `home/kitchen/fan/fan-01/` |
| 환풍기 `fan-02` (화장실) | `home/toilet/fan/fan-02/` |
| 공기청정기 `air-01` (방) | `home/room/air_purifier/air-01/` |

QoS 1. 기기는 **5초마다, 그리고 상태가 바뀔 때마다** `state`를 보냅니다.
15초 이상 `state`가 오지 않으면 오프라인으로 봅니다.

**state (기기 → 서버)**

```json
// 전등
{ "reportedAt": "2026-10-16T23:00:00+09:00", "power": "on", "brightness": 100, "mode": "steady",
  "lastControl": { "publisher": "api", "commandId": "cmd-20261016-1a2b3c4d" } }
// 정수기
{ "reportedAt": "2026-10-16T07:30:00+09:00", "status": "idle", "lastDispensedMl": 250,
  "lastControl": { "publisher": "api", "commandId": "cmd-20261016-5e6f7a8b" } }
// 환풍기
{ "reportedAt": "2026-10-17T18:00:00+09:00", "power": "on", "speed": "mid",
  "lastControl": { "publisher": "api", "commandId": "cmd-20261017-9a8b7c6d" } }
// 공기청정기 (공기질이 나빠 스스로 켬)
{ "reportedAt": "2026-10-25T14:00:00+09:00", "power": "on", "mode": "auto",
  "airQuality": { "pm25": 42, "pm10": 60, "level": "bad" },
  "lastControl": { "publisher": "system" } }
```

- 전등 `power`: `on` / `off`, `brightness`: 0~100(%), `mode`: `steady` / `blink` / `fadeout`
  - 절전 밝기로 낮추는 중에는 `mode: "fadeout"`, 다 낮춘 뒤에는 `fadeout` 또는 `steady` 둘 다 됩니다. `power`는 계속 `on`
  - `brightness`를 보내지 않으면 켜져 있을 때 100으로 봅니다
- 환풍기 `power`: `on` / `off`, `speed`: `low`(약) / `mid`(중) / `high`(강)
- 공기청정기 `power`: `on` / `off`, `mode`: `auto` / `manual`, `airQuality`: `pm25`·`pm10`(㎍/㎥), `level`(`good` / `normal` / `bad`)
  - 공기질 판단과 자동 작동은 기기가 합니다. 스스로 켜거나 끄면 `lastControl.publisher`를 `system`으로 보냅니다.
  - `airQuality`에 다른 센서 값(예: `co2`)을 더 넣어도 그대로 저장·전달합니다.
- 정수기 `status`: `idle` / `dispensing`
- `lastControl.publisher`: 기기 버튼 등으로 직접 조작했으면 `user`, 서버 명령으로 바뀌었으면 `api`(+ `commandId`)
- 기기가 켜진 직후처럼 아무도 조작하지 않았을 때는 `user`(commandId 없음)로 보냅니다. `system`은 기기가 스스로 안전 조치를 했을 때(과열 차단 등)만 씁니다.

**command (서버 → 기기)**

```json
{ "commandId": "cmd-20261016-1a2b3c4d", "issuedAt": "...", "deviceId": "light-01", "type": "blink", "durationSec": 10 }
{ "commandId": "cmd-20261016-5e6f7a8b", "issuedAt": "...", "deviceId": "water-01", "type": "dispense", "amountMl": 250 }
{ "commandId": "cmd-20261017-2c3d4e5f", "issuedAt": "...", "deviceId": "light-01", "type": "fadeout", "brightness": 20, "durationSec": 3 }
{ "commandId": "cmd-20261017-9a8b7c6d", "issuedAt": "...", "deviceId": "fan-01", "type": "set_speed", "speed": "mid" }
{ "commandId": "cmd-20261025-3b4c5d6e", "issuedAt": "...", "deviceId": "air-01", "type": "set_mode", "mode": "auto" }
```

- 전등: `on`(`brightness: 100`), `off`, `blink`(`durationSec` 동안 깜빡인 뒤 원래 상태로 돌아감),
  `fadeout`(`durationSec`초 동안 `brightness`(20)까지 서서히 낮춤, 전원은 켠 채로)
- 정수기: `dispense`(`amountMl`만큼 출수)
- 환풍기: `on`(지난 풍량으로 켜기), `off`, `set_speed`(`speed`로 바꾸기. 꺼져 있으면 켜면서 바꿈)
- 공기청정기: `on`, `off`, `set_mode`(`mode`로 바꾸기)

**ack (기기 → 서버, 명령을 받으면 바로)**

```json
{ "commandId": "cmd-20261016-1a2b3c4d", "result": "applied", "appliedAt": "...",
  "state": { "reportedAt": "...", "power": "on", "mode": "blink" } }
```

`result`: `applied` / `rejected` / `failed`. `state`는 처리 후 상태(위 state 형식)이며 생략할 수 있습니다.

## 3. 기기 목록 바꾸기

기본 구성은 전등 3개(`light-01` 방, `light-00` 화장실, `light-02` 부엌), 정수기 1개(`water-01` 부엌), 환풍기 2개(`fan-01` 부엌, `fan-02` 화장실),
공기청정기 1개(`air-01` 방)입니다.
바꾸려면 `.env`에 JSON으로 넣습니다. **값을 넣으면 기본 구성 전체를 대신하므로** 필요한 기기를 모두 적어야 합니다.

```
HOMEVIS_DEVICES=[{"deviceId":"light-01","type":"light","room":"room"},{"deviceId":"light-02","type":"light","room":"kitchen"},{"deviceId":"water-01","type":"water_purifier","room":"kitchen"},{"deviceId":"fan-01","type":"fan","room":"kitchen"}]
LIGHT_BLINK_SEC=10
LIGHT_FADE_SEC=3
```

## 4. 테스트용 가짜 기기

```bash
docker compose --profile sim up -d     # 가짜 인덕션 + 전등·정수기·환풍기·공기청정기 + 엣지 노드 + 최종 판단 + 음성 판정까지 실행
python tests/simulate_home_devices.py  # Docker 없이 가짜 전등·정수기·환풍기·공기청정기만 실행
python tests/simulate_edge_nodes.py    # Docker 없이 가짜 엣지 노드만 실행
python tests/simulate_fusion.py        # Docker 없이 가짜 최종 판단만 실행
python tests/simulate_voice_ai.py      # Docker 없이 가짜 판정 엔진(음성 명령)만 실행
```
