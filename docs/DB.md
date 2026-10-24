# DB 설계 (MongoDB)

HomeVIS 백엔드의 MongoDB 컬렉션 구조입니다. 코드에서는 `app/state_store.py`(무엇을 저장하는지)와
`app/db.py`(어떻게 저장하는지)가 이 문서와 1:1로 대응합니다.

- DB: MongoDB Atlas 무료 등급(M0), DB 이름 `homevis`
- 접속 주소: 서버 `.env`의 `MONGODB_URI` (GitHub에는 올리지 않음)
- 필드 이름과 값의 형식은 API 응답과 동일합니다 (`app/schemas.py` 기준)

## 저장 방식

- **읽기는 서버 메모리에서** 합니다. DB가 멀리 있어도 API 응답이 느려지지 않습니다.
- **쓰기는 메모리에 반영한 뒤 DB에도 저장**합니다. 별도 스레드가 순서대로 저장하므로 API나
  MQTT 수신이 DB 때문에 멈추지 않습니다.
- **서버가 시작될 때 DB의 내용을 메모리로 불러옵니다.** 그래서 재시작해도 데이터가 유지됩니다.
- `MONGODB_URI`가 없거나 접속에 실패하면 DB 없이 메모리로만 동작합니다.
  `GET /health`의 `storage` 값(`mongodb` / `memory`)으로 확인할 수 있습니다.

이 방식은 서버가 1대일 때를 전제로 합니다. 서버를 여러 대로 늘리면 서버마다 메모리 내용이
달라지므로, 그때는 읽기도 DB에서 하도록 바꿔야 합니다.

## 컬렉션 목록

| 컬렉션 | `_id` | 내용 | 관련 API |
| --- | --- | --- | --- |
| `contacts` | `user` / `guardian` | 사용자·보호자 연락처 | 회원 정보 |
| `policies` | `kitchen-absence` / `fall-safety` | 부재중 정책, 낙상 안전 정책 | AI 재실 판단, 낙상 사고 감지 |
| `telemetry_latest` | 기기 ID | 인덕션의 최신 상태 1건 | 인덕션 제어, 대시보드 화면 |
| `telemetry_logs` | 자동 생성 | 인덕션 상태 이력 (자동 삭제) | 조회 API 없음 (기록용) |
| `commands` | 명령 ID | 가전 제어 명령과 처리 상태 (v0.3: 전등·정수기 포함) | 인덕션 제어, 전등·정수기 제어 |
| `safety_events` | 이벤트 ID | 안전 이벤트 이력 | 안전 이벤트 |
| `sessions` | 세션 ID | 조리 세션과 타임라인 | 대시보드 화면 |
| `presence` | 방 이름 | 방별 최신 재실 판단 결과 | AI 재실 판단 |
| `fall_incidents` | 사건 ID | 낙상 사건과 확인 토큰 | 낙상 사고 감지 |
| `sms_logs` | 발송 기록 ID | 문자 발송 이력 | 회원 정보 |
| `runtime_state` | 고정 키 | 진행 중인 세션, 복구용 화력 | 내부용 |
| `device_states` | 기기 ID | 전등·정수기의 최신 상태 (v0.3) | 전등·정수기 제어, AI 중앙 제어 |
| `ai_decisions` | 판단 ID | AI 중앙 판정 엔진의 판단과 실행 결과, 피드백 (v0.3) | AI 중앙 제어 |
| `sensing_results` | 결과 ID | 재실 판단 담당이 보낸 최종 재실 판단 결과 (v0.4, 자동 삭제) | AI 중앙 제어 |
| `voice_commands` | 음성 명령 ID | 대시보드 음성 명령 문장과 처리 결과 (v0.6, 30일 뒤 자동 삭제) | 음성 명령 |

엣지 노드가 보내는 원본 메시지(features)는 저장하지 않고, 서버 메모리에서 합쳐 전달만 합니다
(`docs/EDGE-MQTT.md`).

