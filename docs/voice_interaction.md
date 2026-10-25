# 음성 명령 및 사용자 상호작용

## 범위와 확인한 계약

최초 음성 연동은 팀 `HomeVIS-Backend` develop의 `00e59be71050bb5c4081ecd19f912d42f4abb2f0`에서
`docs/VOICE.md`, `docs/AI-INTEGRATION.md`, `app/schemas.py`, `voice_service.py`, `ai_service.py`,
관련 router의 v0.6 계약으로 구현했습니다. 2026-10-26에는 `fb22929879d255f6c1788f465df48c941b9338b7`의
v0.7을 확인해 공청기·시작어 메타데이터·확인 기반 인덕션 ON·즉시 OFF를 확장했습니다.
배포된 서버도 v0.7을 지원해야 합니다. [추가 자동화와 계약 한계](home_automation_v07.md)도 참고하세요.
실제 서버·브로커·가전과의 연결 시험을 대신하는 문서는 아닙니다.

기존 중앙 판단, confidence 계산, FeedbackManager/WeightManager, 낙상 상태 머신,
자동 전등·화력 감소/복구·기상 출수와 기존 AlertService/TTS 구현은 유지했습니다.
기존 실행기에서 빠져 있던 `CentralController.feedback_llm` 연결과 HTTP 센싱 + 음성 MQTT 병행을 추가했습니다.

## 실행 흐름

```text
백엔드 STT → MQTT home/voice/request (QoS 1, retain=false)
  → 기존 MQTTSource/InputRouter → SQLite voice_requests (voiceId 중복 제거)
  → bounded 음성 worker → 공유 LLM IntentClassifier
     ├─ 질문: 필요한 GET 또는 저장된 판단 근거 조회
     ├─ 명시적 평가: 기존 피드백 해석 → owner thread에서 기존 학습 함수
     ├─ 직접 제어: 최신 기기 상태 + 안전 검증 + 승인 필요 (인덕션 OFF만 즉시 요청)
     └─ 장기 설정: proposed 저장만 (활성화 없음)
  → SQLite에 확정 JSON 저장 → 별도 HTTP worker
  → POST /api/v1/ai/decisions (voice_command, voiceId, announcement)
  → 백엔드 확인 화면 / 대시보드 / TTS / 기기 실행
```

중앙 판단은 기존 host의 기본 0.1초 tick으로 계속 실행합니다. MQTT 콜백은 크기가 제한된 큐에 넣기만 합니다.
LLM·조회 HTTP·전송 HTTP는 controller/SQLite를 직접 건드리지 않는 별도 worker에서 실행합니다.
SQLite와 피드백 변경의 소유자는 기존 main thread 하나입니다. 기존 학습 함수의 파일 저장 작업은 여기서 수행하므로
디스크 I/O 지연까지 없는 hard real-time 보장은 아닙니다.

## Windows 준비와 실행

저장소 루트에서 Python 3.11 이상을 사용합니다. 아래 설치 명령은 기존 실행기와 동일합니다.

