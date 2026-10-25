# 음성 명령 연동 명세 (v0.7)

대시보드가 브라우저 음성 인식으로 만든 **전체 문장**을 서버가 받아 저장하고, AI 판정 엔진에 MQTT로 전달합니다.
판정 엔진은 판단(답변·제어)을 HTTP로 돌려주고, 서버는 실행 결과와 진행 상황을 WebSocket으로 대시보드에 알립니다.

```
① 대시보드 ── HTTP POST /api/v1/voice/commands ──▶ 서버 (DB 저장)
② 서버 ── MQTT home/voice/request ──▶ AI 판정 엔진
③ AI 판정 엔진 ── HTTP GET (기기 상태·재실 결과·음성 기록 등, 필요할 때) ──▶ 서버
④ AI 판정 엔진 ── HTTP POST /api/v1/ai/decisions (voiceId 포함) ──▶ 서버 (실행·저장)
⑤ 서버 ── WebSocket voice.status ──▶ 대시보드 (진행 상황·답변·확인 창)
⑥ 대시보드 ── HTTP POST /api/v1/voice/commands/{voiceId}/confirm ──▶ 서버 (확인 창 결과)
```

화면 이동 명령("주방", "기록 보여줘", "설정", "우리 집")은 대시보드가 직접 처리하고 서버로 보내지 않습니다.

## 시작어 "홈비스" (v0.7)

- 대시보드가 "홈비스"를 감지하면 그 문장을 보냅니다. 서버는 문장 앞의 시작어를 떼어 내고 `wakeWord: true`로 판정 엔진에 전달합니다.
  예) "홈비스, 욕실 조명 켜줘" → `text: "욕실 조명 켜줘"`, `rawText: "홈비스, 욕실 조명 켜줘"`, `wakeWord: true`
- 음성 인식이 "홈 비스", "홈비즈", "홈비쓰", "홈비스야", "HomeVIS"처럼 적어도 시작어로 처리합니다.
- 시작어만 있고 뒤 문장이 없으면 422입니다. 시작어 없이 보낸 문장은 `wakeWord: false`로 그대로 전달합니다.
- 시작어 뒤 문장에 정해진 단어 규칙은 없습니다. 어떤 가전을 어떻게 할지는 판정 엔진이 문장을 해석해서 정합니다.
- **음성으로 인덕션을 켜는 동작**(`turn_on`, `set_level`, `restore_power`)은 판정 엔진이 `requiresConfirmation: false`로 보내도
  서버가 항상 확인 창을 띄웁니다. 인덕션 끄기는 바로 실행합니다.

## 1. 상태

| status | 의미 | 대시보드 표시 |
| --- | --- | --- |
| `received` | 서버가 받음 (POST 응답) | 알아들었어요 |
| `thinking` | 판정 엔진에 전달, 판단 대기 | 확인하고 있어요 |
| `confirm_required` | 제어 전에 사용자 확인 필요 | 확인 창 (`confirmText`) |
| `executed` | 제어 실행 완료 | 결과 + `answer` 읽기 |
| `answered` | 제어 없이 답변만 (거절 포함) | 결과 + `answer` 읽기 |
| `cancelled` | 사용자가 취소했거나 확인 시간(30초) 초과 | 잘 듣지 못했어요 |
| `timeout` | 판정 엔진 응답 없음 (10초) | 잘 듣지 못했어요 |
| `failed` | 판정 엔진에 전달 실패 | 지금은 음성 명령을 쓸 수 없어요 |

대기 시간은 `.env`의 `VOICE_AI_TIMEOUT_SEC`(기본 10), `VOICE_CONFIRM_TIMEOUT_SEC`(기본 30)로 바꿀 수 있습니다.

## 2. 대시보드 ↔ 서버

### 문장 보내기: `POST /api/v1/voice/commands`

```json
{ "text": "욕실 조명 켜줘", "lang": "ko-KR", "confidence": 0.92, "source": "voice", "recognizedAt": "2026-10-24T21:00:00+09:00" }
```

- `text`만 필수입니다 (1~500자). 나머지는 생략할 수 있습니다.
- 응답 202: `{ "voiceId": "voice-20261024-1a2b3c4d", "status": "received", "receivedAt": "..." }`
- 503: 판정 엔진에 전달하지 못함 (브로커 연결 끊김 등). "지금은 음성 명령을 쓸 수 없어요"를 표시합니다.

### 진행 상황: WebSocket `/api/v1/stream`의 `voice.status`

같은 `voiceId`의 이벤트만 처리합니다. `data`는 음성 명령 기록 전체입니다.

```json
{ "voiceId": "voice-20261024-1a2b3c4d", "text": "욕실 조명 켜줘", "status": "confirm_required",
  "answer": "욕실 조명을 켤게요.", "confirmText": "욕실 조명을 켤까요?", "confirmDeadline": "...",
  "actions": [], "decisionId": "dec-voice-001", "updatedAt": "..." }
```

