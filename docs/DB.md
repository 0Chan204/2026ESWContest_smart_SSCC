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
| `commands` | 명령 ID | 화구 제어 명령과 처리 상태 | 인덕션 제어 |
| `safety_events` | 이벤트 ID | 안전 이벤트 이력 | 안전 이벤트 |
| `sessions` | 세션 ID | 조리 세션과 타임라인 | 대시보드 화면 |
| `presence` | 방 이름 | 방별 최신 재실 판단 결과 | AI 재실 판단 |
| `fall_incidents` | 사건 ID | 낙상 사건과 확인 토큰 | 낙상 사고 감지 |
| `runtime_state` | 고정 키 | 진행 중인 세션, 부재 단계 | 내부용 |

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
{ "_id": "fall-safety", "autoReportSec": 60 }
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
  "action": "인덕션 비상 전원 차단 + 보호자 SMS 발송",
  "reasoning": "modelVersion=fall-detector-0.1"
}
```

`seq`는 발생 순서를 보장하기 위한 일련번호입니다. `type` 13종은 `app/schemas.py`의 `SafetyEventType` 참고.

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
  "autoReportAt": "2026-10-05T03:01:00+00:00",
  "eventId": "evt-033aac118458", "resolvedAt": null, "reportedAt": null
}
```

`status`: `pending` → `resolved` / `reported` / `auto_reported`. `token`은 API 응답에는 포함되지 않습니다.
서버가 재시작되면 `pending` 상태인 사건의 자동 신고 타이머를 `autoReportAt` 기준으로 다시 겁니다.

### runtime_state

```json
{ "_id": "active_sessions", "values": { "induction-01": "session-1a2b3c4d5e6f" } }
{ "_id": "absence_stages", "values": { "kitchen": "reduce" } }
```

재시작 후에도 진행 중인 조리 세션과 부재 단계를 이어가기 위한 내부 상태입니다.

## 인덱스

| 컬렉션 | 인덱스 | 용도 |
| --- | --- | --- |
| `telemetry_logs` | `receivedAt` (TTL) | 보관 기간이 지난 로그 자동 삭제 |
| `telemetry_logs` | `deviceId`, `receivedAt` | 기기별 시간순 조회 |
| `safety_events` | `seq` | 발생 순서대로 불러오기 |
| `commands` | `issuedAt` | 최근 명령 불러오기 |
| `sessions` | `startedAt` | 최근 세션 불러오기 |
| `fall_incidents` | `detectedAt` | 최근 사건 불러오기 |

인덱스는 서버가 DB에 연결될 때 자동으로 만들어집니다.

## 시작 시 불러오는 범위

메모리 사용을 제한하기 위해 최근 것만 불러옵니다. 그보다 오래된 것은 DB에는 남아 있지만 API로는 조회되지 않습니다.

| 종류 | 불러오는 개수 |
| --- | --- |
| 안전 이벤트 | 최근 1,000건 |
| 제어 명령 | 최근 500건 |
| 조리 세션 | 최근 200건 |
| 낙상 사건 | 최근 200건 |

## 용량

무료 등급은 512MB까지입니다. 가장 빨리 쌓이는 것은 `telemetry_logs`로, 3초 간격이면 하루 약 2만 9천 건입니다.
7일 보관 기준으로 수십 MB 수준으로 예상되며(실측은 아님), 부족해지면 `TELEMETRY_LOG_TTL_DAYS`를 줄이면 됩니다.