## 문서 예시

### contacts

```json
{ "_id": "guardian", "name": "박보호", "phone": "01033334444" }
```

전화번호는 숫자만 저장합니다.

### policies

```json
{
  "_id": "kitchen-absence",
  "watchAfterSec": 60, "reduceAfterSec": 180, "offAfterSec": 600,
  "reduceToLevel": 1, "minConfidence": 0.7, "nearZoneMultiplier": 2.0,
  "overheatEnterC": 150.0, "overheatExitC": 60.0, "heartbeatTimeoutSec": 15
}
```

```json
{ "_id": "fall-safety", "userAlertWaitSec": 30, "autoReportSec": 60 }
```

문서가 없으면 `app/config.py`의 기본값을 사용합니다.

### telemetry_latest

```json
{
  "_id": "induction-01",
  "lastSeenAt": "2026-10-05T03:00:00Z",
  "report": {
    "reportedAt": "2026-10-05T12:00:00+09:00",
    "burners": [
      { "burnerId": "burner-1", "deviceState": "on", "level": 3, "temperature": 80.0, "activeSec": 120 }
    ],
    "lastControl": { "publisher": "api", "commandId": "cmd-20261005-ab12cd34" },
    "alarm": "off"
  }
}
```

`lastSeenAt`은 온라인 판정에 사용합니다.

### telemetry_logs

```json
{
  "deviceId": "induction-01",
  "receivedAt": "2026-10-05T03:00:00Z",
  "reportedAt": "2026-10-05T12:00:00+09:00",
  "burners": [ { "burnerId": "burner-1", "deviceState": "on", "level": 3, "temperature": 80.0, "activeSec": 120 } ],
  "lastControl": { "publisher": "api", "commandId": "cmd-20261005-ab12cd34" },
  "alarm": "off"
}
```

인덕션이 상태를 보낼 때마다(약 3초 간격) 1건씩 쌓입니다. `receivedAt` 기준으로
`TELEMETRY_LOG_TTL_DAYS`(기본 7일)가 지나면 MongoDB가 자동으로 삭제합니다.

### commands

```json
{
  "_id": "cmd-20261005-ab12cd34",
  "commandId": "cmd-20261005-ab12cd34",
  "status": "acked",
  "type": "set_level", "level": 3,
  "actor": "user", "reason": null,
  "issuedAt": "2026-10-05T12:00:00+09:00",
  "ackedAt": "2026-10-05T12:00:01+09:00"
}
```

`status`: `pending` → `sent` → `acked` / `rejected` / `failed`. `actor`가 `system`이면 부재중 정책이나
낙상 감지로 서버가 자동 발행한 명령입니다.

### safety_events

```json
{
  "_id": "evt-033aac118458",
  "seq": 12,
  "eventId": "evt-033aac118458",
  "type": "fall_detected", "severity": "danger",
  "occurredAt": "2026-10-05T03:00:00+00:00",
  "room": "kitchen", "sessionId": null, "temperature": null,
  "trigger": "낙상 감지 모델 confidence=0.95",
  "action": "인덕션 비상 전원 차단 명령 전송 + 보호자 문자 발송",
  "reasoning": "modelVersion=fall-detector-0.1"
}
```

`seq`는 발생 순서를 보장하기 위한 일련번호입니다. `type` 13종은 `app/schemas.py`의 `SafetyEventType` 참고.

사용자가 피드백을 제출하면 같은 문서 안에 `feedback`으로 저장됩니다. 다시 제출하면 최근 의견으로 바뀝니다.

```json
"feedback": { "verdict": "rejected", "comment": "오탐", "submittedAt": "2026-10-05T03:05:00+00:00" }
```

### sessions

