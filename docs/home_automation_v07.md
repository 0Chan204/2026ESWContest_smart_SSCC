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
| 외출 전체 OFF | 첫 유효한 집 전체 `empty`에서 즉시 판단. 생산자의 전체 구역 부재 의미 확인 전에는 설정상 비활성 |
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

1. 기본 HTTP 입력은 `present=false`, 명시적 `room=null`, `observedAt`·양수 정수 `validSec`, 신뢰도 기본 0.8 이상이어야 합니다. `normalize_result`가 이를 내부 `empty`로 변환하되 원본 계약도 별도로 검사합니다.
2. 직접 MQTT 입력은 `location=empty`, `time`, `location_confidence`를 검사합니다. 선택적 `valid_until`을 준수하고, 유효기간이 없는 기존 Wi-Fi 포맷은 기존 `UNKNOWN_TIMEOUT`으로 만료시킵니다. 이 시간은 확인 대기가 아닙니다.
3. 두 경로 모두 측정 시각이 수신 시각보다 미래이거나 `allowed_lateness`보다 오래되면 거부합니다. 만료·오류 reason·invalid·unknown·누락을 부재로 간주하지 않으며, 백엔드 mock 계약도 부재 근거로 쓰지 않습니다.
4. 첫 유효한 `empty`를 수신한 처리 주기의 `HomeAutomation.tick()`에서 즉시 요청을 생성합니다. `away_confirm_seconds`는 제거했으며 행동 결합 버퍼와 이벤트 재정렬을 기다리지 않습니다. 중앙 위치·행동 판단에는 기존 결합·재정렬 정책이 계속 적용됩니다.

`InputRouter` → 수신 시점 재실 검증 → `HomeAutomation` → 기존 outbox/episode ID →
`POST /api/v1/ai/decisions` 순서로 전달합니다. 동일 외출 에피소드의 반복 결과는 새 명령을 만들지 않고,
응답 유실 시 기존 decision ID로 재시도합니다. 마지막 측정 시각을 저장하여 귀가·재시작 후 과거 `empty` 재생도 차단합니다.

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
- 전체 외출: 첫 유효한 부재 관측에서 실제 받은 신뢰도, `observed_absence_confidence`.
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

`config/decision_policy.toml`의 `[home_automation]` (`homevis.toml`에서 자동 연결):

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| air_purifier_enabled / cooking_air_clean_enabled | true / true | 상태 수용 / 조리 규칙 활성화 |
| air_purifier_off_on_good_or_normal | true | 출처가 확인된 경우에만 OFF 검토 |
| air_purifier_clean_hold_seconds | 30 | 양호한 새 관측의 연속 유지 시간 |
| away_all_off_enabled / whole_home_presence_verified | true / false | 규칙 준비 / 전체 집 부재 계약 확인 |
| away_min_confidence | 0.8 | 전체 부재 관측의 최소 신뢰도; 추가 확인 대기 없음 |

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
| `config/homevis.toml`, `config/decision_policy.toml`, `.env.example`, `README.md`, 문서 | 연결 설정·판단 기준·실행법·미확정 계약 명시 |

## 검증

개발용 테스트 파일은 이후 삭제했습니다. 아래 수치와 테스트 설명은 삭제 전 검증 기록입니다.
현재 기동 확인은 실행 파일을 사용합니다.

```powershell
python run_homevis.py --check-config
python run_homevis.py --mode mock --duration 15
```

삭제 전에는 실제 `get_device_info()` 함수와 요청 모델로 lastControl 누락과 자동 OFF 보류도 검증했습니다.
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

## 팀 전달용 요청사항

작성 기준: 2026-10-26. **아래는 팀 간 확인·수정 요청이며 확정 API 명세가 아닙니다.**
이번 범위는 AI 저장소의 보호 로직과 문서입니다. Wi-Fi·백엔드·임베디드 저장소를 수정하거나
새 MQTT 토픽·API·우선순위 필드를 임의로 만들지 않습니다. 담당자 이름과 일정은 팀에서 정해야 합니다.

