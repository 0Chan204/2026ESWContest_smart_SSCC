# 공기청정기·외출 전체 OFF·음성 v0.7 통합

2026-10-26 로컬 변경을 보존하면서 기존 연속 실행기에 추가한 기능입니다.
새 실행 프로그램, 기기 MQTT 명령, 공기질 PM 임계값, 새 confidence 학습 알고리즘은 만들지 않았습니다.

## 확인한 소스와 현재 가능한 범위

- [백엔드 AI 계약](https://github.com/2026ESEC-SSCC/HomeVIS-Backend/blob/fb22929879d255f6c1788f465df48c941b9338b7/docs/AI-INTEGRATION.md), [음성 계약](https://github.com/2026ESEC-SSCC/HomeVIS-Backend/blob/fb22929879d255f6c1788f465df48c941b9338b7/docs/VOICE.md): develop `fb22929879d255f6c1788f465df48c941b9338b7`, v0.7.
- 같은 커밋의 `app/schemas.py`, `app/ai_service.py`, 음성 처리 코드도 확인했습니다. 문서 예시만으로 연결 가능하다고 가정하지 않았습니다.
- [임베디드 저장소](https://github.com/2026ESEC-SSCC/HomeVIS-EM.devices/tree/d73f7f71fc5d0ba355622c7cdf432954145ee156): `d73f7f7`에 인덕션·전등·정수기 Dummy_Data는 있으나 공청기 펌웨어는 확인하지 못했습니다.
- Wi-Fi 행동 라벨·위치 연동은 기존 [Wi-Fi 행동 문서](wifi_behavior.md)를 유지합니다. 행동 `none`은 집 전체 부재가 아닙니다.

| 기능 | 구현 상태 / 운영 제한 |
| --- | --- |
| 조리 중 공청기 ON | 최신 인덕션 ON + 유효한 공청기 OFF이면 기존 API로 1회 요청 |
| 조리 종료 후 공청기 OFF | 상태 전이·30초 양호·정확한 명령 출처가 모두 필요. 현재 백엔드 GET은 출처를 제외하므로 운영에서는 보류 |
| 외출 전체 OFF | 600초 유효한 집 전체 부재 규칙 구현. 생산자의 전체 구역 부재 의미 확인 전에는 설정상 비활성 |
| 음성 공청기 제어 | ON/OFF/auto/manual, 사용자 확인 요청 |
| 음성 인덕션 ON | 명시적 단계 1~9 + 안전 검증 + 백엔드 확인 필요 |
| 임베디드와 우선순위 공유 | 계약 없음. AI 내부 우선순위·중복 방지만 구현, 기기 상태 유지 보장은 불가 |

## 기존 구조와 연결 지점

```text
백엔드 센싱 GET (기본 1초) ─┐
백엔드 기기 상태 GET (2초) ─┼→ 기존 IntegrationRuntime
                         │   ├─ 기존 중앙 판단·confidence·시나리오
                         │   └─ HomeAutomation: 조리 연동 / 전체 부재 규칙
                         └→ 기존 DecisionMapper → SQLite Outbox
                                                → POST /api/v1/ai/decisions
백엔드 STT → home/voice/request → 기존 음성 분류·검증 ─────────┘
```

센싱은 기존 `/api/v1/sensing/results` 이력 폴링을 재사용해 연속 측정을 처리합니다.
음성 재실 질문은 기존 `/api/v1/sensing/results/latest`를 사용합니다. 새로운 API나 MQTT 토픽을 만들지 않았습니다.
실제 기기 OFF 대상 선택·MQTT 명령·STT·음성 응답 TTS는 백엔드 담당입니다.
기존 위험 알림용 로컬 AlertService/TTS는 변경하지 않았습니다.

이번 추가로 CentralController, RealtimeDecisionEngine, ConfidenceEngine, WeightManager/FeedbackManager의
기존 판단·학습 알고리즘은 변경하지 않았습니다. 기존 로컬 Wi-Fi/음성 변경도 덮어쓰지 않았습니다.
공청기 연동은 LLM 없이 규칙으로 실행하며 음성 분류는 기존 Qwen/EXAONE/GPT 공유 client를 재사용합니다.

## 공청기 상태와 조리 연동

대상은 `air_purifier`, 기본 ID `air-01`, 구역 `room`입니다.
기존 기기 GET의 `online`, `is_on`, `updatedAt`, `control_state`, `current_state`를 사용합니다.
`current_state`에서 `power`, `mode`, `reportedAt`, `airQuality.level`과 선택적 PM 값을 검증합니다.
PM2.5/PM10은 유효한 비음수 측정인지 확인하고 표시할 뿐, good/normal/bad로 다시 분류하지 않습니다.
추가 원문 값(예: CO2)은 보존하되 제어 임계값으로 쓰지 않습니다.

- ON: 최신 kitchen 인덕션이 실제 ON, 공청기가 실제 OFF, online·시각·공기질 필드 유효.
- 이미 ON이면 요청하지 않습니다. 알려진 사용자 수동 의도, 미해결 낙상·위험, 확정 외출이 우선합니다.
- OFF: 인덕션 ON→OFF 전이를 최근 관측으로 확인하고 공청기가 ON이며, good/normal 관측이 기본 30초 이어져야 합니다.
- 실제 펌웨어의 `is_on=false, state=cooling`도 가열 종료로 인정합니다. 냉각 중에도 출처·공기질 유지 검증을 계속하되, `overheated`, 미확인 상태, is_on과 state의 모순은 종료 근거로 사용하지 않습니다.
- good/normal을 OFF 검토 가능한 상태로 취급하는 것은 **AI 조리 종료 정책의 가정**입니다. 임베디드의 실제 PM 임계값은 바꾸지 않습니다.
- OFF에는 `control_state=homevis`만으로 부족합니다. 실제 상태의 `lastControl.publisher=api`, `commandId`가 해당 조리 에피소드의 ON 요청에 대해 백엔드가 반환한 `sent` 명령 ID와 정확히 일치해야 합니다.
- 수동 ON, 임베디드 `publisher=system`, 다른 명령 ID, 출처 누락, bad/unknown, offline/stale이면 OFF를 보류합니다.
- 잘못된 중간 폴링·통신 실패·관측 공백은 양호 유지 시간을 초기화합니다. 같은 데이터의 반복 GET과 프로세스 중단 시간으로 30초를 채우지 않습니다.
- 전송 직전에 상태·출처·구역·대상을 재검증합니다. ON/OFF 모두 기존 `cooking_air_clean` 계약을 사용합니다.

현재 백엔드 `get_device_info()`는 **AI GET의 current_state에서 lastControl을 제거**합니다.
따라서 실제 GET만 받는 현재 운영 환경에서는 OFF 소유권을 증명할 수 없어 자동 OFF를 보내지 않습니다.
백엔드가 이미 가진 원본 상태를 AI도 반환받을 수 있는 계약이 필요하며, 임의의 조회 API는 추가하지 않았습니다.
외부 수동 OFF도 출처가 누락되면 정확히 식별할 수 없다는 제한이 있습니다.
AI가 접수한 공청기 음성 제어는 별도로 기록해 조리 연동보다 우선 보호합니다.
확인 대기·취소된 음성 의도도 해당 조리 에피소드에서는 보수적으로 보호하며, 다음 조리 에피소드에서 다시 평가합니다.

## 외출 전체 OFF와 재점화 방지

`whole_home_presence_verified=false`가 기본입니다. 설정을 true로 바꾸는 것은
**생산자·백엔드가 해당 결과를 전체 집의 유효한 부재라고 보증한다는 운영 확인**이지 센서 유효성을 만들어내는 기능이 아닙니다.

확인 후에도 아래 조건을 모두 만족해야 합니다.

1. 기존 백엔드 결과의 `present=false`, 명시적 `room=null`, 측정 시각·양수 정수 `validSec`, 신뢰도 기본 0.8 이상.
2. 센싱 결과가 오래되거나 미래 시각이 아니고 오류 reason·mock 표시가 없어야 합니다.
3. 새 관측들이 유효기간 안에서 연속으로 이어져야 합니다. 센싱 단절·불확실·단일 구역 부재·unknown/empty는 누적 시간을 끊습니다.
4. 측정 시각 기준 600초 이상 유지되어야 합니다. 단일 결과를 10분 동안 반복 조회해도 충족하지 않습니다.

HTTP 입력의 잘못된 형식·미래 시각·요청 실패·큐 초과는 내부 `SensingFault`로 판단기에 전달합니다.
이는 센싱 관측이나 새 MQTT/API 필드가 아닙니다. 조인 버퍼를 비우고 외출·행동 근거를 중단하며,
오류 발생 이전의 일반 자동화 근거가 지연 도착하거나 이벤트 큐에서 재생되어 유효성을 되살리지 못하게 차단합니다.
새로운 측정 시각의 유효한 결과부터 다시 평가합니다. 활성 낙상 사건을 오류로 종료하지는 않으며,
오류 전에 이미 수신·검증한 명시적 낙상 보고는 버퍼에 있더라도 기존 안전 대응 경로로 보존합니다.

요청은 `scenario=away_all_off`, `actions=[]`이며 room 없이 전송합니다.
백엔드가 켜진 stove/light/fan/air_purifier를 OFF하고 water_purifier를 제외합니다.
이 시나리오에 한해 응답의 백엔드 생성 OFF actions를 허용합니다. 물 제어·ON·restore 응답은 거부합니다.
다른 시나리오의 요청/응답 일치·필수 필드 검증은 그대로 유지합니다.

외출 확정 요청 전부터 SQLite에 복구 차단을 저장하고 이전 화력 감소 근거를 제거합니다.
유효한 귀가는 외출 에피소드를 끝내지만 복구 차단은 해제하지 않습니다.
불확실한 센싱도 이미 확정된 외출을 귀가로 바꾸지 않습니다.
따라서 기존 kitchen_return_restore가 단순 귀가만으로 OFF된 인덕션을 재점화하지 않습니다.

이후 사용자가 새로 조리를 시작한 실제 상태와 새 HomeVIS 화력 감소 이력이 확인되면
그 **새 조리 구간**에서 기존 감소/복구 정책을 다시 사용할 수 있습니다.
외출 전 화력에 대한 명시적 음성 restore도 출처·실제 상태를 증명하지 못하면 보류합니다.
“인덕션 3단으로 켜줘”는 귀가 후 최신 OFF 상태·주방 재실·온도 등 안전 검증과 백엔드 사용자 확인을 통과해야 합니다.

## 제어 우선순위와 A/B 시험의 의미

AI 내부 적용 순서는 안전·외출 전체 OFF → 확인 가능한 사용자 의도 → 임베디드 자동 ON 보호 → AI 조리 연동입니다.
그러나 **이 순서를 기기에 전달하고 유지시키는 계약은 없습니다**.
현재 기기 command 스키마에는 priority/hold/away lock 같은 필드가 없으며 새 필드를 전송하지 않았습니다.

| 상황 | 오프라인 시험 및 AI 처리 | 아직 보장할 수 없는 것 |
| --- | --- | --- |
| A: 인덕션 ON + good → AI ON 뒤 임베디드 OFF | 반대 상태를 주입해 재현. 같은 에피소드 ON 반복 없음, 유지 계약 부족 진단 기록 | 조리 중 실제 공청기가 계속 ON 유지됨 |
| B: 전체 외출 + bad → 백엔드 OFF 뒤 임베디드 ON | 반대 상태를 주입해 재현. 새로운 조리 ON/반복 전체 OFF 없음, 우선순위 계약 부족 진단 기록 | 임베디드가 공청기를 다시 켜지 않음 |

이는 충돌 해결 완료 테스트가 아니라 **미해결 충돌을 숨기지 않고 반복 명령 싸움을 피하는 테스트**입니다.
임베디드 펌웨어가 없는 상태에서 실기기의 A/B 동작을 검증했다고 주장하지 않습니다.
여러 제어 요구가 동시에 활성인 경우 마지막 명령 하나만으로 모든 우선순위를 보장할 수도 없습니다.

## confidence·이력·중복 처리

기존 중앙 confidence 가중합·학습값·feature 정의는 바꾸지 않습니다. 새 규칙의 점수는 구분해 저장합니다.

- 조리 연동: `1 - max(인덕션 updatedAt 나이, 공청기 updatedAt 나이, 공기질 reportedAt 나이) / device_max_age`.
  모든 관측이 최신·유효한 경우에만 계산하는 **최신성 휴리스틱**이며 정확도 확률이나 학습된 confidence가 아닙니다.
  백엔드 예시의 0.9를 고정 사용하지 않으며 `confidence_basis=telemetry_freshness_not_probability`로 기록합니다.
- 전체 외출: 연속 부재 구간에서 실제 받은 신뢰도의 최솟값, `minimum_absence_confidence`.
- 기존 `rule_confidence_policy=block`이면 신규 규칙도 전송하지 않습니다.

에피소드 ID로 안정적인 decisionId를 만들고 기존 SQLite Outbox와 DecisionHistory에
관측 원문·규칙 조건·출처 확인 여부·요청·응답·설정 스냅샷을 저장합니다.
HTTP 재시도는 같은 ID/본문을 사용하고, 프로세스 재시작으로 새 ON/OFF/외출 요청을 만들지 않습니다.
미확정 외출 후보와 공기질 유지 시간은 재시작 후 새 관측부터 계산합니다.
이미 확정된 외출은 실제 재실이 확인되기 전까지 유지합니다.

거절·부분 실패·만료·임베디드의 반대 동작을 새 decisionId로 자동 재실행하지 않습니다.
같은 에피소드의 요청이 만료되거나 실패하면 운영자가 이력을 확인해야 합니다.
백엔드 `executed`와 개별 `sent`는 **명령 송신 결과**이지 실제 가전의 최종 ACK가 아닙니다.
그 후 GET 관측을 따로 확인하며, 새 조회가 안 오면 적용 성공으로 추정하지 않습니다.

“왜 공청기가 켜졌어?”는 실제 출처와 일치하는 이력을 사용합니다. 출처가 빠졌으면 과거 AI 요청과 현재 원인을 구분해 설명합니다.
“왜 가전을 다 껐어?”는 유일하게 식별되는 외출 이력으로 설명합니다. 후보가 여러 개면 임의로 최신 기록을 고르지 않습니다.
이런 질문과 공기질 조회는 피드백 학습으로 처리하지 않습니다.
기존 사용자 지시 저장·proposed 상태·명시적 평가 경로는 유지하며 새 장기 정책을 자동 활성화하지 않습니다.

## 설정과 실행

### 온도 안전 계약의 보수적 차단

임베디드 develop `1f0e262`는 센서 고장 시 마지막 온도, 최초 측정 전에는 25℃를 전송하고,
백엔드 AI GET에는 온도 센서 유효성·측정 시각이 없습니다. 최신 `updatedAt`만으로 온도가 최신이라고 볼 수 없습니다.
이에 `[backend].stove_temperature_validity_verified=false`를 기본으로 추가했습니다.

- live: 인덕션 ON·화력 증가/동일 단계 재설정·restore 요청을 보류합니다. 자동 restore도 전송 직전에 차단합니다.
- 안전 방향 OFF와 이미 ON인 화구의 실제 단계 감소는 기존 검증을 유지합니다. 공청기 조리 규칙·다른 가전은 영향을 받지 않습니다.
- mock: 합성 온도를 사용하는 기존 테스트·시뮬레이션을 유지합니다.
- 이 설정은 온도 단위 확인(`temperature_is_celsius`)과 별개입니다. 기능을 켜기 위해 임의로 true로 바꾸지 마세요.
  팀이 잘못되거나 오래된 온도를 유효한 숫자로 제공하지 않도록 수정·검증한 뒤에만 운영 확인으로 활성화해야 합니다.
  이 플래그 자체가 각 관측의 유효성을 증명하지는 않습니다.

### Wi-Fi→백엔드의 남은 연결 작업

현재 Wi-Fi main은 `wifi/occupancy/state`의 `time/location/location_confidence`를 발행하고,
백엔드는 `home/edge/result`의 `observedAt/room/confidence`와 유효기간 등을 받습니다.
현재 Wi-Fi 메시지를 실제 백엔드 스키마에 넣으면 `observedAt` 누락으로 거부됩니다.
토픽 이름만 바꿔서는 해결되지 않습니다. 생산자/백엔드에서 양쪽 계약에 맞춰 변환하고
validSec·전체 부재·unknown·오프라인 의미를 합의해야 합니다.
AI의 기본 HTTP 수신 구조는 유지하고, 다른 팀 저장소나 기기 MQTT 토픽을 임의로 변경하지 않았습니다.
잘못된 Wi-Fi 원형이 HTTP로 들어오면 `backend_sensing_contract_mismatch`로 진단하며 제어 근거로 사용하지 않습니다.

### 실행 방법

저장소 루트에서 기존 실행 명령 하나를 사용합니다. 새 규칙은 표준 라이브러리만 사용하며 신규 패키지가 없습니다.
백엔드·브로커·센싱 생산자는 별도로 실행 중이어야 합니다.

```powershell
python -m pip install -r requirements-runtime.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m src.integration --check-config
python -m src.integration
```

`.env`의 백엔드·브로커 주소와 인증을 보드에 맞게 설정합니다. 키·토큰은 Git에 올리지 않습니다.
OS 환경변수가 `.env`보다 우선합니다. 기존 `LLM_PROVIDER` 설정을 그대로 사용합니다.

```ini
HOMEVIS_SENSING_SOURCE=backend
HOMEVIS_AIR_PURIFIER_ENABLED=true
HOMEVIS_COOKING_AIR_CLEAN_ENABLED=true
HOMEVIS_AWAY_ALL_OFF_ENABLED=true
# 전체 집 부재의 의미/오프라인 구역 처리 확인 전에는 변경하지 말 것
HOMEVIS_WHOLE_HOME_PRESENCE_VERIFIED=false
# 음성 기능은 선택. 사용 시 기존 LLM provider/API 키 설정 필요
HOMEVIS_VOICE_ENABLED=false
```

`config/homevis.toml`의 `[home_automation]`:

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| air_purifier_enabled / cooking_air_clean_enabled | true / true | 상태 수용 / 조리 규칙 활성화 |
| air_purifier_off_on_good_or_normal | true | 출처가 확인된 경우에만 OFF 검토 |
| air_purifier_clean_hold_seconds | 30 | 양호한 새 관측의 연속 유지 시간 |
| away_all_off_enabled / whole_home_presence_verified | true / false | 규칙 준비 / 전체 집 부재 계약 확인 |
| away_confirm_seconds / away_min_confidence | 600 / 0.8 | 연속 부재 시간 / 최소 관측 신뢰도 |

기존 코드의 직접 `IntegrationConfig()` 생성은 호환성을 위해 신규 규칙이 기본 OFF입니다.
위 설정 파일을 사용하는 실행기에서만 해당 설정이 적용됩니다.
`output/integration/live/status.json`의 `home_automation`에 활성 여부, 계약 확인 여부,
외출 활성 상태, 복구 차단, 마지막 진단을 기록합니다. 전체 진단·판단 근거는 기존 Outbox audit에 남습니다.

## 변경 파일

| 경로 | 이번 추가 역할 |
| --- | --- |
| `src/integration/home_config.py`, `home_automation.py` | 신규 설정·규칙·에피소드·보수적인 출처 검증 |
| `config.py`, `settings.py`, `state_mapper.py` | 기존 설정·환경변수·상태 파싱 확장 |
| `decision_mapper.py`, `schemas.py` | cooking/away 전용 요청·응답 검증 |
| `runtime.py`, `host.py` | 기존 tick/수신/송신 전 검사 연결, 복구 차단, 상태 표시 |
| `src/interaction/contracts.py`, `intent.py`, `control.py`, `coordinator.py` | v0.7 음성 필드·명령·확인 정책 |
| `src/interaction/response.py`, `explanation.py` | 공기질 조회·출처/외출 이력 설명 |
| `config/homevis.toml`, `.env.example`, `README.md`, 문서 | 설정·실행법·미확정 계약 명시 |
| `tests/test_home_automation.py`, `test_voice_v07.py`, `test_home_backend_v07.py` | 신규 Mock·실제 스키마 오프라인 테스트 |
| `tests/test_voice_interaction.py` | 이전 인덕션 ON 무조건 금지 검증을 새 안전 조건 검증으로 조정 |

## 검증

```powershell
python -m pip install pytest
python -m pytest tests/test_home_automation.py tests/test_voice_v07.py -q
python -m pytest -q
python -m src.integration --env-file .env.example --mode mock --duration 5
```

실제 백엔드 소스에 대한 추가 **오프라인** 검증은 Pydantic 2와 위 커밋을 포함한 로컬 clone이 있을 때 실행합니다.

```powershell
$env:HOMEVIS_BACKEND_CHECKOUT = 'C:\path\to\HomeVIS-Backend'
python -m pytest tests/test_home_backend_v07.py -q
```

백엔드 checkout이 없으면 해당 선택 테스트만 skip하며 핵심 Mock 테스트는 실행 가능합니다.
실제 `get_device_info()` 함수와 요청 모델을 이용해 lastControl 누락과 자동 OFF 보류도 재현합니다.
EXAONE/GPT 실API 테스트는 기존 명시적 opt-in 방식을 유지합니다.
이번 작업에서는 실제 유료 API·브로커·실서버·가전 제어를 실행하지 않았습니다.

초기 v0.7 통합 테스트: **77 passed** (선택적 실제 백엔드 소스 검증 5건 포함).
초기 전체 회귀: **718 passed, 2 skipped** (126.94초).

검토 후 수정의 최종 전체 회귀: **738 passed, 2 skipped** (131.57초).
`tests/test_review_regressions.py`에 냉각 상태·오류 응답/미래 시각/통신 실패·버퍼 재사용 차단·
명시적 낙상 보존·live 온도 안전 차단 등 20건을 추가했습니다.
기존 malformed 기상 입력 테스트는 전송 시 차단하던 요청을 이제 생성 전 차단하도록 기대값을 강화했습니다.
건너뛴 2건은 EXAONE/GPT 실제 유료 API 테스트입니다.
`--check-config`와 Mock 5초 기동·정상 종료를 확인했습니다. 상태 파일은 `running=false` 및 신규 `home_automation` 상태를 기록했습니다.
CLI 계약 표시는 v0.7로 갱신했으며 온도 유효성 확인 설정도 함께 표시합니다. 이 검사는 실제 서버 연결 검사가 아닙니다.
수정 후 integration/interaction/관련 테스트 34개 파일의 Python 3.11 문법 검사와 `git diff --check`도 통과했습니다.
`.env` 및 실행 출력은 기존 `.gitignore`에 의해 제외됩니다.

## 팀 확인 사항 / LG OS 배포 전 확인

1. 백엔드: AI GET에서 확인 가능한 제어 출처·명령 ID, 외부 수동 변경, 동시에 활성인 임베디드 자동 요구를 어떻게 표현할지.
2. 임베디드·백엔드: 조리 ON 유지와 외출 OFF 유지의 우선순위, 해제·재부팅·수동 조작·ACK 규칙. 현재 A/B는 미해결입니다.
3. 센싱·백엔드: present=false/room=null이 집 전체 유효 부재인지, 모든 구역 커버리지와 일부 노드 고장/unknown을 구분하는 근거.
4. 음성 확인 후 실행 시점의 최종 재실·온도·위험 재검증과 취소. 현재 AI의 송신 전 검사만으로 확인 대기 이후 안전을 보장하지 않습니다.
5. 보드 LG OS의 Python 3.11+, arm64 패키지 설치, 쓰기 가능한 상태 디렉터리, 시각 동기화, HTTP/MQTT 인증·TLS, 자동 재시작·중복 프로세스 방지.
6. 실제 배포 v0.7 지원, 모의 음성 AI 중지, 실제 공청기 상태·제어 결과·TTS 경로의 현장 시험.
7. Wi-Fi→백엔드 메시지 변환 배포와 온도 센서 오류·측정 시각 전달 계약. AI의 보수적인 차단만으로 이 연결을 완료했다고 볼 수 없습니다.

Windows/Python 3.13.5에서 자동 검증하며 Python 3.11 문법 호환성을 별도로 검사합니다.
LG OS/라즈베리파이에서 실행 검증했다는 의미는 아닙니다.