```json
{
  "_id": "session-1a2b3c4d5e6f",
  "sessionId": "session-1a2b3c4d5e6f",
  "startedAt": "2026-10-05T03:00:00+00:00", "endedAt": null,
  "status": "active", "peakTemperature": 120.5,
  "timeline": [ { "at": "2026-10-05T03:00:00+00:00", "type": "cooking_started", "summary": "조리 시작" } ]
}
```

### presence

```json
{
  "_id": "kitchen",
  "room": "kitchen", "zone": "far", "present": false, "absentSec": 200,
  "confidence": 0.9, "observedAt": "2026-10-05T03:00:00+00:00", "modelVersion": "presence-0.1"
}
```

방마다 최신 1건만 보관합니다.

### fall_incidents

```json
{
  "_id": "fall-71c6610bdb",
  "token": "(확인 링크용 임의 문자열)",
  "incidentId": "fall-71c6610bdb",
  "room": "kitchen", "status": "pending",
  "detectedAt": "2026-10-05T03:00:00+00:00", "confidence": 0.95,
  "confirmUrl": "https://(프론트 주소)/fall/fall-71c6610bdb?token=...",
  "stage": "user",
  "guardianAlertAt": "2026-10-05T03:00:30+00:00",
  "guardianAlertedAt": null,
  "autoReportAt": "2026-10-05T03:01:30+00:00",
  "shutoffSent": true, "lightBlinkSent": true, "lightDeviceId": "light-01",
  "userNotified": true, "guardianNotified": false,
  "eventId": "evt-033aac118458", "resolvedAt": null, "reportedAt": null
}
```

`status`: `pending` → `resolved` / `reported` / `auto_reported`. `token`은 API 응답에는 포함되지 않습니다.
`stage`: 지금 응답을 기다리는 대상. `user`(사용자 본인) → `guardianAlertAt`이 지나면 `guardian`(보호자).
`userAlertWaitSec`가 0이면 처음부터 `guardian`입니다. `autoReportAt`은 보호자 알림 시각 + `autoReportSec`입니다.
`shutoffSent` / `lightBlinkSent` / `userNotified` / `guardianNotified`는 각 조치(인덕션 차단, 전등 깜빡임,
사용자 문자, 보호자 문자)를 실제로 보냈는지를 나타냅니다. 예전 문서에 없는 필드는 기본값(`stage: guardian`, false)으로 읽습니다.
서버가 재시작되면 `pending` 상태인 사건을 `guardianAlertAt`, `autoReportAt` 기준으로 이어서 진행합니다.

### sms_logs

```json
{
  "_id": "sms-54d382c8b9b3",
  "seq": 3,
  "logId": "sms-54d382c8b9b3",
  "to": "01033334444",
  "purpose": "fall_alert",
  "success": true,
  "sentAt": "2026-10-05T03:00:00+00:00",
  "incidentId": "fall-71c6610bdb"
}
```

`purpose`: `user_verification`(사용자 등록 확인) / `guardian_verification`(보호자 등록 확인) /
`fall_user_alert`(사용자 본인에게 보내는 1차 낙상 알림) / `fall_alert`(보호자에게 보내는 낙상 알림).
발송에 실패한 경우도 `success: false`로 남깁니다. 문자 본문은 저장하지 않습니다 (낙상 문자에는 확인 링크의 토큰이 들어 있기 때문).

### runtime_state

```json
{ "_id": "active_sessions", "values": { "induction-01": "session-1a2b3c4d5e6f" } }
{ "_id": "restore_levels", "values": { "induction-01": 6 } }
{ "_id": "power_saving_lights", "values": ["light-01"] }
{ "_id": "weather", "value": { "location": "서울", "fetchedAt": "2026-10-16T12:45:00+00:00", "temperature": 18.3, "condition": "맑음", "...": "..." } }
```