AI의 연속 GET·판단 POST, 잘못된 센싱 이후 누적 근거 초기화, 정상 cooling 종료 처리,
온도 계약 미확인 시 가열·복구 차단은 이미 반영했습니다. 기존 중앙 confidence·피드백 학습 구조는 유지합니다.
팀에는 아래 항목별로 **적용 커밋/배포 버전, 실제 입출력 샘플, 정상·오류 시험 결과**를 요청합니다.
키·토큰·사용자 음성 원문 등 민감정보는 공유 자료에서 제거하세요.

### 요청 요약

| ID | 협의할 팀 | 요청 / 완료 확인 | 미완료 시 AI 처리 |
| --- | --- | --- | --- |
| R1 | Wi-Fi + 백엔드 | 최종 추론 MQTT → 백엔드 저장 → 센싱 GET까지 같은 측정이 전달되는지 확인 | HTTP 경로 유지, 잘못된 결과는 진단·거절. 임의 MQTT 우회 없음 |
| R2 | Wi-Fi + 백엔드 | 집 전체 부재·unknown·노드 고장 구분, 구역/노드 매핑 확정 | 전체 외출 OFF 보류 |
| R3 | Wi-Fi + 백엔드 | 실제 행동 JSON, 신뢰도·시각·이벤트 중복·설명 계약 제공 | 미측정 자세·still·행동을 생성하지 않음 |
| R4 | 임베디드 + 백엔드 | 온도 센서 유효성·실제 측정 시각·오류가 AI GET까지 전달됨을 검증 | live 인덕션 ON·증가·복구 보류 |
| R5 | 백엔드 + 임베디드 | 실제 제어 출처와 commandId 보존, 동시에 유효한 공기질 자동 요구 식별 | 소유권 없는 공청기 OFF 보류 |
| R6 | 백엔드 + 임베디드 | 조리 ON/외출 OFF 유지, 수동 변경·재시작·해제 우선순위 합의 | 중복 요청은 막지만 물리적 ON/OFF 유지 보장은 불가 |
| R7 | 백엔드 + 임베디드 + 대시보드 | 음성 승인 후 최종 안전 검증, 낙상 사건 종료, 실제 ACK·음성 출력 검증 | AI 송신 전 검증만 수행, 미확인 실행 성공·사건 종료를 주장하지 않음 |

### Wi-Fi 담당에게: R1·R2·R3

1. **백엔드까지 전달되는 최종 결과 연결을 정해주세요.**
   - 확인한 Wi-Fi 출력은 `wifi/occupancy/state`의 `time/location/location_confidence`입니다.
   - 백엔드는 `home/edge/result`의 `observedAt/room/confidence` 등을 저장합니다.
   - 변환을 생산자에서 할지 백엔드에서 할지 담당을 정해주세요. 토픽 이름만 바꾸면 해결되지 않습니다.
   - 시간·위치·신뢰도는 의미가 일치하는지 확인한 뒤 대응시키고, 관측하지 않은 `present/validSec`를 임의로 채우지 마세요.
   - 실제 발행 JSON과 동일 결과의 백엔드 GET JSON을 한 쌍으로 보내주세요. 원시 CSI나 학습 CSV는 이 연결 샘플을 대체하지 않습니다.

2. **집 전체 부재와 단순 불확실을 구분해주세요.**
   - 모든 구역을 포함하는 최종 결과인지, `empty`가 어느 범위의 부재인지 확인이 필요합니다.
   - `room/kitchen/toilet`과 실제 노드 ID 매핑표, 일부 노드 고장·낮은 신뢰도·초기화 중 출력 예시를 주세요.
   - `unknown`·노드 오프라인을 `present=false`로 바꾸지 마세요.
   - `present=false, room=null`을 전체 집의 유효한 부재로 보증할 수 있을 때만 그 의미를 명세에 확정해주세요.
   - AI는 확인 전 `whole_home_presence_verified=false`를 유지합니다. 계약 확인 후 첫 유효한 전체 `empty`에서 즉시 판단하며, 반복 GET은 새 외출 명령을 만들지 않습니다.

