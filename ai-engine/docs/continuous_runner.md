# 연속 탐지·제어 실행기

Python 3.11 이상에서 저장소 루트(`README.md`, `src/`가 있는 폴더)를 작업 디렉터리로 사용합니다.
이 실행기는 센싱 **최종 결과**를 수신하는 AI 프로세스입니다. 브로커·백엔드·Wi-Fi 추론 서버는 실행 중이어야 합니다.
센서 노드의 특징값을 여기서 다시 분류하거나 다른 저장소의 모델을 자동 다운로드하지 않습니다.

## 설치와 한 명령 실행

```sh
python -m pip install -r requirements-runtime.txt
```

`.env.example`을 `.env`로 복사하고 주소를 한 번 설정합니다. 보드에서 함께 실행하면 기본값 `localhost`를,
다른 PC에서 실행하면 `HOMEVIS_BACKEND_URL=http://<보드 IP>:8000`, `HOMEVIS_MQTT_HOST=<보드 IP>`를 사용합니다.
`.env`는 Git에서 제외되며 OS 환경변수가 파일 값보다 우선합니다. 인증은 환경변수의
`HOMEVIS_BACKEND_TOKEN`(Bearer), `HOMEVIS_MQTT_USERNAME/PASSWORD`로 전달하고 로그에는 출력하지 않습니다.
백엔드·MQTT 기본 주소 및 수신 토픽은 `config/decision_policy.toml`의 `[backend]`, `[mqtt]`에서 설정합니다.
MQTT TLS/CA도 같은 파일의 `mqtt.tls/ca_file`이며 `HOMEVIS_MQTT_TLS`, `HOMEVIS_MQTT_CA_FILE`로 덮어쓸 수 있습니다.
클라이언트 ID는 `mqtt.client_id` 또는 `HOMEVIS_MQTT_CLIENT_ID`입니다. 연결 정보는 OS 환경변수 > `.env` > TOML 순입니다.

```sh
python run_homevis.py
```

기본 실행은 **live·무기한**입니다. `Ctrl+C` 또는 `SIGTERM`으로 종료합니다.
`run_homevis.py` 하나가 센싱 수신, 기기 상태 조회, 중앙 판단·생활 자동화, outbox 전송,
낙상 진행 조회, 활성화된 음성 처리, 상태 기록을 모두 기존 통합 실행기로 연결합니다.
별도 시나리오 파일들을 하나씩 실행할 필요가 없습니다. 설정과 환경변수에서 비활성화한 기능은 실행하지 않습니다.
파일 실행 시 상대 경로는 프로젝트 폴더 기준입니다. 기존 `python -m src.integration`도 그대로 사용할 수 있습니다.
백엔드·센싱 생산자·MQTT 브로커를 이 파일에서 대신 시작하지는 않습니다.
MQTT와 HTTP는 별도 작업 스레드를 사용하고, 컨트롤러·SQLite는 주 실행 스레드에서만 접근합니다.
MQTT 연결이 끊기면 재연결·재구독하고, HTTP 오류는 다음 주기에 재시도합니다.
센싱 중단을 정상/외출/회복으로 바꾸지 않으며, 오래된 일반 기기 제어는 만료시킵니다.

```sh
python -m src.integration --check-config
python -m src.integration --mode mock --duration 15
python -m src.integration --mode mock --mock-scenario fall --duration 15
python -m src.integration --sensing-source backend
python -m src.integration --healthcheck
```

Mock 모드는 MQTT·실가전·LLM API를 호출하지 않습니다. 가짜 센싱과 백엔드로 실제 판단 엔진을 실행합니다.
`--duration`을 생략하면 Mock도 계속 실행됩니다. Mock WAV는 시험용 소리이며 실제 음성은 아닙니다.
`--healthcheck`는 프로세스 heartbeat 확인입니다. 센싱/백엔드 연결 상태는 별도로 상태 파일에서 확인합니다.
동일 데이터 폴더를 사용하는 두 번째 실행기는 파일 잠금으로 거부합니다. 폴더는 실행 계정이 쓸 수 있어야 합니다.

### 2026-10-27 연속 실행 재검증

아래 회귀 결과는 개발용 테스트 파일 삭제 전의 기록입니다. 현재 실행 확인은 `run_homevis.py`를 사용합니다.

