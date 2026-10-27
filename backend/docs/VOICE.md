# 음성 명령 연동 명세 (v0.9)

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

(v0.9) 보드(라즈베리파이)에는 브라우저 음성 인식이 없어서, **보드 마이크 버튼**으로 서버가 직접 녹음·음성 인식을 하고
①을 대신합니다. 이후 ②~⑥은 같습니다. → [5장](#5-보드-마이크-v09)

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
| `listening` | (v0.9) 보드 마이크로 듣는 중 | 듣고 있어요 |
| `recognizing` | (v0.9) 음성 인식 중. 인식되면 `text`를 담아 한 번 더 옴 | 알아듣는 중… + 들린 문장 |
| `received` | 서버가 받음 (POST 응답) | 알아들었어요 |
| `thinking` | 판정 엔진에 전달, 판단 대기 | 확인하고 있어요 |
| `confirm_required` | 제어 전에 사용자 확인 필요 | 확인 창 (`confirmText`) |
| `executed` | 제어 실행 완료 | 결과 + `answer` 읽기 |
| `answered` | 제어 없이 답변만 (거절 포함) | 결과 + `answer` 읽기 |
| `cancelled` | 사용자가 취소했거나 확인 시간(30초) 초과 | 잘 듣지 못했어요 |
| `timeout` | 판정 엔진 응답 없음 (10초) | 잘 듣지 못했어요 |
| `failed` | 실패. `reason`: `mic_unavailable`(마이크 없음) · `no_speech`(말소리 없음) · `stt_error`(인식 실패) · `publish_failed`(판정 엔진에 전달 실패) · `interrupted`(듣는 중 서버 재시작) | 이유별 문구 |

대기 시간은 `.env`의 `VOICE_AI_TIMEOUT_SEC`(기본 10), `VOICE_CONFIRM_TIMEOUT_SEC`(기본 30)로 바꿀 수 있습니다.

(v0.12) **자동 승인**: `.env`에 `VOICE_AUTO_CONFIRM=true`를 넣으면 판정 엔진이 `requiresConfirmation: true`로 보내도
확인 창을 띄우지 않고 서버가 바로 승인해 실행합니다.

- 판정 엔진에는 평소처럼 `awaiting_confirmation`(제어 `pending`)으로 답하고, 곧바로 확인과 같은 흐름으로 실행합니다 (판정 엔진 수정 불필요).
- 대시보드는 `confirm_required`를 받지 않고 바로 `executed`를 받습니다. 답변(`answer`)은 확인 문구를 바꾼 "~할게요." 문장입니다 (예: "방 조명을 켤게요.").
- **인덕션 켜기·화력 조절(`turn_on`, `set_level`, `restore_power`)은 안전 때문에 이 설정과 상관없이 항상 확인 창을 띄웁니다.**
- 기본값은 `false`(지금처럼 확인 창).

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

## 5. 보드 마이크 (v0.9)

보드 Flutter 앱(프론트 board-app v7)의 마이크 버튼용입니다. 녹음 · 음성 인식(STT) · 음성 안내(TTS)는 서버가 합니다.

```
① 보드 화면 ── POST /api/v1/voice/listen ──▶ 서버 (listening)
② 서버: 보드 USB 마이크 녹음 (pulseaudio parecord) → recognizing
③ 서버 ── OpenAI STT ──▶ 문장 + 신뢰도 → recognizing(text) → 기존 흐름 (received → thinking → 판정 엔진 …)
④ 서버: 확인 문구 · 답변 · 일반 안내를 OpenAI TTS로 보드 스피커에서 재생 (설정 speak)
```

### 듣기 시작 · 취소

| 요청 | 응답 |
| --- | --- |
| `POST /api/v1/voice/listen` `{}` | `202 { voiceId, status: "listening", receivedAt }`. 이미 듣는 중이면 `409`, `detail.voiceId`에 듣고 있는 명령. 서버에서 마이크를 끈 경우 `503` |
| `POST /api/v1/voice/listen/cancel` `{ voiceId }` | 듣는 중 · 인식 중이면 `cancelled`. 이미 판정 엔진에 넘어갔으면 `409`, 없는 id면 `404` |

- 한 번에 하나만 듣습니다. `source`는 `button`입니다 (호출어 상시 듣기는 다음 단계에서 `wakeword`).
- 버튼 뒤 `VOICE_LISTEN_START_SEC`(5초) 안에 말소리가 없으면 `failed(no_speech)`.
  말이 끝나고 `VOICE_LISTEN_SILENCE_SEC`(1초) 조용하면, 또는 `VOICE_LISTEN_MAX_SEC`(8초)가 지나면 녹음을 끝냅니다.
- 시작어("홈비스")는 기존처럼 떼어 내고 `wakeWord: true`로 판정 엔진에 전달합니다. 시작어만 있으면 `no_speech`.
- 대시보드는 20초 동안 소식이 없으면 닫으므로, 녹음 + 인식 + 판단이 그 안에 끝나도록 위 시간을 정했습니다.

### 인식 신뢰도 (`confidence`)

판정 엔진은 `confidence`가 0.6 미만이면 제어하지 않으므로 서버가 채워서 보냅니다.
gpt-4o 계열 STT는 토큰 로그확률(`logprobs`) 평균, whisper는 구간별 `avg_logprob`·`no_speech_prob`로 계산하고,
둘 다 없으면 `VOICE_STT_FALLBACK_CONFIDENCE`(0.8)를 씁니다.

### 음성 설정: `GET` / `PUT /api/v1/voice/settings`

```json
{ "wakeWord": false, "standby": false, "speak": true }
```

| 필드 | 뜻 |
| --- | --- |
| `wakeWord` | 호출어(홈비스)로 부르기. 저장만 하고, 상시 듣기는 다음 단계에서 붙습니다 |
| `standby` | 지금 호출어를 기다리는 중. 상시 듣기가 붙기 전까지 항상 `false` |
| `speak` | 확인 문구 · 답변 · 일반 안내를 보드 스피커로 읽기 (기본 켜짐). 대시보드 "위험 알림 음성 안내"와 연결 |

`PUT`은 보낸 항목만 바꾸고, 바뀐 설정을 WebSocket `voice.settings`로 모든 화면에 알립니다. 서버를 다시 켜도 유지됩니다.

### 보드 스피커 안내

- 읽는 것: `confirm_required`의 `confirmText`, `answered` · `executed`의 `answer`(음성 명령마다 한 번씩),
  `ai.announcement` 중 음성 명령이 아닌 안내
- 한 번에 하나씩 순서대로 읽고, 밀린 안내가 많으면 새 안내는 건너뜁니다. 실패해도 제어 · 판단에는 영향이 없습니다.

### 보드 설정

- `docker-compose.board.yml`: 백엔드 컨테이너에 `/run/pulse/native`(보드 pulseaudio)를 연결하고 `PULSE_SERVER`를 지정합니다.
- 보드 `.env`: `OPENAI_API_KEY`, `VOICE_MIC_DEVICE`(보드에서 `pactl list short sources`로 확인). 그 밖의 값은 `.env.example` 참고
- 인터넷이 없으면 인식은 `failed(stt_error)`, 안내는 건너뜁니다.

### 테스트 (보드)

```bash
curl -s -X POST http://<보드 IP>:8000/api/v1/voice/listen -H 'Content-Type: application/json' -d '{}'
# 바로 마이크에 "홈비스 주방 불 켜줘" → 몇 초 뒤
curl -s "http://<보드 IP>:8000/api/v1/voice/commands?limit=1"
```