3. **행동 생산자의 실제 패킷을 주세요.**
   - 대상 라벨은 `none/fall/lie_down/get_up`입니다. 각 라벨의 실제 JSON과 `activityConfidence` 의미를 확인해주세요.
   - `observedAt`이 6초 추론 창의 시작/끝 중 무엇인지, 발행 지연, 유효기간, 위치와 행동의 시각이 같은지 알려주세요.
   - 같은 이벤트/관측 창의 재전송 식별 방식도 필요합니다. 재전송할 때 측정 시각을 현재 시각으로 갱신하지 마세요.
   - 정상 추론 이유와 오류 진단을 구분할 계약이 필요합니다. 현재 AI의 `reason`은 오류 진단으로 처리하므로 정상 설명을 무조건 넣으면 제어가 보류될 수 있습니다.
   - 네 행동 라벨에는 지속 `lying`이나 실제 `still`이 없습니다. 추가 측정이 없으면 취침 600초/화장실 눕기 후 정지 5초를 만족한다고 보고하지 마세요.
   - `motion_state/fall_detected`는 기존 확장 입력이지 확인된 백엔드 필수 필드가 아닙니다. 새 설명·시각 필드명도 샘플과 합의 후 AI 경계 어댑터에 반영합니다.

**수신 확인 기준:** 정상 위치 이동·동일 관측 재전송·unknown·노드 고장·행동 4종·만료된 행동을
백엔드 GET까지 전달하고, AI에서 각각 새 관측/중복/무효/이벤트로 구분해야 합니다.
현재 AI의 정렬 지연 기본 4초 및 위치·행동 결합 기준과 실제 생산 지연이 맞는지도 함께 시험해야 합니다.

### 백엔드 담당에게: R1·R4·R5·R7

1. **센싱 변환·저장·GET 계약을 함께 확정해주세요.**
   - 기존 `GET /api/v1/sensing/results`를 유지하며 측정 시각, 유효기간, 신뢰도, 구역, 진단 의미를 보존해주세요.
   - `savedAt`이나 GET 시각으로 `observedAt`을 덮어쓰지 말고, 저장할 수 없는 결과와 미수신을 구분해주세요.
   - 실제 `/api/v1/ai/device-states` 응답도 공유해주세요. 문서 예시만이 아닌 배포 서버의 필드·버전 확인이 필요합니다.

2. **온도 측정의 유효성 정보가 사라지지 않게 해주세요.**
   - 현재 인덕션 GET은 `state/level/temperature`와 기기 `updatedAt`을 제공하지만 온도 센서 유효성·독립 측정 시각은 없습니다.
   - 임베디드와 오류·초기 미측정·오래된 값의 표현을 정하고, 스키마·저장·GET 전체에서 의미가 유지되도록 해주세요.
   - 새 필드가 필요하다면 이름·타입·누락 시 처리·구버전 호환을 먼저 합의해주세요. AI는 아직 미확정 필드를 구현한 상태가 아닙니다.

3. **공청기 제어 출처를 AI가 확인할 수 있게 해주세요.**
   - 확인한 `app/ai_service.py:get_device_info()`는 `current_state`에서 기존 `lastControl`을 제거합니다.
   - AI는 실제 `lastControl.publisher=api`와 `commandId`가 자신의 조리 ON 응답과 일치하는지 확인해야 OFF를 검토할 수 있습니다.
   - 기존 출처를 GET에 보존하는 방식부터 검토해주세요. `control_state=homevis` 하나로는 AI·임베디드 자동 제어를 구분할 수 없습니다.
   - 마지막 명령 이후에도 공기질 자동 ON 요구가 살아 있다면 이를 어떻게 구분할지도 임베디드와 협의해주세요. 마지막 commandId만으로 동시 요구의 우선순위가 해결되지는 않습니다.

4. **AI 판단 이후의 최종 실행을 검증해주세요.**
   - 음성 확인 대기 중 재실 이탈·온도 이상·낙상·외출이 발생했을 때, 승인 시점 재검증/취소를 누가 수행하는지 정해주세요.
   - AI는 승인 대기 이후 재POST하지 않습니다. 승인 화면만 통과하면 무조건 안전하다고 해석하면 안 됩니다.
   - 동일 decisionId/voiceId 중복, 만료, 재시작, `sent` 이후 실제 ACK 실패를 시험해주세요.
   - 낙상은 백엔드의 사건 조회 상태로 종료합니다. 사용자·보호자 응답과 타이머 재시작 복구, 실제 신고 수단을 별도로 확인해주세요.
   - STT·시작어 처리·확인 UI·TTS는 기존 백엔드/대시보드 경로를 유지하고, 음성 안내 중복 재생 여부를 확인해주세요.

### 임베디드 담당에게: R4·R5·R6