- 수정 후 전체 회귀 검사: **841 passed, 11 skipped**(194.84초, Windows/Python 3.13.5). skip은 유료 API 직접 호출 2개와 별도 백엔드 checkout이 필요한 9개다. 실제 유료 API는 호출하지 않았다. `git diff --check`와 Python 구문 검사도 통과했다.
- 기본 설정의 mock 프로세스를 65초 동안 실행했다. 센싱 62건을 수신했고, 전등 ON·주방 화력 감소·안전 안내 등 요청 5건을 시뮬레이션 백엔드가 접수했다. 정상 종료 시 `running=false`와 SQLite 기록을 확인했다.
- 기본 `python`(이 환경의 Python 3.12.11)으로 `run_homevis.py --mode mock --mock-scenario fall --duration 12`도 실행했다. `fall_detected`와 `fall_user_announcement` 각 1건이 접수되었으며, 낙상 안내 기록 1건과 정상 종료를 확인했다.
- 실제 `run_homevis.py` 프로세스를 종료 시간 없이 띄워 로컬 HTTP 테스트 서버에 연결했다. 잘못된 센싱, 백엔드 503 장애, 복구, 반복 empty, 귀가, 두 번째 외출, 강제 종료·재시작을 거쳐도 루프와 중복 방지가 유지되는 것을 자동 테스트로 확인했다. 이 테스트는 실가전을 제어하지 않는다.
- 시뮬레이션 백엔드가 `away_all_off`에 불필요하게 `room`을 요구하던 오류를 수정했다. 실제 계약대로 `actions=[]`를 받고 시뮬레이션 대상 기기를 선택한다.
- 과도하게 큰 숫자/TTL과 지나치게 깊은 JSON이 처리 루프를 종료시키지 않도록 입력 오류로 처리한다. 다음 유효한 관측부터 기존 조건으로 복구하며 새로운 확인 대기는 없다.
- Windows에서 상태 파일을 읽는 동안 atomic 교체가 거부되는 문제를 재현·수정했다. 이 경우 이전 상태 파일을 보존하고 최대 0.5초 뒤 상태 기록만 다시 시도한다. 센싱·판단 루프는 계속되며, 영구적인 디스크/SQLite 쓰기 실패를 성공으로 처리하지 않는다.
- 현재 작업 환경의 설정으로 백엔드 기기·센싱 API를 읽기 전용 조회했으나 연결되지 않았고 MQTT TCP 포트도 연결되지 않았다. 따라서 실제 입력부터 실가전까지의 현장 연동 성공을 확인한 것은 아니다.
- 현재 `whole_home_presence_verified=false`, 음성 기능 OFF 설정을 유지한다. 전체 부재 계약이 확인되기 전에는 외출 OFF가 보류된다. 행동 정보가 없으면 위치만으로 낙상·기상·취침을 만들어내지 않는다.
- Docker/ARM64 보드 실행 및 수일 이상의 장시간 실기기 시험은 이 환경에서 수행하지 못했다.

## 테스트 파일 정리 후 재검증 (2026-10-27)

- 프로젝트 밖 임시 복사본에서 현재 소스와 Git의 기존 회귀 검사를 함께 실행했다. 현재 설정 파일 경로·오류 메시지 비노출·즉시 외출 정책에 맞춰 임시 검사 준비 코드를 조정했다.
- 결과는 **774 passed, 2 skipped, 13 deselected**다. skip 2건은 실제 유료 EXAONE/GPT 호출이다. 제외한 13건은 제거된 수동 실행 파일·외출 확인 대기 조건을 대상으로 한 옛 검사이며, 현재 요구사항 검사 49건을 별도로 포함했다. 백엔드 소스 모델 대조와 로컬 MQTT/HTTP 소켓 검사도 통과했다.
- 유효한 첫 `empty`의 즉시 요청, MQTT/백엔드 포맷별 검증, 반복·과거·unknown·오류 입력, 응답 유실 재시도, 재시작 중복 방지, 귀가 후 인덕션 복구 잠금, EXAONE 실패 중 외출 판단을 확인했다. 운영의 `whole_home_presence_verified=false`는 유지했다.
- Gemini Vertex 설정·모델 전달·제한된 재시도·LLM 복구·상태 조회·설정 경계값에 대한 추가 검사 14건도 통과했다. 외부 유료 API는 호출하지 않았다.
- `run_homevis.py`를 종료 시간 없이 로컬 HTTP 서버에 연결해 잘못된 센싱·HTTP 503·응답 유실·중복 실행 차단·강제 종료/재시작·귀가/두 번째 외출을 검증했다. 일반 Mock 65초에서는 요청 5건, 낙상 Mock 15초에서는 요청 2건을 접수하고 정상 종료했다.
- 실행 소스 86개의 Python 3.11 문법, TOML, 선택적 Qwen을 제외한 모듈 로딩, 런타임 SDK 로딩, `--check-config`, `git diff --check`를 확인했다. Qwen 실제 추론은 별도 torch/transformers와 모델이 없어 수행하지 않았다.
- 현재 설정의 백엔드·MQTT TCP 연결과 백엔드 기기 상태 GET은 실패했다. 실가전·실제 음성 출력·유료 API·Docker/ARM64 실행·수일 연속 운영은 이번 검사로 확인되지 않았다.
- 신뢰도 하한 0을 보조 함수에 직접 넣었을 때의 결과도 확인했지만, 실제 설정 로더가 0을 거부하므로 운영 경로의 오류가 아니었다. 이번 검증에서 실행 코드 변경은 없으며, 임시 검사 파일·의존성·출력은 정리했다.