재시작 후에도 진행 중인 조리 세션과 복구용 화력을 이어가기 위한 내부 상태입니다.
`restore_levels`는 HomeVIS(AI 판단)가 인덕션을 끄거나 낮추기 직전 화력이며, `restore_power`로 복구하거나
사용자가 직접 조작하면 지워집니다. (v0.3부터 `absence_stages`는 쓰지 않습니다.)
`power_saving_lights`는 절전(`power_saving`)으로 밝기를 20%로 낮춘 전등 목록입니다 (v0.5). 사람이 돌아오면
(`power_saving_end`) 이 전등만 100%로 되돌리고, 누가 직접 켜거나 끄면 목록에서 빠집니다.
`weather`는 마지막으로 받아 온 날씨입니다 (v0.3.2). 인터넷이 끊긴 상태로 서버를 다시 켜도 이 값으로 날씨 안내를 합니다.

### device_states (v0.3)

```json
{
  "_id": "light-01",
  "type": "light",
  "state": { "reportedAt": "2026-10-16T23:00:00+09:00", "power": "on", "mode": "steady",
             "lastControl": { "publisher": "api", "commandId": "cmd-20261016-1a2b3c4d" } },
  "lastSeenAt": "2026-10-16T14:00:00Z"
}
```

정수기는 `state`가 `{ "status": "idle|dispensing", "lastDispensedMl": 250, ... }` 형태입니다.

### ai_decisions (v0.3)

```json
{
  "_id": "dec-001",
  "seq": 1,
  "decisionId": "dec-001",
  "scenario": "bedtime_light_off",
  "confidence": 0.88,
  "reason": "누운 상태 20분 지속",
  "timestamp": "2026-10-16T23:10:00+09:00",
  "room": "room",
  "receivedAt": "2026-10-16T14:10:01+00:00",
  "weatherBriefing": false,
  "actions": [
    { "device": "light", "deviceId": "light-01", "action": "off", "status": "sent", "commandId": "cmd-20261016-9f8e7d6c" }
  ],
  "eventId": "evt-0a1b2c3d4e5f",
  "fallIncidentId": null,
  "feedback": { "verdict": "rejected", "comment": "아직 안 잤어요", "submittedAt": "2026-10-16T14:12:00+00:00" },
  "weather": null,
  "announcement": "주무실 시간이라 불을 끌게요.",
  "expiresAt": "2026-10-16T23:10:30+09:00",
  "status": "executed"
}
```

판단으로 생긴 안전 이벤트(`ai_control`)에 사용자가 피드백을 남기면 `feedback`에도 복사됩니다.
`status`는 `executed`(실행함) / `expired`(만료 시각이 지나 도착해서 실행하지 않음)이며, 예전 문서에 없으면 `executed`로 읽습니다 (v0.4.1).

### sensing_results (v0.4)

```json
{
  "_id": "res-20261017-000123",
  "seq": 1,
  "savedAtTime": "2026-10-17T12:00:02.150Z",
  "resultId": "res-20261017-000123",
  "observedAt": "2026-10-17T12:00:02+00:00",
  "savedAt": "2026-10-17T12:00:02.150+00:00",
  "room": "kitchen", "present": true, "confidence": 0.91,
  "activity": "standing", "activityConfidence": 0.8,
  "modelVersion": "fusion-0.1", "validSec": 5
}
```

재실 판단 담당이 MQTT(`home/edge/result`)로 보낸 결과를 그대로 저장합니다. 형식이 확정되기 전이라 위에 없는 필드도
함께 저장됩니다. `savedAtTime`은 자동 삭제(TTL)용 날짜 값이고 API 응답에는 포함되지 않습니다.

### voice_commands (v0.6)