```powershell
python -m pip install -r requirements-runtime.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`.env`에서 보드 주소와 provider를 설정합니다. 키는 본인 환경에만 저장합니다.

```ini
HOMEVIS_MODE=live
HOMEVIS_BACKEND_URL=http://192.168.0.2:8000
HOMEVIS_MQTT_HOST=192.168.0.2
HOMEVIS_MQTT_PORT=1883
HOMEVIS_SENSING_SOURCE=backend
HOMEVIS_VOICE_ENABLED=true
HOMEVIS_VOICE_TOPIC=home/voice/request
LLM_PROVIDER=exaone
FRIENDLI_API_KEY=
```

GPT는 `LLM_PROVIDER=gpt`, `OPENAI_API_KEY`, 계정에서 사용할 수 있는 `OPENAI_MODEL`을 설정합니다.
Qwen은 기존 로컬 설치·모델 설정을 그대로 사용합니다. `none`이면 안전한 재질문만 하며 제어·학습하지 않습니다.
API provider를 선택하면 Qwen을 로딩하지 않습니다. 음성·피드백·기존 안내는 하나의 지연 생성 LLM/client를 공유합니다.

```powershell
python -m src.integration --check-config
python -m src.integration
```

`Ctrl+C`로 종료합니다. `HOMEVIS_SENSING_SOURCE=mqtt`이면 기존 센싱 토픽과 음성 토픽을 같은 MQTT 연결로 받습니다.
`backend`이면 센싱은 기존 `/api/v1/sensing/results` 폴링, 음성은 MQTT로 받습니다.
기기 상태는 기존 주기적 GET을 계속 사용하고, 음성 질의에서 필요할 때 별도 최신 조회를 추가합니다.

백엔드 관리자와 협의해 실제 AI 연결 전 가짜 판정 엔진만 중지하세요. 이 명령은 백엔드 compose 디렉터리용입니다.

```powershell
docker compose --profile sim stop voice-ai-simulator
```

고정 MQTT `client_id`는 `config/homevis.toml`의 `[mqtt]`에서 설정합니다. 기본 `homevis-ai`를 사용하는 프로세스는
하나만 실행하세요. 다른 데이터 디렉터리의 두 번째 AI도 같은 음성 요청을 구독하면 안 됩니다.
브로커 ACL·인증·TLS를 설정하기 전에는 신뢰할 수 있는 사설망에서만 사용하세요.

## 설정과 제한 시간

`[voice]` 기본값은 disabled, 큐 16건, LLM 작업 예산 5초, HTTP timeout 1.5초,
송신 여유 2초, 복구 조회 5초, 확인 결과 조회 2초입니다.
`expiresAt`을 최종 마감으로 사용하며 LLM/조회 예산은 `min(now+5초, expiresAt-2초)`입니다.
마감 직전에는 무제어 기본 안내만 준비하고, 송신 예산이 부족하거나 이미 만료되면 POST하지 않습니다.
HTTP worker에서도 실제 POST 직전에 만료를 다시 검사합니다.

음성 API 호출은 SDK `with_options(timeout=남은시간,max_retries=0)`를 사용해 기존 공유 connection pool을 재사용합니다.
기존 비음성 호출의 provider timeout/retry 설정은 바꾸지 않습니다. POST 재시도는 임시 네트워크/408/429/5xx에 한해
마감 내 최대 3회이며 **같은 decisionId와 같은 저장 본문**을 사용합니다.
SDK의 소켓 timeout은 전체 벽시계 기한을 보장하지 않으므로 owner thread에서도 늦은 결과를 버립니다.
공식 SDK 동작은 [OpenAI Python reference](https://developers.openai.com/api/reference/python)를 기준으로 확인했습니다.

Qwen 초기 로딩이나 GPU 추론은 Python thread에서 강제 중단하지 않습니다. 하나의 bounded daemon worker만 유지하고
지연 결과를 버리므로 중앙 루프는 계속 진행하지만, 느린 Qwen은 10초 응답을 만족하지 못할 수 있습니다.
종료/비정상 중단 시 learning의 불확실한 상태는 자동으로 재학습하지 않습니다.

## 의도·신뢰도·학습 정책

9개 의도: `explanation_question`, `status_question`, `feedback`, `control_request`,
`control_instruction`, `preference_change`, `confirmation`, `general_question`, `unknown`.
의도 JSON은 허용 라벨·필드·타입·파라미터와 실제 발화의 인용 근거를 검증합니다.
설명 + 평가 같은 복합 의도를 허용하지만, 즉시 제어와 다른 의도가 섞이면 추가 확인을 요청합니다.
LLM은 action_id·user_id·deviceId를 생성하지 못합니다. deviceId는 조회된 기기에서만 선택합니다.

- STT 신뢰도: 입력값 그대로 저장. 없다고 높은 값을 채우지 않습니다.
- Intent 신뢰도: 모델 분류값. 기본 0.8 미만이면 재질문합니다.
- 음성 응답 confidence: STT가 있으면 `min(STT,Intent)`, 없으면 Intent만 사용하고 근거를 기록합니다.
  제어/학습에는 STT 0.6 이상이 필요합니다. 이 값은 물리 실행 확률이나 중앙 판단 점수가 아닙니다.
- 중앙 판단 confidence와 피드백 해석 confidence는 기존 별도 계산/기준을 유지합니다.

“왜 껐어?”는 학습하지 않습니다. “너무 빨리 껐어”, “잘했어” 등 명시적 평가일 때만 기존
`NaturalLanguageFeedbackInterpreter → NaturalLanguageFeedbackService → FeedbackManager → WeightManager`를 사용합니다.
worker가 해석한 결과를 정확히 동일한 프롬프트로 main thread에서 재사용하여 LLM을 두 번 호출하지 않습니다.

최근 기본 30분/최대 100건에서 기기·구역·동작을 통해 대상 하나가 확인되어야 합니다.
대상 없는 “잘했어”는 가장 최근 동작에 임의 연결하지 않습니다. 직전 명확한 설명의 대화 맥락만 60초간 재사용합니다.
모델이 발화에 없는 기기·동작을 만들어도 학습 대상으로 인정하지 않으며, 발화에 없는 구역으로 복수 이력을 임의 축소하지 않습니다.
백엔드 `sent` 기록, 실제 자동화 action, 사용자, weight profile, 중복 반영 여부도 확인합니다.
STT에는 사용자 인증이 없으므로 `[voice].user_id`는 **단일 거주자 배포 설정**이지 음성 화자 인증이 아닙니다.
여러 사람이 사용하는 환경에서는 본인 식별 계약을 추가하기 전 학습 기능을 사용하지 마세요.

`FEEDBACK_APPLY_THRESHOLD=0.8`, `FEEDBACK_REVIEW_THRESHOLD=0.5` 및 기존 학습률/공식은 변경하지 않았습니다.
legacy 가중치 파일과 피드백 JSONL은 SQLite와 하나의 트랜잭션이 아니므로, 학습 시작 전에 action_id를 영속 예약합니다.
예약 뒤 비정상 종료되면 해당 action을 자동 재시도하지 않습니다(at-most-once). 관리자가 기존 가중치/학습 기록을 확인해야 합니다.

## 사용자 지시와 설명

`RoutineManager`는 관측 루틴용이므로 기존 것을 바꾸지 않고 같은 outbox SQLite에 `user_instructions`를 추가했습니다.
instruction_id, source_voice_id, user_id, 원문, 의도, device/scenario/parameters, 생성·확인·적용 시각,
status, policy_version, 이전 지시 참조를 보관합니다. 현재 생성되는 상태는 **proposed뿐**이며,
확인·적용 시각은 null입니다. 개별 기기 `requiresConfirmation`을 장기 정책 승인에 재사용하지 않습니다.

실제 중앙 출력의 outbox source에 당시 설정 버전·설정·센싱·기기 상태를 추가 기록합니다.
기존 `explanation`의 action_id, 사용자, scenario, features/weights/contributions/threshold를 재사용합니다.
backend decisionId와 전송 결과는 같은 outbox 행에 있고, 음성 요청의 analysis.action_id가 설명/평가 대상을 참조합니다.
과거 설정으로 기록된 대기 기준을 설명하며 현재 설정으로 과거 판단을 재구성하지 않습니다.
기록에 없는 사용자 지시를 적용했다고 말하지 않습니다. 예전 기록에 스냅샷이 없으면 해당 수치를 추정하지 않습니다.
새 메타데이터 저장 실패가 기존 중앙 출력 자체를 막지 않도록 분리했습니다.

## 안전한 기기 제어

| 기기 | 음성 처리 |
| --- | --- |
| 전등 | on/off/blink/fadeout, 최신 등록 기기 하나가 확인돼야 함 |
| 환풍기 | on/off/set_speed(low/mid/high), 음성 전용 검증만 확장 |
| 공기청정기 | on/off/set_mode(auto/manual), 백엔드 사용자 확인 요청 |
| 정수기 | dispense, 1~2000mL 명시, 기존 준비 상태와 주방 재실 검증 |
| 인덕션 | turn_on은 명시적 1~9단·현재 OFF·주방 재실·온도·위험 검증 후 확인 대기; turn_off는 즉시 요청; set_level(1~9)은 켜짐 상태에서만 |
| 화력 복구 | HomeVIS 감소 이력과 이후 실제 낮은 화력 관측, 복귀 시간·온도 등 기존 `_revalidate` 재사용. 외출 전체 OFF 이후의 불명확한 복구는 보류 |

상태 변경에는 `requiresConfirmation=true`를 사용하되 인덕션 `turn_off`만 false로 즉시 요청합니다.
위험·미해결 낙상·외출 전체 OFF와 충돌하는 일반 제어는 막습니다. 사용자의 발화가 안전 정책을 우회하지 않습니다.
추가 검증으로 live의 인덕션 ON·화력 증가·복구에 온도 유효성 계약 확인을 요구합니다.
현재 `[backend].stove_temperature_validity_verified=false`이므로 해당 요청은 보류됩니다.
기기 heartbeat의 최신성은 온도 센서의 정상 측정을 증명하지 않습니다. OFF는 이 차단과 무관하게 요청 가능합니다.
“괜찮아”가 낙상 종료나 임의 실행 승인이 되지 않습니다. 기존 백엔드 낙상 상태 API와 확인 화면을 사용해야 합니다.

주의: 백엔드 확인 후 실행은 별도 AI 재검증 없이 진행되는 현재 계약입니다.
승인 대기 중 상황이 변하는 경우의 최종 안전 검증/취소, 정수기 컵·넘침 감지, 실제 하드웨어 interlock은
백엔드/하드웨어와 추가 확인해야 합니다. AI의 송신 전 검증만으로 실제 장치 안전이 보장되지는 않습니다.

## MQTT / HTTP 계약

MQTT 3.1.1, 고정 client ID, `clean_session=False`, QoS 1. retained 입력·잘못된 JSON·NaN/Infinity·빈 문장·만료 요청을 거절합니다.
원문 500자, 메시지 전체 크기는 기존 MQTT 제한(기본 65536 bytes)을 적용합니다.

v0.7의 선택 필드 `rawText`(원본 발화), `wakeWord`(boolean)를 보존합니다.
의도 분류에는 백엔드가 시작어를 제거한 `text`만 사용합니다. AI는 시작어 감지·제거를 다시 하지 않습니다.
`wakeWord=true/false` 모두 백엔드 계약상 유효하며 이 값만으로 요청을 거절하지 않습니다.
예: `text="인덕션 3단으로 켜줘"`, `rawText="홈비스, 인덕션 3단으로 켜줘"`, `wakeWord=true`.

| API | 용도 / 확인한 응답 |
| --- | --- |
| GET `/api/v1/ai/device-states` | 최신 기기, `{items:[...]}` |
| GET `/api/v1/sensing/results/latest` | 단일 결과 객체, observedAt/validSec 검증, 404/만료 시 모른다고 응답 |
| GET `/api/v1/weather` | available/text/stale/basedOn, 오래된 날씨는 기준 시각 표시 |
| GET `/api/v1/voice/commands?limit=10` | 음성 이력 `{items,total}` |
| GET `/api/v1/voice/commands?status=thinking` | 시작/재연결/주기적 유실 복구 `{items,total}` |
| POST `/api/v1/ai/decisions` | voice_command, voiceId/announcement/actions/requiresConfirmation/expiresAt |
| GET `/api/v1/ai/decisions/{decisionId}` | 확인 후 executed/cancelled 등을 조회, 재POST하지 않음 |

음성 전용 validator를 사용합니다. 일반 자동화의 reason/room 검증은 유지하되 `away_all_off`에만 room 생략과 빈 actions를 허용합니다.
구역을 확인할 수 없는 일반 답변은 v0.7의 optional room을 생략합니다.
awaiting_confirmation/pending, executed/sent·rejected·failed, expired, cancelled,
실제 서버가 반환할 경우 answered, 200 duplicate=true와 202 신규 응답을 구분합니다.
404는 새 ID를 만들어 재시도하지 않습니다. `executed/sent`는 **물리 실행 ACK가 아닙니다**.

백엔드는 음성 `voice.status.answer`와 `ai.announcement`를 모두 내보낼 수 있습니다.
대시보드가 voiceId 있는 announcement를 중복 재생하지 않는 계약을 확인했습니다.
AI의 새 음성 경로는 WAV/STT/TTS/AudioPlayer를 생성하지 않습니다.
기존 위험·낙상 로컬 AlertService 및 백엔드 announcement 경로는 이 작업에서 변경하지 않았으므로,
배포 환경의 기존 경고 중복 재생 여부는 별도 음성 출력 통합 시험이 필요합니다.

## 영속성과 운영

기존 `output/integration/{mock|live}/outbox.sqlite3` 연결에 `voice_requests`,
`voice_feedback_claims`, `user_instructions`를 추가합니다. 정확한 파일명은 `IntegrationConfig.outbox_path`를 따릅니다.
큐/worker는 bounded이고, 재시작 후 pending 본문/ID는 불변입니다.
확인 대기는 원래 요청 expiresAt 이후에도 GET으로 추적하며 POST를 반복하지 않습니다.
완료 ID를 삭제하면 중복 방지 근거를 잃으므로 자동 삭제하지 않습니다.
이력/발화는 개인정보이므로 데이터 디렉터리 접근 권한·보관 기간·백업 정책을 별도로 정하세요.
상태 JSON/진단 로그에는 원문이나 API 키 대신 상태 수와 오류 종류만 기록합니다.
`.env`와 `output/*`는 기존 `.gitignore`로 제외됩니다.

## 파일별 구현과 재사용

| 파일 | 역할 |
| --- | --- |
| `src/interaction/config.py`, `contracts.py` | opt-in 설정, 음성 전용 입력/출력 검증 |
| `intent.py`, `response.py` | 의도 분류, 검증된 사실 기반 짧은 한국어 응답 |
| `storage.py`, `explanation.py` | SQLite 중복/학습 예약·제안 저장, 당시 이력 설명 |
| `control.py`, `backend.py` | 제어 안전 검증, 기존 인증 transport를 쓰는 확정 API |
| `coordinator.py`, `worker.py` | 별도 bounded 작업, 마감·복구·승인 조회 |
| `src/llm/shared.py` | 한 모델/client 공유, 요청별 deadline, 피드백 추론 재사용 |
| `src/integration/{runtime,mqtt_source,host,settings,__main__,backend_client}.py` | 기존 실행기에 최소 연결 |
| `tests/test_voice_interaction.py` | 외부 I/O 없는 통합·실패·복구·안전·학습 테스트 |
| `config/homevis.toml`, `.env.example`, `README.md` | 설정과 실행 안내 |

기존 LLM factory/adapters/prompts, 실제 FeedbackService/Manager/WeightManager, DecisionHistory,
SQLite Outbox, 중앙 판단 엔진을 호출하며 별도 학습 알고리즘이나 가전 실행기를 만들지 않았습니다.

## 테스트

```powershell
python -m pip install pytest
python -m pytest tests/test_voice_interaction.py -q
python -m pytest -q
python -m src.integration --mode mock --duration 5
```

실제 API smoke test는 기존 명시적 opt-in 절차에만 남아 있습니다. 위 자동 테스트는 Mock LLM/HTTP와
연결하지 않는 MQTT client를 사용하며 유료 API나 실가전을 호출하지 않습니다.
선택적 교차 저장소 schema 검증은 `HOMEVIS_BACKEND_CHECKOUT`이 각 테스트에 고정된 backend commit(v0.6/v0.7)을 포함한 로컬 clone을 가리킬 때 실행됩니다.
Python 3.11 대상 문법으로 작성했으며 이번 개발 환경 실제 실행 버전은 Python 3.13입니다.

2026-10-24 Windows / Python 3.13.5 검증 결과:

- 전체 pytest: **541 passed, 2 skipped** (고정 backend checkout schema 검증 포함).
- 음성 전용 테스트: **106 passed**.
- 건너뛴 2건은 명시적으로 활성화해야 하는 EXAONE/GPT 실제 유료 API 테스트입니다.
- 음성 enabled 상태의 `--check-config`, Mock 연속 실행과 정상 종료 확인.
- 새 모듈 Python 3.11 문법 검사, `git diff --check`, `.env`/출력 디렉터리 Git 제외 확인.
- 실제 가전, 실서버, 유료 LLM, LG OS 현장 실행은 수행하지 않았습니다.

위 결과는 최초 음성 연동 당시 기록입니다. v0.7 추가·최신 전체 회귀 결과는 [신규 통합 검증](home_automation_v07.md#검증)을 참고하세요.

## 아직 현장에서 확인할 사항

- 실제 배포 백엔드의 v0.7 지원, MQTT 인증/ACL/TLS, 동일 client ID 충돌 방지, simulator 중지.
- 최종 센싱 생성기의 구역 매핑·측정 시각·validSec·행동 입력. 현재 Wi-Fi 위치만으로 낙상/기상 행동을 만들어내지 않음.
- 장기 설정 영구 승인/취소 계약, 다중 사용자 본인 식별 계약. 현재 proposed 및 단일 사용자 범위만 지원.
- 승인 시점 최종 안전 검증, 가전 ACK, 대시보드 TTS 중복 제거와 출력 장치.
- Raspberry Pi 5의 LG 커스텀 OS: Python 3.11+, 패키지/CPU wheel, 쓰기 가능한 데이터 경로,
  시간 동기화, 네트워크/인증서, supervisor/자동 재시작, 리소스와 실제 응답 지연.
  Linux/webOS/LG 전용 오디오 API 존재를 가정하지 않았으며 현장 OS에서 실행 검증하지 않았음.