### 검증 후 수정

Qwen 어댑터의 torch/transformers import를 초기화 시점으로 옮겼다. 선택하지 않은 Qwen 모듈을 읽을 때는 해당 패키지가 필요하지 않으며, 선택 시 로컬 모델 폴더와 의존성을 확인한다. 선택 의존성 설치는 `python -m pip install -r requirements-qwen.txt`를 사용한다. 기존 생성 설정과 로컬 파일 전용 로딩은 유지한다.

의존성 없는 import, 누락된 모델·패키지 처리, 실패 시 fallback, 모의 모델의 로딩·생성 인자 등 8개 검사와 전체 소스 문법·설정 검사, Mock 3초 기동·정상 종료를 확인했다. 테스트 파일이나 임시 출력은 남기지 않았다. 실제 Qwen 추론은 로컬 모델과 런타임을 준비한 환경에서 별도로 확인해야 한다.

실제 백엔드·MQTT는 설정된 localhost 포트에 실행 중인 서비스가 없으며, 별도 장비 주소도 프로젝트에 지정되지 않았다. 이 연결 문제는 서비스 기동 또는 실제 주소 설정이 필요하다. Docker/ARM64 실기기 검증도 해당 실행 환경이 준비되어야 한다.

## 확인한 팀 계약

2026-10-24에 팀 저장소의 다음 버전을 읽고 구현했습니다.

