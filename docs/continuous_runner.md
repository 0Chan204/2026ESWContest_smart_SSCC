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
MQTT TLS/CA는 `config/homevis.toml`의 `mqtt.tls/ca_file`에서 설정합니다.

```sh
python -m src.integration
```

기본 실행은 **live·무기한**입니다. `Ctrl+C` 또는 `SIGTERM`으로 종료합니다.
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

## 확인한 팀 계약

2026-10-24에 팀 저장소의 다음 버전을 읽고 구현했습니다.

- [백엔드 AI 연동 v0.5](https://github.com/2026ESEC-SSCC/HomeVIS-Backend/blob/3a23128d5dedb4eed279472b2fc1aac7ded07fe6/docs/AI-INTEGRATION.md)
- [백엔드 센싱 MQTT 계약](https://github.com/2026ESEC-SSCC/HomeVIS-Backend/blob/3a23128d5dedb4eed279472b2fc1aac7ded07fe6/docs/EDGE-MQTT.md)
- [실제 Wi-Fi 토픽 정의](https://github.com/2026ESEC-SSCC/HomeVIS-AI_Wifi/blob/f73c0ff0d72bcdf1e04769270e7fb401103bde90/src/mqtt_util.py)

| 흐름 | 실제 연결 |
| --- | --- |
| 기본 센싱 수신 | MQTT `wifi/occupancy/state`: `time/location/location_confidence/reason` |
| 백엔드 저장 센싱 선택 | GET `/api/v1/sensing/results?since=...&limit=5000` |
| 기기 상태 | GET `/api/v1/ai/device-states`, 기본 2초 주기 |
| 모든 기기 제어·안내 | POST `/api/v1/ai/decisions` |
| 진행 중 낙상 | GET `/api/v1/fall-incidents/{fallIncidentId}` |

Wi-Fi 저장소와 백엔드의 센싱 토픽은 현재 서로 다릅니다. 기본 실행은 실제 Wi-Fi 토픽을 직접 받습니다.
`--sensing-source backend`는 `home/edge/result`로 저장된 결과를 읽습니다. 두 소스를 섞어 판단하지 않습니다.
백엔드 `docker compose --profile sim up -d`의 fusion simulator를 쓰면 이 backend 모드를 선택합니다.
직접 MQTT로 백엔드 형식의 결과를 받으려면 `HOMEVIS_LOCATION_TOPIC=home/edge/result`를 설정합니다.
그 형식의 `observedAt`, `validSec`, `activityConfidence`도 보존·검사합니다.

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

위 시간은 `config/homevis.toml`의 `automation_absence_seconds`, `automation_return_seconds`,
`light_on_seconds`, `light_off_seconds`로 변경합니다. 기존 입력 전체를 사용하는 평가로 되돌리려면
`automation_profile="legacy"`를 선택합니다. 새로운 프로필의 학습 파일은
`user_weights.location_level_v1.json`, `feedback.location_level_v1.jsonl`로 분리되어 기존 학습값을 덮어쓰지 않습니다.
이전 프로필 판단에 대한 피드백은 그 프로필로 처리하며 서로 다른 feature 가중치를 섞지 않습니다.

| 내부 출력 | 백엔드 전송 |
| --- | --- |
| 전등 `turn_on/turn_off` | `light: on/off`, 정확한 `deviceId` 포함 |
| 취침 소등 | `bedtime_light_off`, `light: off` |
| 인덕션 `reduce_power` | `stove_absence`, `set_level`로 현재보다 기본 1단계 낮춤. 이미 1단계면 보내지 않음 |
| 인덕션 `restore_power` | `stove_absence`, `restore_power` |
| 기상 출수 | `water_dispense`, 기존 판단 수량(기본 120mL), `weatherBriefing=true` |
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

현재 Wi-Fi 저장소는 위치만 발행합니다. 이 상태에서는 위치 기반 판단은 실행되지만
기상 출수·취침·낙상에 필요한 실제 행동/움직임을 만들어내지 않습니다. `missing_inputs`를 확인하세요.
백엔드 형식의 `activity/activityConfidence/validSec`나 별도 행동 토픽을 받아 연결할 준비는 되어 있습니다.
낙상 확인에는 `motion_state` 및 `fall_detected` 또는 관측된 행동 전이가 필요합니다.
`lying`만으로 움직임 없음/낙상을 추정하지 않습니다.

별도 행동 생산자가 정해지면 `HOMEVIS_BEHAVIOR_TOPIC`을 설정할 수 있습니다. 다음은 이 실행기 어댑터의
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

## 검증

```sh
python -m pytest -q
python -m pytest -q tests/test_continuous_runner.py tests/test_runner_network.py
python -m pytest -q tests/test_location_level_automation.py
```

네트워크 테스트는 로컬 시험 MQTT 브로커/HTTP 서버만 사용합니다. paho가 없으면 MQTT 실소켓 테스트만 skip합니다.
실제 팀 backend checkout이 있으면 `HOMEVIS_BACKEND_CHECKOUT`을 그 경로로 설정해
요청·응답을 백엔드 Pydantic 모델로 검증할 수 있습니다. 원격 서버나 실가전 동작 시험은 자동 실행하지 않습니다.