```json
{ "voiceId": "voice-20261024-1a2b3c4d", "status": "executed", "answer": "욕실 조명을 켤게요.",
  "actions": [ { "device": "light", "deviceId": "light-00", "action": "on", "status": "sent", "commandId": "cmd-..." } ] }
```

- 답변 음성은 `voice.status`의 `answer`만 재생합니다. 같은 문장이 `ai.announcement`로도 가는데,
  그쪽에는 `voiceId`가 들어 있으므로 `voiceId`가 있는 `ai.announcement`는 재생하지 않으면 됩니다.
- 확인 창 문구(`confirmText`)는 서버가 기기 이름과 동작으로 만듭니다.
  예) "욕실 조명을 켤까요?", "주방 환풍기 풍량을 강으로 바꿀까요?", "욕실 조명 켜기, 주방 환풍기 끄기를 실행할까요?"

### 확인 창 결과: `POST /api/v1/voice/commands/{voiceId}/confirm`

```json
{ "approved": true }
```

- `true`: 보류한 제어를 실행 → `executed` / `false`: 취소 → `cancelled`
- `confirm_required`가 아닌 명령에 보내면 409, 없는 `voiceId`면 404

### 기록: `GET /api/v1/voice/commands?status=&limit=50`, `GET /api/v1/voice/commands/{voiceId}`

최신순입니다. `status`로 거를 수 있습니다.

## 3. 서버 ↔ AI 판정 엔진

### 음성 문장 받기: MQTT `home/voice/request` (서버 → 판정 엔진, QoS 1, retain 없음)

```json
{
  "voiceId": "voice-20261024-1a2b3c4d",
  "text": "욕실 조명 켜줘",
  "rawText": "홈비스, 욕실 조명 켜줘",
  "wakeWord": true,
  "lang": "ko-KR",
  "confidence": 0.92,
  "source": "voice",
  "recognizedAt": "2026-10-24T21:00:00+09:00",
  "receivedAt": "2026-10-24T12:00:00.250+00:00",
  "expiresAt": "2026-10-24T12:00:10.250+00:00"
}
```

- `expiresAt`까지 판단이 오지 않으면 서버가 `timeout` 처리합니다. 그 뒤에 온 판단은 실행하지 않습니다.
- QoS 1이라 같은 메시지가 두 번 올 수 있습니다. `voiceId`로 한 번만 처리해 주세요.
  서버도 같은 `voiceId`에는 처음 판단 하나만 실행합니다.
- 고정 client ID + `clean_session=False`로 접속하면 잠깐 끊긴 동안의 메시지를 브로커가 보관해 줍니다.
  놓친 명령은 `GET /api/v1/voice/commands?status=thinking`으로 확인할 수 있습니다.

### 판단 보내기: `POST /api/v1/ai/decisions` (기존 API에 `voiceId`, `requiresConfirmation` 추가)

```json
{
  "decisionId": "dec-voice-001",
  "voiceId": "voice-20261024-1a2b3c4d",
  "scenario": "voice_command",
  "confidence": 0.9,
  "timestamp": "2026-10-24T21:00:02+09:00",
  "room": "toilet",
  "announcement": "욕실 조명을 켤게요.",
  "requiresConfirmation": true,
  "actions": [ { "device": "light", "deviceId": "light-00", "action": "on" } ]
}
```

| 경우 | 보내는 값 | 결과 |
| --- | --- | --- |
| 상태 질문 답변, 거절 | `announcement`만, `actions: []` | `answered` |
| 바로 실행 | `actions` + `requiresConfirmation: false` | 즉시 실행 → `executed` |
| 확인 후 실행 | `actions` + `requiresConfirmation: true` | 판단 기록 `status: awaiting_confirmation`, 액션 `pending` → 사용자가 "실행"을 누르면 실행 |

- `announcement`가 사용자에게 들려줄 답변입니다. 확인이 필요한 경우 실행 뒤에 읽어 줍니다.
- 없는 `voiceId`면 404, 이미 끝난(시간 초과·다른 판단이 연결된) 음성 명령이면 실행하지 않고 `status: expired`로 기록합니다.
- 확인 후 실행된 결과는 `GET /api/v1/ai/decisions/{decisionId}`의 `actions`, `status`로 확인합니다.

## 4. 테스트

```bash
docker compose --profile sim up -d     # 가짜 판정 엔진(tests/simulate_voice_ai.py) 포함
curl -s -X POST localhost:8000/api/v1/voice/commands -H 'Content-Type: application/json' -d '{"text":"욕실 조명 켜줘"}'
curl -s localhost:8000/api/v1/voice/commands | python3 -m json.tool
```

가짜 판정 엔진은 키워드 규칙으로 조명·환풍기는 확인 후 실행, 인덕션·물은 거절 안내, 그 외는 켜진 기기 수를 답합니다.