1. **온도 오류가 정상 측정처럼 전달되지 않게 해주세요.**
   - 검토한 develop `1f0e262`는 최초 측정 전 25℃, 센서 오류 시 마지막 온도를 사용합니다.
   - 새 기기 heartbeat만으로 AI가 이 숫자를 새 정상 온도로 볼 수 없도록 실제 측정 시각·유효/오류 의미를 전달해야 합니다.
   - 정상 측정, 부팅 직후, 센서 분리/고장, 오래된 값 반복, 재연결을 각각 시험하고 백엔드 GET에서 구분되는 결과를 주세요.
   - `cooling`은 정상 가열 종료로 반영했지만 `overheated`나 서로 모순되는 전원·상태는 정상 종료로 인정하지 않습니다.

2. **기기에서 적용된 명령의 출처와 결과를 보존해주세요.**
   - AI 요청의 `commandId`, 실제 수동 조작, 임베디드 자동 제어를 구별할 수 있어야 합니다.
   - ACK의 적용/거절/실패와 뒤따르는 실제 상태가 일치하는지 확인해주세요. 명령을 받았다는 사실만으로 성공 처리하지 않습니다.

3. **공기질 기본 제어와 AI 요청의 충돌 규칙을 백엔드와 정해주세요.**
   - 공기질 측정·PM 임계값·기본 공청기 ON/OFF는 계속 임베디드 역할입니다.
   - 조리 ON 유지와 외출 OFF 유지의 적용·해제 조건, 사용자 수동 조작, 위험 상태, 재부팅·연결 끊김 시 정책을 합의해주세요.
   - 귀가만으로 인덕션이 다시 켜지면 안 됩니다. 공청기 유지 해제와 인덕션 재점화는 별도 정책입니다.
   - 현재 command 계약에는 공유 우선순위/유지/외출 잠금 정보가 없습니다. 새 토픽이나 필드로 임의 구현하지 말고 기존 계약 확장 여부부터 합의해주세요.

**공동 A/B 완료 기준:**

| 시험 | 실제 장치에서 확인할 결과 |
| --- | --- |
| A: 인덕션 ON + 공기질 good → AI 공청기 ON | 합의한 조리 유지 조건 동안 임베디드가 다시 OFF하지 않음. 종료·수동 변경·연결 단절 시 합의한 해제 규칙 적용 |
| B: 전체 외출 확정 + 공기질 bad → 백엔드 전체 OFF | 합의한 외출 유지 조건 동안 임베디드가 다시 ON하지 않음. 정수기 제외, 재시작 후 정책 유지·해제 확인, 귀가만으로 인덕션 ON 없음 |

현재 AI의 A/B 테스트는 반대 상태를 주입해 반복 명령을 막는 테스트입니다.
위 실제 장치의 유지·우선순위 동작은 아직 검증 완료가 아닙니다.

### 협의 후 AI에서 할 일과 배포 조건

- 팀이 확정한 실제 입력 샘플로 경계 어댑터·계약 회귀 테스트를 보완합니다. 중앙 confidence나 공기질 임계값을 바꾸는 작업은 아닙니다.
- R4의 의미·데이터 경로·오류 시험이 확인되고 AI가 합의된 유효성을 검사할 수 있는지 검토한 뒤에만 `stove_temperature_validity_verified` 활성화를 검토합니다. 이 플래그 자체가 샘플별 유효성을 검증하지는 않습니다.
- R2 확인 및 부분 노드 고장/unknown/재전송 시험 후에만 `whole_home_presence_verified` 활성화를 검토합니다.
- 실제 서버 v0.7 지원, 브로커 인증·ACL·TLS, 동일 client ID 충돌 방지, 모의 음성 AI 중지를 확인합니다.
- 보드의 Python 3.11+, arm64 패키지, 쓰기 가능한 데이터 경로, 시각 동기화, 자동 재시작, 중복 프로세스 방지를 확인합니다.
- 실가전 시험은 담당자 감독하에 진행합니다. AI의 Mock/로컬 소켓 검증을 실제 기기 안전 보증으로 대체하지 않습니다.

Windows/Python 3.13.5 자동 검증과 Python 3.11 문법 검사는 수행했으나,
LG OS/라즈베리파이에서 실행 검증했다는 의미는 아닙니다.