- [백엔드 AI 연동 v0.5](https://github.com/2026ESWC-SSCC/HomeVIS-Backend/blob/3a23128d5dedb4eed279472b2fc1aac7ded07fe6/docs/AI-INTEGRATION.md)
- [백엔드 센싱 MQTT 계약](https://github.com/2026ESWC-SSCC/HomeVIS-Backend/blob/3a23128d5dedb4eed279472b2fc1aac7ded07fe6/docs/EDGE-MQTT.md)
- [실제 Wi-Fi 토픽 정의](https://github.com/2026ESWC-SSCC/HomeVIS-AI_Wifi/blob/f73c0ff0d72bcdf1e04769270e7fb401103bde90/src/mqtt_util.py)

| 흐름 | 실제 연결 |
| --- | --- |
| 기본 센싱 수신 | GET `/api/v1/sensing/results?since=...&limit=5000`, 기본 1초 주기 |
| 직접 센싱 선택 | `--sensing-source mqtt`: MQTT `home/edge/result` (재실 + 행동) |
| 기기 상태 | GET `/api/v1/ai/device-states`, 기본 1초 주기 |
| 모든 기기 제어·안내 | POST `/api/v1/ai/decisions` |
| 진행 중 낙상 | GET `/api/v1/fall-incidents/{fallIncidentId}` |

2026-10-27 제공된 백엔드 v0.10 계약에서는 Wi-Fi 재실·행동 최종 결과가 `home/edge/result`로 전달됩니다.
기본 실행은 백엔드 HTTP 조회이며, 원시 특성이나 `home/edge/combined`는 판정 엔진의 입력이 아닙니다.
백엔드 HTTP와 직접 MQTT는 같은 최종 결과 어댑터를 사용하며, 두 소스를 섞어 판단하지 않습니다.
기존 `.env`의 `HOMEVIS_SENSING_SOURCE=mqtt`는 설정을 덮어쓰므로 `backend`로 변경하거나 CLI로 명시하세요.
백엔드 `docker compose --profile sim up -d`의 fusion simulator를 쓰면 이 backend 모드를 선택합니다.
직접 MQTT 기본 토픽도 `home/edge/result`입니다. 기존 환경변수에 이전 토픽이 남아 있으면 수정하세요.
`observedAt`, `validSec`, 각 신뢰도와 `presenceReason/activityReason`을 보존·검사합니다.
학습 로그로 확인한 `activity=none/fall/lie_down/get_up`을 지원합니다. `none`은 외출이나 정지가 아니며,
`get_up`은 조건 충족 시 아침 방 전등 이벤트로 사용합니다. v0.10 통합 결과와 판단 불가 처리는
[행동 연동 안내](wifi_behavior.md)를 확인하세요. AI에서 CSI 행동 모델을 학습/실행하지 않습니다.

Wi-Fi 추론 서버가 노드 수집에 최대 2초를 기다리므로 실행기 정렬 여유는 기본 4초입니다.
기존 직접 `IntegrationConfig()` 호출과 테스트의 기본 2초는 유지합니다. 시각을 현재 시각으로 덮어쓰지 않습니다.
MQTT retained 메시지는 신규 관측으로 쓰지 않으며 다음 실제 발행부터 사용합니다.

## 판단과 전송

운영 기본값은 `automation_profile="location_level_v1"`입니다. 현재 팀 입력에서 실제로 제공되는
위치·시간·센싱 일관성·인덕션 화력 단계로 점수를 계산합니다. 없는 행동·전력(W) 값을 채워 넣지 않습니다.
기존 `legacy` 프로필과 임계값, FeedbackManager/WeightManager 구현은 유지합니다.

| 동작 | 기본 조건 |
| --- | --- |
| 전등 켜기 | 해당 구역 재실 5초 이상 + confidence ≥ 0.72 |
| 전등 끄기 | 다른 유효 구역에서 30초 이상 부재 확인 + confidence ≥ 0.78 |
| 인덕션 감소 | 켜진 인덕션의 level 2~9 확인, 주방 이탈 40초 이상 + confidence ≥ 0.82 |
| 인덕션 복구 | 새 주방 복귀 5초 이상 확인 + confidence ≥ 0.80 + 본 시스템의 감소 기록·관측 확인 |

시간은 측정 시각 기준이며 실제 전달에는 기본 4초 정렬 버퍼와 통신 지연이 더해집니다.
낮은 신뢰도·unknown·empty·센싱 단절은 부재로 간주하지 않습니다. 인덕션은 자동으로 켜지 않습니다.
`multi_room_lights=true`이면 기기 조회에 등록된 room/kitchen/toilet 전등들을 각각 평가하고 정확한
`deviceId`로 전달합니다. 등록되지 않은 구역의 전등을 가정하지 않습니다. 같은 구역의 여러 전등도 지원합니다.
`false`이면 기존 `device_ids.light` 한 대만 사용합니다. 취침 소등을 일반 재실 켜기가 즉시 취소하지 않습니다.

위 시간은 `config/decision_policy.toml`의 `[automation]` 아래 `automation_absence_seconds`, `automation_return_seconds`,
`light_on_seconds`, `light_off_seconds`로 변경합니다. 기존 입력 전체를 사용하는 평가로 되돌리려면
`automation_profile="legacy"`를 선택합니다. 새로운 프로필의 학습 파일은
`user_weights.location_level_v1.json`, `feedback.location_level_v1.jsonl`로 분리되어 기존 학습값을 덮어쓰지 않습니다.
통합 정책에서 가중치 또는 가중치 상·하한을 바꾸면 가중치 파일에 `.policy-<식별자>`가 추가됩니다.
이전 학습값은 보존하며, 같은 구성의 재시작은 해당 구성의 학습값을 재사용합니다.
이전 프로필 판단에 대한 피드백은 그 프로필로 처리하며 서로 다른 feature 가중치를 섞지 않습니다.

| 내부 출력 | 백엔드 전송 |
| --- | --- |
| 전등 `turn_on/turn_off` | `light: on/off`, 정확한 `deviceId` 포함 |
| 취침 소등 | `bedtime_light_off`, `light: off` |
| 인덕션 `reduce_power` | `stove_absence`, `set_level`로 현재보다 기본 1단계 낮춤. 이미 1단계면 보내지 않음 |
| 인덕션 `restore_power` | `stove_absence`, `restore_power` |
| 기상 출수 | `water_dispense`, 기존 판단 수량(기본 120mL), `weatherBriefing=true` |
| 기상 방 전등 | 내부 `morning_light_on` → 기존 백엔드 `light_auto_on`, `light: on` |
| 낙상 | `fall_detected`, `actions=[]`; 긴급 차단·깜빡임은 백엔드가 수행 |
| 위험·낙상 음성 안내 | 제어 없는 별도 판단의 `announcement`; 대시보드가 표시·음성 재생 |

`reduce_power`의 단계 폭은 `stove_reduce_steps`로 설정합니다. 전원 차단으로 바꾸지 않습니다.
복구는 AI가 보낸 감소 요청의 접수 기록과 이후 `homevis`·낮아진 level 관측이 모두 있어야 허용합니다.
사용자 조작, OFF, 미해결 낙상은 복구하지 않습니다. 운영 프로필은 온도 미측정·200℃ 이상·온도 급상승에도
복구하지 않습니다. 원래 화력 저장·기기 실행은 백엔드 책임입니다.
백엔드가 OFF 후 복구도 지원하지만 기존 AI의 OFF 복구 금지 조건은 유지합니다.

백엔드 실제 모델은 `confidence: null`을 허용하지 않습니다. 기존 가중합 점수가 있는 출력은 그 값을 유지합니다.
별도 점수가 없는 출수·취침·낙상 규칙은 해당 관측의 위치/행동 신뢰도 중 낮은 값을 전송하고
`source.confidence_basis`에 근거를 기록합니다. 필요한 측정 신뢰도가 없으면 임의 점수를 만들지 않고 보류합니다.
기존 직접 호출용 `null` 정책과 Mock 예시는 호환용으로 남아 있으며 live 실행기는 `observed` 정책을 씁니다.

정수기의 `current_state.status=idle`은 **기기의** 출수 대기 상태입니다. Wi-Fi 사용자 행동과 구분합니다.
online·기기/구역·freshness도 확인합니다. 온도는 백엔드 스키마에서 섭씨로 확인됐습니다.
level(1~9)을 와트로 추정하지 않습니다. 운영 프로필의 감소 점수는
`위치×0.30 + 이탈시간/40(최대1)×0.30 + level/9×0.10 + 일관성×0.20 + 피드백×0.10`입니다.
위치·일관성 0.95, 40초 이탈, level 5, 초기 피드백 0.5이면 약 0.881로 감소 기준을 통과합니다.
W는 검증된 `level_to_watts` 표나 `watts_field` 설정이 없으면 미측정으로 남지만, 운영 자동 제어의
필수 입력은 아닙니다. W에 의존하는 기존 위험 판단 항목은 W를 제공해야 평가할 수 있습니다.

일반 요청에는 `expiresAt`을 보내고 `status=expired` 응답은 재시도하지 않습니다.
`202/sent`는 접수·전송이지 가전의 실제 동작 완료 ACK가 아닙니다.
부분 실패는 기록하며 이미 접수된 판단을 새 ID로 재실행하지 않습니다.

## 낙상과 TTS

최초 낙상 사건 1건을 디스크에 저장한 뒤 전송하고 `decisionId`와 `fallIncidentId`를 연결합니다.
재시작·응답 유실 때도 동일 ID/본문을 사용합니다. 일반 기기 상태 조회가 실패해도 이미 감지한 낙상은
전송하며, 일시적인 오류는 최대 60초 간격으로 재시도합니다. 인증·요청 오류는 실패로 기록합니다.

백엔드가 즉시 차단/깜빡임/사용자 SMS → 기본 30초 뒤 보호자 → 추가 60초 뒤 신고 상태를 관리합니다.
대기시간은 백엔드 `/api/v1/policies/fall-safety` 설정입니다. AI가 보호자 SMS·자동 신고 타이머를 중복 실행하지 않습니다.
AI의 5/10/30초는 기존 움직임 관측의 위험 단계이며 백엔드의 응답 대기시간과 다릅니다.
조회 결과 `resolved`이면 내부 사건을 종료하고, `reported/auto_reported`는 안전 확인으로 취급하지 않습니다.
종료 후 잔여 낙상 신호는 재시작하더라도 새 사건으로 보내지 않고, 유효한 회복 관측 후 다시 감지합니다.

1차 문장/WAV는 기존 AlertService를 별도 작업 스레드에서 생성합니다. 실패·지연이 판단/제어를 막지 않습니다.
완성된 문장은 별도 `announcement`로 백엔드에 보내 대시보드가 읽게 합니다. 로컬 WAV는 자동 재생하지 않습니다.
`LLM_PROVIDER=none/qwen/exaone`을 그대로 지원합니다. EXAONE 사용 시 `FRIENDLI_API_KEY`를 설정하세요.
EXAONE 실패 시 기존 문구 fallback을 사용하며 Qwen을 자동 로딩하지 않습니다.

확인한 백엔드 `fall_service.auto_report()`의 실제 119/응급기관 연결은 **미구현**입니다.
현재는 `auto_reported` 상태·대시보드 이벤트 기록까지이며 AI 실행기가 이를 실제 신고 완료로 표현하지 않습니다.

## 행동 데이터와 운영 상태

화장실 눕기 후보와 기상 방 전등의 추가 정책, 정상 설명/오류 분리, Mock 전용 이벤트 계약은
[Wi-Fi 행동 연동 안내](wifi_behavior.md)를 참고하세요. 후보만으로는 낙상 사건을 만들지 않습니다.

v0.10에서는 위치와 행동을 한 결과에서 받습니다. `present=true`이고 행동만 `unknown`이면
위치 기반 판단은 유지하고 행동이 필요한 판단은 보류합니다. `missing_inputs`를 확인하세요.
`presenceReason`과 `activityReason`은 각각 해당 판단의 진단이며 서로의 유효성을 덮어쓰지 않습니다.
통합 결과에 행동이 없거나 판단 불가이면 이전 별도 행동 토픽의 결과로 대체하지 않습니다.
낙상 확인에는 `motion_state` 및 `fall_detected` 또는 관측된 행동 전이가 필요합니다.
`lying`만으로 움직임 없음/낙상을 추정하지 않습니다.

v0.10 통합 결과에는 별도 행동 토픽 설정이 필요 없습니다. 기존 직접 위치 입력을 사용하는 경우에만
`HOMEVIS_BEHAVIOR_TOPIC`으로 별도 관측을 결합할 수 있습니다. 다음은 이 실행기 어댑터의
입력 예시이며 현재 Wi-Fi 서버가 이미 발행하는 형식이라는 뜻은 아닙니다.

```json
{"time":"2026-10-24T07:00:00+09:00","valid_until":"2026-10-24T07:00:05+09:00",
 "location":"toilet","confidence":0.94,"activity":"lying","motion_state":"still","fall_detected":true}
```

위치와 동일 공간, 시각차 기본 1초 이내, 만료 전인 행동만 결합합니다. 위치 JSON 안의 `behavior` 객체로
같은 형식을 함께 보낼 수도 있습니다. 누락·미래·만료·깨진 입력과 순서 역전은 검사합니다.

`output/integration/live/status.json`에 heartbeat, 연결 상태, 현재 위험·낙상 상태,
누락 입력, 전송 상태 개수, 진행 중 사건을 기록합니다. `outbox.sqlite3`에는 원본·요청·응답·재시도 이력이 있습니다.
고빈도 관측 감사 로그는 기본 7일 후 정리하며 판단 ID와 미해결 사건은 보존합니다.
운영 프로필의 판단·루틴 이력도 SQLite에 저장해 매 tick의 기록이 메모리에 누적되지 않게 합니다.
기존 `controller/decision_history.jsonl`은 최초 실행 때 읽어서 이전 판단의 피드백 조회를 유지하며 원본은 보존합니다.
직접 컨트롤러 호출용 JSONL 저장소와 피드백·가중치 처리 인터페이스는 그대로입니다.

## 실행 확인

```sh
python run_homevis.py --check-config
python run_homevis.py --mode mock --duration 15
python run_homevis.py --mode mock --mock-scenario fall --duration 15
```

개발용 자동 테스트와 별도 검증 스크립트는 삭제했습니다. Mock에 필요한 시뮬레이션 코드는 실행기의 일부로 유지합니다.
Mock 기동은 실제 백엔드·MQTT·가전 연결 검증을 대신하지 않습니다.