```json
{
  "_id": "voice-20261024-1a2b3c4d",
  "seq": 1,
  "receivedAtTime": "2026-10-24T12:00:00.250Z",
  "voiceId": "voice-20261024-1a2b3c4d",
  "text": "욕실 조명 켜줘", "lang": "ko-KR", "confidence": 0.92, "source": "voice",
  "recognizedAt": "2026-10-24T21:00:00+09:00",
  "receivedAt": "2026-10-24T12:00:00.250+00:00",
  "expiresAt": "2026-10-24T12:00:10.250+00:00",
  "status": "executed",
  "decisionId": "dec-voice-001",
  "answer": "욕실 조명을 켤게요.",
  "requiresConfirmation": true,
  "confirmText": "욕실 조명을 켤까요?",
  "confirmDeadline": "2026-10-24T12:00:32.300+00:00",
  "confirmedAt": "2026-10-24T12:00:05.100+00:00",
  "pendingActions": [],
  "actions": [ { "device": "light", "deviceId": "light-00", "action": "on", "status": "sent", "commandId": "cmd-20261024-..." } ],
  "updatedAt": "2026-10-24T12:00:05.200+00:00"
}
```

대시보드가 보낸 음성 명령 문장과 처리 결과입니다 (`docs/VOICE.md`). `status`는 received / thinking / confirm_required /
executed / answered / cancelled / timeout / failed 중 하나입니다. `pendingActions`는 사용자 확인을 기다리는 제어로,
확인 대기 중에 서버를 다시 켜도 이어서 실행할 수 있도록 저장합니다. 음성 문장은 개인정보라 `receivedAtTime` 기준
30일(`VOICE_COMMAND_TTL_DAYS`) 뒤 자동 삭제됩니다.

## 인덱스

| 컬렉션 | 인덱스 | 용도 |
| --- | --- | --- |
| `telemetry_logs` | `receivedAt` (TTL) | 보관 기간이 지난 로그 자동 삭제 |
| `telemetry_logs` | `deviceId`, `receivedAt` | 기기별 시간순 조회 |
| `safety_events` | `seq` | 발생 순서대로 불러오기 |
| `commands` | `issuedAt` | 최근 명령 불러오기 |
| `sessions` | `startedAt` | 최근 세션 불러오기 |
| `fall_incidents` | `detectedAt` | 최근 사건 불러오기 |
| `sms_logs` | `seq` | 발송 순서대로 불러오기 |
| `ai_decisions` | `seq` | 받은 순서대로 불러오기 |
| `sensing_results` | `seq` | 받은 순서대로 불러오기 |
| `sensing_results` | `savedAtTime` (TTL) | 보관 기간(`SENSING_RESULT_TTL_DAYS`, 기본 7일)이 지난 결과 자동 삭제 |
| `voice_commands` | `seq` | 받은 순서대로 불러오기 |
| `voice_commands` | `receivedAtTime` (TTL) | 보관 기간(`VOICE_COMMAND_TTL_DAYS`, 기본 30일)이 지난 음성 명령 자동 삭제 |

인덱스는 서버가 DB에 연결될 때 자동으로 만들어집니다.

## 시작 시 불러오는 범위

메모리 사용을 제한하기 위해 최근 것만 불러옵니다. 그보다 오래된 것은 DB에는 남아 있지만 API로는 조회되지 않습니다.

| 종류 | 불러오는 개수 |
| --- | --- |
| 안전 이벤트 | 최근 1,000건 |
| 제어 명령 | 최근 500건 |
| 조리 세션 | 최근 200건 |
| 낙상 사건 | 최근 200건 |
| 문자 발송 이력 | 최근 200건 |
| AI 판단 기록 | 최근 500건 |
| 최종 재실 판단 결과 | 최근 5,000건 (1초마다 오면 약 1시간 20분) |

## 용량

무료 등급은 512MB까지입니다. 가장 빨리 쌓이는 것은 `telemetry_logs`로, 3초 간격이면 하루 약 2만 9천 건입니다.
7일 보관 기준으로 수십 MB 수준으로 예상되며(실측은 아님), 부족해지면 `TELEMETRY_LOG_TTL_DAYS`를 줄이면 됩니다.
`sensing_results`도 1초 간격이면 하루 약 8만 6천 건이라, 부족해지면 `SENSING_RESULT_TTL_DAYS`를 줄이면 됩니다.
