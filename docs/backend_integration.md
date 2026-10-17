# 백엔드 클라이언트 및 최종 위치 입력

AI가 `GET /api/v1/ai/device-states`를 조회하고, 기존 중앙 판단 출력을
`POST /api/v1/ai/decisions`로 전달하는 클라이언트 경로다. 제공된 JSON 계약을 기준으로 구현했다.
제공 자료는 요청·응답 예시와 후속 설명이며 OpenAPI/서버 모델은 포함되지 않았다.
후속 합의에 따라 계산된 confidence는 유지하고, 점수가 없는 규칙 결과만 null을 전송한다. 출수 외 API 허용값, 실행 ACK·낙상 사건 동기화 API는
추측해서 추가하지 않았다. 실제 직렬화와 대조하는 전체 Mock 요청·응답은 [README](../README.md)에 있다.

## 구성과 실행

| 파일 | 역할 |
| --- | --- |
| `src/integration/config.py` | mock/live, 시간, 매핑, 검증된 단위/상태 해석 설정 |
| `schemas.py` | timezone을 요구하는 시각 파싱, 기기·판단·접수 응답 검증 |
| `sensing.py` | 최종 위치 JSON 원본 보관, 내부 위치 변환, 별도 행동 입력 경계 |
| `state_mapper.py` | 장비 원본/관측/조회 시각 보관, 보수적 장비 모델 변환 |
| `decision_mapper.py` | 기존 출력의 안정적 ID, 실제 근거, 백엔드 JSON 또는 차단 진단 |
| `outbox.py` | SQLite 원자적 저장, 재시도, 응답, 출수 예약, 미해결 낙상 사건 |
| `runtime.py` | 단일 소유자 순차 판단, 관측 시각 정렬, tick, 비동기 HTTP |
| `backend_client.py` | 표준 라이브러리 HTTP; 고정 경로, timeout, 인증 헤더 주입 |
| `mock_backend.py` | 중복 접수·응답 유실 등을 재현하는 메모리 백엔드 |
| `examples/backend_integration_demo.py` | 위치만 입력하는 기본 데모 및 별도 가상 행동 데모 |

`README.md`, `src/`, `tests/`가 있는 저장소 루트에서 실행한다.
추가 런타임 의존성은 없다. 통합 테스트에는 pytest가 필요하다.

Windows PowerShell:

```powershell
python -m pytest -q
python -m examples.backend_integration_demo
python -m examples.backend_integration_demo --with-mock-behavior
python -m src.integration --duration 3
```

Linux 또는 pytest가 설치된 일반 Python 환경:

```sh
python -m pytest -q
python -m examples.backend_integration_demo
python -m examples.backend_integration_demo --with-mock-behavior
python -m src.integration --duration 3
```

Linux 명령은 실행 안내이며 이 작업 환경에서 직접 실행하지 않았다.
기존 `python -m unittest discover -s tests -v`는 기존 unittest 테스트를 실행한다.
새 pytest 통합 테스트까지 검증하려면 `python -m pytest -q`를 사용한다.

기본 데모는 **위치만** 공급한다. 행동이 없으므로 출수·취침·낙상 기능을 실행하지 않는다.
`--with-mock-behavior`는 별도 `BehaviorObservation` 가상 측정을 명시적으로 공급한다.
`room`은 모든 실행 모드에서 취침·기상 판단의 표준 공간이다. `idle`은 출수 준비 조건으로 사용하지 않는다.
데모만 별도 가상 필드 `mock_readiness=ready`를 공급한다. 이 필드는 실제 백엔드 계약이 아니다.
점수 없는 규칙 결과의 confidence=null은 Mock 전용 예외가 아니라 합의된 기본 전송 정책이다. 5회 상태 조회 후 기존 기상→주방 판단으로 120mL 요청을
1회 접수한다. `202/accepted`, `actions[].status=sent`는 실제 출수 완료가 아니다.
낙상 입력(motion/fall)은 이 데모에도 없으며, 누락으로 보고한다.
기본 데모 데이터는 임시 디렉터리에 보관하고 종료 시 정리한다.
`--data-dir output/demo`로 지정하면 재시작 후 outbox와 일일 출수 예약을 확인할 수 있다.

출수량은 `ScenarioConfig.MORNING_WATER_AMOUNT_ML=120` → `DeviceCommand.amount_ml` →
POST의 `actions[].amountMl`로 전달한다. 대표 데모도 같은 기본값을 사용하고,
`weatherBriefing=true`를 유지한다. 별도 출수량 설정도 가능하며 기존 pending/sending 요청의
수량·본문·`decisionId`와 과거 `lastDispensedMl`은 새 기본값으로 덮어쓰지 않는다.

주방 이탈 위험 단계는 엔진이 계산한 이탈 시간 기준 20/40/60초다. 이탈 시간 feature의
최대 기준도 60초지만, 실제 화력 감소는 기존 confidence threshold 0.82 및 실행 조건을 따른다.
자세한 기준은 [실시간 판단](realtime_control.md)과 [Confidence 제어](confidence_control.md)에 있다.

실제 연결은 `--mode live --base-url <확인한 URL>`로 명시적으로 선택한다.
CLI는 장비 polling/tick 호스트이며 센싱 통신은 붙이지 않았다.
실제 센싱 어댑터가 결정되면 같은 실행 스레드에서
`runtime.ingest_location(payload, received_at=...)`를 호출하고 `run_once()`를 주기적으로 호출한다.
HTTP 작업 스레드는 엔진이나 SQLite를 변경하지 않는다. 런타임·컨트롤러는 한 스레드,
outbox는 한 프로세스가 소유해야 한다.

## 최종 Wi-Fi 위치 계약

```json
{"time":"2026-10-02T15:05:03+09:00","location":"kitchen","location_confidence":0.87}
```

```json
{"time":"2026-10-02T15:05:04+09:00","location":"unknown","location_confidence":null,"reason":"node_offline:r3"}
```

Pi의 `features` 배열은 거부한다. 노드 ID를 장소로 분류하지 않는다.

| 원본 location | 내부 location | 관측 처리 |
| --- | --- | --- |
| kitchen | kitchen | 유효한 수치 신뢰도가 있으면 후보 관측 |
| toilet | toilet | 동일 |
| room | room | 취침·기상 판단에 사용하는 방; 별도 매핑 설정 불필요 |
| bedroom / bathroom | room / toilet | 이전 입력의 별칭; raw는 변경하지 않음 |
| empty | unknown | empty 원문 보존; outside로 변환하지 않음 |
| unknown | unknown | unknown 원문 보존; 위치 무효 |
| r2/r3/r4 및 미등록 값 | unknown | 명시적 `unmapped_room` 진단 |

`LocationObservation.raw` 및 outbox의 `location_received` 감사 기록에 원본 JSON,
원본 null, reason 전체, 측정 시각, 수신 시각, 변환 유효성을 별도로 보관한다.
reason은 열거형으로 잘라내지 않는다. `node_offline:r3`, `config_mismatch` 및 새 오류도
그대로 남기며, 비어 있지 않은 reason은 보수적으로 무효 관측으로 처리한다.
원본 null은 내부 숫자형 confidence에만 0으로 맞추고 `observation_valid=False`로 명시한다.
수치가 유효하더라도 기존 `MIN_CONFIDENCE` 미만이면 현재 판단에서 신뢰하지 않는다.

`time`은 timezone-aware datetime을 거쳐 Unix 초로 변환한다. 원본 문자열도 보존한다.
조회 시각을 측정 시각으로 덮어쓰지 않는다. 같은 스트림/측정 시각/본문은 다시 넣지 않으며,
같은 시각에 다른 본문이면 충돌로 기록하고 더 새로운 관측 전까지 신뢰하지 않는다.
따라서 반복 조회로 위치 확인 시간이나 sensor history를 채울 수 없다.

`RealtimeDecision.user_location`은 마지막 확인 위치다. `observation_valid=False` 또는
`sensing_status=invalid/timeout/unconfirmed`를 함께 확인해야 한다.
명시적으로 무효인 통합 입력은 즉시 불확실하게 취급하며, 기존 위험을 정상으로 해제하지 않는다.
기존 직접 호출의 `observation_valid=None`은 기존 unknown 유예 정책과 호환되지만,
해당 유예 중에도 무효 관측으로 자동 복구하지 않는다.

`runtime.sensing_health()`는 다음을 따로 제공한다.

- `message_timeout`: 마지막 메시지 수신 후 timeout. HTTP 조회 성공 여부와 별개다.
- `measurement_stale`: 마지막 측정이 오래됨. 같은 JSON을 계속 받아도 참이 된다.
- `explicit_invalid`: 원본 무효·reason·낮은 신뢰도·충돌 등.
- `raw_location`, `raw_confidence`, `reason`, `measured_at`, `last_received_at`.
- `applied_measured_at`, `applied_observation_valid`, `last_confirmed_location`: 정렬 대기 중인
  수신 관측과 이미 엔진에 적용한 관측을 구분한다.

오래된 unknown JSON을 계속 받으면 `invalid`, `measurement_stale=True`,
`message_timeout=False`다. 메시지까지 끊기면 timeout도 별도로 참이 된다.
엔진의 `sensing_status=timeout`은 측정의 신선도 기준이며, 실제 메시지 단절은
통합 계층의 `message_timeout`으로 구분한다.

## 행동 정보와 위치 확인 지연

위치 JSON에서 `activity`, `motion_state`, `fall_detected`를 만들지 않는다.
내부 모델의 `activity="unknown"`은 미측정 표식이고 `activity_observed=False`다.
기존 주방 점수 경로의 `activity_confidence=None → location confidence` fallback을 제거했다.
미측정 행동은 점수의 activity feature를 0으로 입력한다. 가중치 재분배나 threshold 변경은 없다.
`LightContext`의 미지정 행동 신뢰도 기본값도 0이며 통합 전등 경로에서 명시적으로 전달한다.

취침은 lying 관측, 기상 기반 출수는 수면→기상 관측, 낙상은 fall 신호 또는 행동 전이 및
motion 정보가 필요하다. 런타임의 `missing_inputs`가 이를 표시한다.
전등의 일반적인 재실 제어는 위치를 사용할 수 있지만, 기기 상태 조회로 재실을 생성하지 않는다.

전체 기기는 단일 GET의 `items[]`를 `device`와 설정된 `deviceId`로 구분해 적용한다. 기기별 조회는 없다.
사용자는 Wi-Fi 위치와 별도 실제 행동 측정을 `ingest_location(payload, behavior=...)`로 결합한다.
실제 반영 필드는 `SensingUpdate.location/activity/motion_state/fall_detected`이며
`activity_confidence/activity_timestamp/activity_valid_until/activity_observed`도 함께 보존한다.
`idle → sitting → lying` 측정은 사용자 행동만 갱신한다. 기기 원본 `current_state.status`를 AI가 덮어쓰거나,
status를 실제 행동 측정으로 복제하지 않는다. 전원·level·lastDispensedMl·updatedAt은 GET 원본 그대로다.
`location_applied` 감사 기록의 `sample`에서 엔진에 적용한 사용자 상태를 확인할 수 있다.
위치 전용 JSON에 없는 행동 필드나 센싱 API를 추측해 추가하지 않았다.

현재 행동 입력 경계는 `BehaviorObservation(measured_at, valid_until, location, confidence, ...)`다.
이것은 내부 입력 모델이며 실제 행동 API를 가정한 것이 아니다.
별도 행동 신뢰도, 유효 표시, 같은 내부 공간, 위치 측정 이전의 행동 측정,
최대 시각차(`behavior_max_skew`, 기본 1초), 만료 전 조건을 만족해야 결합한다.
다른 공간·미래·만료·무효·신뢰도 누락 행동은 결합하지 않는다.
동일 행동 측정을 재사용해 새 행동 관측처럼 시나리오에 넣지 않으며,
유효 기간 사이 공백은 연속 lying·기상 확인·stillness 확인을 끊는다.
행동이 사라진 낙상 사건은 센서 불확실로 남고 정상 회복으로 처리하지 않는다.

센싱 쪽 전환 확인 2~3초 뒤 처음 최종 위치가 나오면, 엔진은 그 측정부터 다시
`SENSING_CONFIRM_TIME=5초`를 확인한다. 결과적으로 **7~8초**가 필요하다.
기본 정렬 여유 2초까지 포함하면 처리 시점 기준 **9~10초 + 전송/조회 지연**이다.
서로 다른 새 측정들이 계속 들어온다는 조건의 값이다. tick만으로 후보가 확인되지는 않는다.
원본 JSON에 전환 시작 시각이나 사전 확인 구간이 없으므로 이전 2~3초를 임의로 소급하지 않는다.
복귀·현관·외출·낙상 안전 조건은 유지했다. 배포 지연 목표에 맞춰 조정하려면
센싱의 확인 구간 계약과 안전 평가가 먼저 필요하다.

## 기기 변환 및 복구

기본 기기 식별은 stove/induction-01, light/light-01, water_purifier/water-01이다.
공간은 `room/kitchen/toilet`, 기기는 `stove/light/water_purifier`로 통일한다.
전등은 `device=light`와 별도의 `room`으로 구분한다. `room` 위치 관측과 같은 방의 전등 상태를
취침·기상 및 재실 판단에 사용한다. 미등록 기기/공간은 진단을 남기며 toilet 전등을 room 전등으로 대체하지 않는다.
`bedroom/bathroom/water_dispenser/induction/*_light`는 입력·저장 기록을 읽는 경계에서만 해석한다.
이전 outbox의 source/payload/decisionId는 갱신하지 않고 재시도에도 원래 본문을 사용한다.
기존 `room_is_bedroom` 인자는 호환 목적으로만 남으며 room의 의미를 바꾸지 않는다.
외출·미감지·센싱 오류를 나타내는 내부 상태는 유지하고 백엔드의 세 구역으로 강제 변환하지 않는다.
전송 직전에도 payload의 room과 실제 장비의 매핑을 비교한다.

`level=5`는 W가 아니다. 기본 `power_watts=None`이며 `power_watts_unmeasured` 진단을 남긴다.
검증한 `level_to_watts` 또는 실제 W 필드 이름 `watts_field`가 있을 때만 전력을 채운다.
온도 단위도 제공 예시만으로 확정하지 않아 `temperature_is_celsius=True`로 확인한 경우에만 사용한다.
`ApplianceUpdate.level`과 `RealtimeDecision.level`에 정수 단계를 그대로 전달한다. 최대 단계를 가정하지 않는다.
raw current_state에는 level/temperature를 그대로 남긴다.
기존 FeatureExtractor에서 미측정 전력은 stove_power feature=0이며, 기본 가중치의
위치만 있는 장기 이탈 테스트에서 자동 화력 감소가 발생하지 않음을 검증한다.
위험 알림 상태는 점수 기반 가전 명령과 독립적이므로 장기 이탈 위험은 남을 수 있다.

`user/homevis/null`은 제어 주체 정보일 뿐, 내부 NONE/HOMEVIS_REDUCED/USER_OVERRIDE로
직접 대응하지 않는다. 통합 경로에서는 control_state=None을 사용하고 복구는 비활성화한다.
이유는 다음과 같다.

| 상태 | 현재 통합 처리 | 복구에 부족한 근거 |
| --- | --- | --- |
| 일반 HomeVIS 감소 | 원본 주체 보관, 복구 차단 | 감소 commandId, 실행 확인, 감소 전 화력, 사용자 변경 여부 |
| HomeVIS 부재 차단/OFF | OFF 원문 유지, 복구 차단 | 비상/사용자 종료와 구별되는 차단 사유, 재가동 허가 |
| 사용자 종료 | OFF 유지, 자동 복구 없음 | 사용자 의사를 덮어쓸 근거 없음 |
| 비상 차단/미해결 낙상 | 복구 차단 | 사건 종료 확인과 별도 안전 재가동 정책 |
| 통신/상태 불명 | 마지막 값은 보관하되 stale | 최신 유효 관측 및 실행/제어 이력 |

기존 엔진은 OFF 관측에서 감소 기억을 초기화하고 stove_off guard도 사용한다.
따라서 백엔드의 “끄거나 낮추기 직전 화력으로 복구” 전체 의미와 일치하지 않는다.
이를 우회하기 위해 OFF를 ON으로 바꾸거나 guard를 삭제하지 않았다.
기존 직접 호출의 확인된 HOMEVIS_REDUCED 복구 경로는 유지했고,
센서 무효·장비 stale·비상 중 복구 방어 조건을 추가했다.

정수기의 `is_on=false`만으로 출수 불가능하다고 보지 않는다.
반대로 online=true만으로 준비됐다고 보지도 않는다.
`status=idle`은 사용자 상태 설명이며 출수 준비 근거가 아니다. sitting/lying 등 행동 값도 같은 원칙이다.
준비 상태는 별도 확인된 `current_state` 필드(`water_ready_field`)와 허용값(`water_ready_states`)이 있어야 한다.
두 설정의 기본값은 None/빈 tuple이므로 실제 준비 조건이 제공되기 전에는 출수를 보류한다.
이전 `water_ready_states=("idle",)`만 지정해도 출수를 허용하지 않으며 `water_ready_field="status"`는 거부한다.
Mock은 `mock_readiness=ready`라는 독립적인 가상 필드만 사용한다. 실제 서버의 필드를 주장한 것이 아니다.
lastDispensedMl은 과거 상태로 보관하며 요청량으로 쓰지 않는다.

## 시간순 처리와 불확실 상태

`updatedAt`/센싱 `time`은 측정 시각, `fetched_at`/`received_at`은 수신 시각,
감사 기록의 `processed_at`은 판단 처리 시각이다.
watermark=`현재 시각-allowed_lateness`까지 heap으로 정렬한 이벤트를 처리하고 tick한다.
watermark보다 늦게 도착한 과거 이벤트는 원본과 진단을 기록하고 엔진에 재주입하지 않는다.
미래 측정 시각도 거부한다. 허용 범위 내 역순 도착, 같은 시각 중복, tick 이후 지연 도착을 테스트한다.

센싱이 멈춰도 run_once의 tick은 계속된다. HTTP GET/POST는 별도의 두 작업 스레드에서
각각 timeout을 적용한다. 한 번의 호출 안에서 sleep하며 반복 재시도하지 않고 다음 시도를 예약한다.
GET 실패나 offline은 OFF로 만들지 않는다. 동일 updatedAt을 반복 조회해도 장비 관측이 새로워지지 않는다.
현재 updatedAt이 상태 변경 시각인지 heartbeat 시각인지 미확정이므로, 반복된 snapshot은
APPLIANCE_TIMEOUT 뒤 stale로 평가한다. live에서 가전이 정상이어도 오래된 updatedAt만 반환한다면
제어가 차단될 수 있으며 백엔드와 갱신 기준을 합의해야 한다.

### 판단용 기기 상태와 송신용 기기 상태

기본 `allowed_lateness=2.0`은 유지한다. `latest_received_devices`(기존 `devices`와 같은 객체)는
최신 수신 관측을, `evaluated_devices`는 현재 처리 시각 이하에서 마지막으로 적용한 관측을 보관한다.
별도의 DB 이력은 추가하지 않고 기존 heap에서 stove/light/water_purifier 모두 시간순으로 적용한다.
offline 관측도 그대로 적용하고, 누락·잘못된 응답·조회 실패는 수신/오류 시점의 무효화 이벤트로 처리한다.
더 최근의 오류를 건너뛰어 예전 정상 관측을 선택하지 않는다.

| 시각 | 의미와 사용처 |
| --- | --- |
| 원본 측정 시각 | 기기의 `updatedAt`, 위치의 `time`, 행동의 `measured_at`; 조회 시각으로 바꾸지 않음 |
| 수신 시각 | `fetched_at` / `received_at`; 원본 측정 시각과 별도 보관, 통신 실패 시점도 구분 |
| 평가 시각 | 각 이벤트의 측정 시각 및 마지막 watermark=`now-2초`; 이 시각 이하의 기기 관측만 사용 |
| 송신 시각 | 전송 직전 `now`; 최신 수신 기기·위치·행동의 유효성과 명령 TTL을 다시 검사 |

예를 들어 현재 T+10, watermark T+8이면 판단에는 T+8 이하의 상태를 사용하고,
송신 직전에는 이미 수신한 T+10 상태를 검사한다. T+8 정상/T+10 offline이면 과거 판단은 가능하지만
송신은 차단한다. 반대로 T+8 offline/T+10 정상이어도 T+8 평가를 정상으로 바꾸지 않는다.
평가 시각 이하의 관측이 없으면 미래 관측으로 대체하지 않는다. 음수 age를 보정하지 않는다.

같은 측정 시각에 이미 도착한 이벤트는 기기 관측 → 기기 무효화 → 센싱 순서로 처리한다.
따라서 수신 순서가 반대여도 같은 시각의 정수기 준비 상태를 사용한다. 한 번의 `advance()`가 여러
시각을 처리해도 각각의 센싱 시점에 맞는 상태를 사용하며, 조명은 최종 watermark에서 평가한다.
아직 도착하지 않은 이벤트를 가정하지 않는다. 허용 지연을 넘긴 관측은 기존처럼 진단 후 제외한다.
이미 적용한 관측의 충돌이 뒤늦게 확인되면 그 캐시를 무효화하되 엔진 시간을 되돌리거나
더 새로운 정상 관측까지 무효화하지 않는다.

송신은 최신 offline, missing, malformed, conflict, HTTP 실패, stale, 정수기 busy/error를 별도로
차단한다. 이때 준비 신호의 busy/error는 별도 Mock 필드로 검증하며 사용자 status로 추정하지 않는다.
동일 `updatedAt`의 반복 조회는 freshness를 연장하지 않는다. 누락·조회 오류 등의
차단은 오류 전 관측보다 새로운 검증된 측정으로만 회복하며, 충돌은 그 측정 시각보다 새 관측이 필요하다.
미래 측정 시각은 거부하고 해당 조회의 오류도 유지한다. 이때 잘못된 시각을 `now`로 바꾼 관측은 만들지 않는다.

## 출력, 접수 및 재시작

기존 drain API는 유지한다. 통합 런타임은 `peek_outputs()`로 자동 제어/규칙 출력을 모두 조회하고,
outbox 트랜잭션 성공 후 `acknowledge_outputs()`로 해당 객체만 제거한다.
저장 실패 시 원본 큐가 남는다. drain_backend_requests와 그 내부 drain을 중복 호출하지 않는다.
위험 RealtimeDecision은 로컬 평가 기록으로 남기며 action 문자열을 가전 명령으로 변환하지 않는다.

출수는 water_dispense / water_purifier / dispense / amountMl / weatherBriefing으로 변환한다.
amountMl과 reason은 기존 명령 값 그대로 사용한다. 규칙 출력에 별도 confidence가 없으면 null을 전송한다.
기본 정책은 `rule_confidence_policy="null"`이며 기존 `"block"`은 명시적 배포 차단 옵션으로만 유지한다.
위험 점수나 위치 신뢰도를 대신 사용하지 않으며 전송을 위한 새 점수 계산은 없다.
이 정책 변경은 이미 저장된 blocked/pending/sending 요청의 ID·본문을 수정하거나 자동 재활성화하지 않는다.

AutomationAction confidence는 보존한다. reason에는 실제 threshold와 기여값을 문자열로 담고,
원래 features/weights/contributions와 action_id는 outbox source 및 기존 history에 보관한다.
출수 외 scenario/action은 기본 미지원이다. `action_routes`는 합의된 명세를 반영하는 명시적 설정이며,
reduce_power를 turn_off로 바꾸는 등 의미 변경은 거부한다.

안정적 source_id에서 decisionId를 생성하며 재시도·재시작에서 같은 본문과 ID를 사용한다.
송신 시도도 먼저 디스크에 기록한다. 재시작 시 sending은 동일 pending으로 복구하며
기존 시도 횟수와 만료 시각은 유지한다. 다중 프로세스 송신/실기기의 exactly-once는 보장하지 않는다.

- HTTP 202는 접수, 200+duplicate=true는 중복 접수다.
- sent는 전송 상태이며 실제 실행 완료가 아니다.
- rejected/failed의 사유와 commandId, eventId, fallIncidentId, weather, feedback 원본을 저장한다.
- 요청/응답 decisionId, scenario/confidence, action 대상과 개수를 검증한다.
- 부분 실패는 accepted_partial로 기록하고 새 ID로 전체 action을 재실행하지 않는다.
- timeout/일시 오류는 제한 재시도, 그 외 오류는 실패로 남긴다.
- 명령 TTL 만료와 최신 상태 재검증은 분리한다. 만료된 명령은 연결 복구 후 전송하지 않는다.
- 출수 전 장비 준비 상태·현재 주방 관측을 재확인한다. 복귀 후 오래된 소등/감소도 재검증한다.
  새로운 위치가 수신됐지만 아직 정렬 대기 중이어도, 기존 위치와 다르면 송신을 보류한다.

아침 출수 횟수는 명령을 내기 전에 예약 훅으로 디스크에 보관한다.
timeout 또는 응답 유실로 예약을 되돌리지 않는다. 재시작해도 같은 날 허용 횟수를 유지한다.
저장 도중 비정상 종료되어 예약만 남을 경우 출수를 놓칠 수는 있지만, 안전하게 중복 출수를 억제한다.
이미 보낸 명령을 뒤늦게 취소하는 백엔드 계약은 없으므로 전송 후 취소를 보장하지 않는다.

### 조명 시나리오별 송신 직전 재검증

백엔드 `scenario` 이름이 내부 이름과 다를 수 있으므로 outbox `source`의 원래 시나리오와
`target`/`device`와 별도 `room`을 사용한다. 이전 `bedroom_light` source도 읽기 경계에서 해석한다.
실제 전등의 방, 백엔드 방, 원래 대상이 일치해야 하며 이미 요청한 ON/OFF 상태인 전등에는 송신하지 않는다.

- `light_auto_off`: 유효하고 신선한 부재 근거가 필요하며 대상 방으로 돌아오면 차단한다.
  unknown·무효·stale 센싱이나 정렬 대기 중의 위치 변경도 허용 근거로 쓰지 않는다.
- `bedtime_light_off`: 침실에 있다는 사실은 차단 이유가 아니다. 실제 시나리오가 지속 조건을 채워
  생성한 현재 취침 구간의 요청인지, 지금도 그 침실에서 유효한 실제 lying 행동이 관측되는지 확인한다.
  행동 신뢰도·측정 시각·만료를 검사하며 `_requested=True`만으로 허용하지 않는다.
- `light_auto_on`: 기존의 현재 재실 및 확정 위치 검사를 유지한다. 미지원 시나리오는 차단한다.

기상·방 이탈·행동 누락/불확실·관측 공백은 정렬 대기 중이어도 기존 취침 요청을 차단한다.
다시 누워도 이전 요청을 되살리지 않으며, 새 취침 구간이 기존 임계시간을 충족해 만든 새 요청이 필요하다.
`BedtimeLightScenario.matches_current_request()`는 요청/취침 구간의 동일성만 읽기 전용으로 확인한다.
송신 재검증에서 `tick()`이나 `update_sensing()`을 호출하지 않는다.

정렬 지연 때문에 적용된 행동만 만료된 경우에는 최신 수신한 유효한 실제 행동으로 **이미 충족한**
취침 조건의 유지를 확인할 수 있다. 이를 이용해 취침 지속 시간을 앞당기지는 않는다.
위치 전용 입력에는 행동을 생성하지 않으며 취침 소등·기상 기반 출수·낙상 입력 부족 진단을 유지한다.
재시작으로 현재 취침 구간의 근거가 사라진 경우도 기존 pending 취침 요청을 임의 재사용하지 않는다.

#### 관측 공백 이후의 취침 구간과 서로 다른 측정 시각

위치의 `sample.timestamp`와 행동의 `activity_timestamp`는 서로 다른 측정의 시각이다.
수신 시각은 입력을 받은 시각이고, 엔진 평가 시각은 정렬된 이벤트 시각/마지막 watermark다.
위치가 T+20, 행동이 T+19이고 기존 결합 조건을 만족한다면 새 누움 구간은 행동 측정 T+19에서 시작한다.
새 행동이 수신됐다는 이유로 엔진의 T+18 평가를 앞당기거나 이전 누움 시간을 합산하지 않는다.

관측 공백을 발견한 **새 위치의 시각**을 중단 시각으로 기록하면 이 예에서 T+20 > T+19가 되어,
새 구간이 정상적으로 지속 조건을 채운 요청까지 `bedtime_observation_interrupted`로 차단될 수 있다.
공백 경계와 명시적 반대 관측은 다음처럼 기록한다.

| 원인 | 중단 근거를 기록하는 시각 | 요청에 미치는 영향 |
| --- | --- | --- |
| 새 행동 시작이 이전 행동의 만료보다 늦음 | 이전 행동의 `activity_valid_until` | 이전 구간을 종료하며, 그 뒤에 시작한 새 구간 내부의 중단으로 해석하지 않음 |
| 행동 유효기간은 길지만 위치 관측 간격이 timeout에 도달 | 이전 유효 위치의 측정 시각 | 기존 freshness/시나리오 timeout과 현재 요청 식별 검사로 이전 구간을 차단 |
| standing·방 이탈·unknown·행동 누락/무효/신뢰도 부족 | 해당 위치·행동 결합 관측의 위치 측정 시각 | 정렬 대기 중이어도 해당 구간의 요청을 송신하지 않음 |

예를 들어 이전 행동 근거가 T+11에 만료되고 새 위치가 T+20에 측정됐다면,
공백 표시는 T+11에 남는다. 새 행동의 시각이 T+20 / T+19.5 / T+19 중 어느 것이든
이전 만료 경계 뒤에서 새 구간을 시작할 수 있다. 첫 새 관측 두 개가 역순으로 도착해도
공백 경계는 이전 관측에서 얻으므로 새 구간 시작보다 뒤로 밀리지 않는다.

`_bedtime_interrupted_at > 구간 시작` 검사와 `matches_current_request()`를 함께 유지한다.
공백 이전 pending 요청은 기존 구간이 종료됐으므로 사용할 수 없고, 새로운 요청은 새 구간만으로
기존 취침 지속 조건을 충족해야 한다. 새 구간 내부에 늦게 도착한 반대 관측은 계속 차단 근거이며,
이미 끝난 이전 구간의 오래된 standing 관측을 새 구간 내부의 중단으로 해석하지 않는다.
새 lying마다 중단 표시를 지우거나 메시지 수신마다 새 구간 ID를 만들지 않는다.

행동 유효기간은 `[measured_at, valid_until)`이다. 위치 결합 시각 또는 송신 시각이
`valid_until` 이상이면 그 행동은 만료다. 다음 행동의 시작이 이전 `valid_until`과 정확히 같으면
양의 시간 공백 자체는 없으므로, 시나리오가 아직 유지되고 새 관측이 만료 tick 전에 적용되는 경우
기존 구간을 유지한다. 반면 기존 `tick()`이 만료 시각에 도달해 구간을 이미 종료했다면,
정렬 대기 중인 새 행동이 그 경계에 맞닿아 있어도 이전 요청을 되살리지 않는다.
새로 적용한 관측에서 구간을 다시 시작하고 지속 조건을 다시 확인한다.
예를 들어 행동 T+30 / 위치 T+31이 대기 중인데 엔진이 T+30 만료를 처리했다면 이 후자의 경우다.
수신 순서를 바꾸어도 동일한 시간순 적용 결과를 사용하며, timestamp 보정이나 epsilon은 사용하지 않는다.

이 수정은 공백 표시의 시간 의미만 바로잡는다. 시나리오의 행동 시작 시각·지속 시간·tick 의미,
결합 허용 시각차 1초, 기본 정렬 지연 2초, 명령 TTL은 그대로다. 재검증은 읽기 전용이다.
요청 모델과 API JSON에 구간 필드를 추가하지 않아 기존 `source_id`/`decisionId` 생성 방식도 유지한다.
재시작한 런타임에 현재 구간 근거가 없는 이전 pending 요청은 새 구간에 연결하지 않는다.

## 낙상과 백엔드 역할

낙상 시작·상태 전이·회복은 기존 `BathroomFallScenario`가 판단한다. 판단 로직과 임계시간은 변경하지 않는다.
`fall_owner="backend"`는 후속 대응의 소유자를 뜻하며 AI의 판단을 백엔드에 위임하는 설정이 아니다.
백엔드는 AI 결과를 받아 인덕션 차단·전등 깜빡임·문자·보호자 알림·신고 단계를 관리한다.
기존 직접 호출용 차단/깜빡임/문자/신고 요청은 로컬에 기록하지만 통합 송신에서는 억제한다.
낙상 상태용 scenario/action 및 사건 동기화 형식만 미확정이다. AI 낙상 판단이 미구현인 것은 아니다.
전달 시 사용할 경로는 기존 POST /api/v1/ai/decisions이며 별도 엔드포인트를 추측하지 않는다.
형식 확정 전에는 낙상 POST를 만들지 않는다.

런타임은 `fall_state_changed` 감사 기록에 기존 AI 상태의 변화와 측정 시각, 처리 시각,
local_incident_id를 저장한다. `RECOVERED`는 가전 action이 없어도 기록되며 평가 기록에도 `fall_decision`이 남는다.
전달 상태는 `fall_state_contract_unconfirmed`, 백엔드 사건 상태는 미확인(null)으로 분리한다.
AI RECOVERED로 사건 latch를 지우거나 신고 절차 중단을 요청하지 않는다. 이력은 재시작 후에도 보존한다.
낙상 신호가 있으면 미해결 사건을 local_incident_id로 디스크에 고정한다.
같은 잔여 신호나 재시작으로 새로운 시작 요청을 만들지 않는다.
종료 API가 없으므로 움직임만으로 이 사건을 닫거나 신고 취소를 주장하지 않는다.
종료 동기화 전에는 복구·출수 등 새 자동 송신도 보수적으로 보류한다.

향후 시작 계약이 확정되면 이 사건의 decisionId와 응답 fallIncidentId를 연결해야 한다.
현재 nullable 필드는 미연동임을 표시한다. 백엔드의 “괜찮음”을 학습 positive로 변환하지 않는다.
응답 feedback=null도 FeedbackManager에 전달하지 않는다. 기존 자연어 피드백 경로는 그대로다.

## 검증 범위와 실전 연결 전 합의

최초 용어 계약 수정 전 기준은 266 passed, 이번 후속 설명 반영 전은 293 passed였다.
`tests/test_backend_contract.py`는 표준 구역·기기,
기기 상태 보존, room 취침·전등 연결, 이전 source의 동일 본문 재시도, README 전체 JSON 일치를 검증한다.
로컬 HTTP 테스트 서버로 실제 urllib GET/POST 경로와 202/200 duplicate, sent/rejected/failed도 확인한다.
이 로컬 HTTP 서버는 Mock이며 배포된 실제 백엔드 검증이 아니다. 기존 테스트의
입력 유효성/중복·지연/outbox/재시작/부재·낙상/Mock 요청·응답 검증도 유지한다.
LLM factory는 선택한 adapter만 import하도록 수정해 LLM=none에서 torch 등이 필요하지 않다.
날씨는 백엔드 응답을 보관하며 stale 문구를 지우지 않는다. 날씨 자체를 조회하거나 추정하지 않는다.
TTS의 로컬 WAV 경로를 음성 전송 계약으로 사용하지 않는다.

실제 백엔드·MQTT·가전·LG OS·Docker 보드 실행은 검증하지 않았다. 새 FastAPI 서버나
MongoDB/MQTT/LG SDK 코드를 추가하지 않았다. 다음 계약이 필요하다.

1. control_state와 명령 실행 이력/사용자 변경의 의미, 부재 차단 후 재가동 정책.
2. temperature는 °C인가? level의 단위/범위 및 별도 W 측정 제공 여부, updatedAt·online 갱신 기준은 무엇인가?
3. 사용자 상태와 별개로 실제 출수 준비를 확인할 기기 필드/조건은 무엇인가? idle은 준비 조건에서 제외했다.
4. confidence 계약은 후속 합의 반영 완료: 계산값 보존, 점수 없는 규칙만 null. 추가 점수 규칙은 필요 없다.
5. 출수 외 scenario/action 허용값과 필수 필드, 실제 기기별 room 매핑 및 toilet 경고등 정책은 무엇인가?
6. AI 낙상 시작·RECOVERED 전달 필드와 사용자 확인·사건 처리 상태 동기화 형식, 미해결 사건 해제 조건.
7. commandId 실행 ACK 및 부분 실패 재처리·전송 후 취소 계약.
8. 피드백 스키마/전달 경로, 인증 방식과 확인된 base URL.
9. 센싱 조회 방식, empty의 의미, 전환 확인 구간, 별도 행동 데이터의 측정/만료 계약.

모든 명령은 기본 mock 저장소를 사용하며 live outbox 경로와 DB 모드 표식을 분리한다.
설정 변경만으로 Mock 명령을 live에서 읽지 않는다. `.env.example`은 예시이고
실제 인증 정보는 `IntegrationConfig.headers`에 외부에서 주입한다.

### 후속 설명 반영 검증 (2026-10-17)

- 전체 pytest: 301 passed (76.30초). 기존 293개와 신규 8개를 포함한다.
- `python -m unittest discover -s tests -q`: 106 tests, OK (23.703초).
- 신규 `tests/test_contract_clarifications.py`: 계산된 confidence·판단 이력·weight 보존, 규칙만 null,
  전체 기기 단일 조회, 사용자 idle/sitting/lying 갱신과 기기 원본 분리, 반복 조회의 updatedAt 보존을 검증한다.
- 기존 낙상 상태의 0/5/10/30초 전이와 5초 움직임 후 RECOVERED를 실제 런타임으로 확인했다.
  AI 회복 기록은 재시작 후에도 남고 백엔드 사건 종료로 취급되지 않으며, 중복 후속 대응 POST는 없다.
- 위치 전용 데모: GET 5회/POST 0건. 가상 행동·별도 가상 준비 신호 데모: GET 5회/120mL POST 1건 Mock 접수.
  `weatherBriefing=true`, `execution_ack_not_provided`를 유지한다. 실제 서버·실가전 검증은 아니다.
- README 전체 요청·응답 비교, 로컬 HTTP 계약 테스트, 기존 재시도·중복·회귀 테스트도 통과했다.

### 이전 계약 수정 검증 (2026-10-17, 후속 설명 반영 전)

Windows / Anaconda Python에서 실행했다. 테스트 개수는 서로 중복되는 실행 범위이며 합산하지 않는다.

| 실행 | 결과 |
| --- | --- |
| 변경 전 `python -m pytest -q` | 266 passed |
| 변경 후 `python -m pytest -q` | 293 passed (102.01초) |
| `python -m pytest -q tests/test_backend_contract.py` | 27 passed (3.19초) |
| `python -m unittest discover -s tests -v` | 106 tests, OK (46.048초) |
| 위치 전용 데모 | GET 5회, POST 0건, 행동 입력 부족 표시 |
| 별도 가상 행동 데모 | GET 5회, 120mL POST 1건 Mock 접수, `execution_ack_not_provided` |

로컬 HTTP 테스트는 실제 클라이언트의 직렬화·고정 경로·202 및 200 중복 응답·동작 상태를 확인한다.
당시에는 Mock에서 idle을 준비 상태로 가정하고 nullable confidence를 제한했다.
이후 사용자 설명으로 두 해석을 수정했다: idle 준비 해석은 제거하고 규칙 confidence=null은 기본 정책으로 적용했다.
실제 백엔드 서버 모델/OpenAPI·접속 URL·인증 정보가 없어 배포 서버 연동이나 실가전 실행은 검증하지 않았다.
기존 판단 시간, confidence 가중치·임계값, 피드백 알고리즘 및 120mL 출수 정책은 변경하지 않았다.

### 과거 검증 기록: 3726303 기준 런타임 회귀 수정

아래 두 절은 당시 실행 기록이다. 테스트 개수·소요 시간·180mL 데모 결과는 당시 설정에 대한
기록이며 현재 기본값이나 최신 실행 결과를 뜻하지 않는다. 현재 대표 데모의 기본 출수량은 120mL다.

수정 전 전체 기준은 `168 passed`였다. 먼저 실제 `IntegrationRuntime`을 사용하는 핵심 회귀 테스트
3개를 추가했으며 모두 예상대로 실패했다. 취침은 `user_returned_to_light_room`으로 차단됐고,
2초 지연에서 조명 및 기상 출수 요청은 생성되지 않았다. 수정 후 이 경로들은 Mock 접수까지 검증한다.

추가 테스트 파일은 다음 명령으로 실행한다.

```powershell
python -m pytest -q tests/test_runtime_regressions.py
```

92f7030 수정 당시 실제 실행 결과(Anaconda Python, LLM/GPU 없이):

- `python -m pytest -q tests/test_runtime_regressions.py`: 53 passed.
- `python -m pytest -q`: 221 passed (55.79초).
- `python -m unittest discover -s tests -v`: 104 tests, OK (30.525초).
  unittest는 기존 unittest 클래스들을 실행하며 pytest 함수형 회귀 테스트는 위 pytest 명령에서 검증한다.
- `python -m examples.backend_integration_demo`: 조회 5회, POST 0건, 행동 입력 부족 명시.
- `python -m examples.backend_integration_demo --with-mock-behavior`: 조회 5회, POST 1건,
  180ml / `weatherBriefing=true` 요청의 Mock 접수. 응답 진단은 `execution_ack_not_provided`다.

FakeClock·MockBackend·임시 저장소에서 기기 polling 2초 / 센싱·advance 1초 / 정렬 지연 2초를 재현한다.
기본 지연을 0으로 바꾸지 않고 조명·출수, 동일 시각 입력 순서 반전, 여러 시각의 일괄 처리,
미래 상태 대체 금지, 과거 offline, 최신 오류 차단/새 측정에 의한 회복, 반복·지연·충돌·시계 역행을 검증한다.
취침은 적용된 행동의 유효기간이 송신 시점보다 짧아도 최신의 실제 관측이 계속되면 접수되는지,
반대 관측/공백 후 과거 요청이 재사용되지 않는지, 재검증이 엔진/출력 큐를 바꾸지 않는지 확인한다.
`allowed_lateness=0`과 기존 outbox 저장 실패·동일 ID/본문 재시도·TTL·재시작 예약 테스트도 유지한다.

성공 테스트의 `room_is_bedroom=True`, `water_ready_states=("idle",)`,
`rule_confidence_policy="null"`, `mock_sleep/mock_absence/mock_presence` 라우트는 **Mock 전용 가정**이다.
취침 임계시간 6초 및 가상 `BehaviorObservation`도 테스트에만 사용한다. 운영 기본값·confidence 계산식·
가중치·시나리오 임계값·출수량 결정 방식·API 계약은 변경하지 않았다.

버그 수정은 실전 활성화와 다르다. 빈 action_routes, 규칙 confidence 표현, 정수기 준비 상태 의미,
level↔W 대응, 자동 복구 제어 이력, 낙상 시작/확인/종료 API, 실제 행동 데이터 수신·유효기간 계약은
여전히 합의/구현이 필요하다. yes/no 피드백 연동은 이번 범위가 아니며 기존 FeedbackManager,
WeightManager와 자연어 피드백 경로는 그대로다. Mock의 접수/sent는 실제 가전 실행 완료가 아니다.

### 과거 검증 기록: 92f7030 이후 공백 뒤 위치·행동 시각차 회귀

README 커밋 5ab1f42가 포함된 깨끗한 로컬 main에서 작업을 시작했다.
변경 전 전체 pytest를 다시 실행하여 `221 passed`(78.47초)를 확인했다.
실제 `IntegrationRuntime` / `CentralController` / `BedtimeLightScenario`와 FakeClock,
MockBackend, 임시 outbox로 재현했으며, 부분 메서드를 복사한 별도 구현을 사용하지 않았다.

핵심 테스트는 T+0~8의 첫 누움 구간과 미전송 요청을 만들고, T+9~19 동안 센싱을 중단한다.
그동안 기기 polling과 advance는 계속하여 이전 행동을 만료시킨다.
T+20부터 행동의 측정 시각을 `위치 시각-skew`, 만료를 `행동 시각+3초`로 공급한다.
수정 전 skew=0은 통과했고, 0.5와 1초는 정상 생성된 새 요청이
`bedtime_observation_interrupted`로 차단되어 실패했다.

테스트용 `BEDTIME_LYING_SECONDS=6`, 명시적인 침실/조명 라우트와 nullable 규칙 confidence를 사용한다.
실제 운영 기본값은 변경하지 않는다. 새 요청은 시나리오/tick의 기존 시간 계산을 따르며,
이전 요청의 차단을 명령 TTL 만료 전에도 별도로 확인한다.
반복 송신은 새 요청 한 건만 접수하고, 응답 유실 뒤 재시도는 동일 본문/ID를 사용함을 검사한다.

추가 경계 검증은 연속 관측의 skew 0·0.5·1초, 허용 범위 초과·미래·만료 행동,
새 구간 중 반대/누락/무효 관측과 재누움, 두 번째 공백, 역순 도착, 이전/현재 구간의 늦은 반대 관측,
중복·충돌, 맞닿은 유효기간, 재시작, 지연 0초, 반복 재검증의 무변경을 포함한다.
기존 53개 런타임 회귀 테스트도 유지하여 재실 중 취침 소등, 시간순 기기 캐시, 일반 조명 검사를 함께 실행한다.

핵심 회귀 테스트의 실제 실행 결과:

| 행동이 위치보다 앞선 시간 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 0초 | 통과 | 새 구간 요청만 Mock 접수 |
| 0.5초 | `bedtime_observation_interrupted`로 실패 | 새 구간 요청만 Mock 접수 |
| 1초 | `bedtime_observation_interrupted`로 실패 | 새 구간 요청만 Mock 접수 |

이번 변경 후 아래 명령을 다시 실행했다(Anaconda Python, LLM/GPU 없이).

- `python -m pytest -q tests/test_runtime_regressions.py`: **86 passed** (40.18초).
- `python -m pytest -q`: **254 passed** (84.31초).
- `python -m unittest discover -s tests -v`: **104 tests, OK** (37.057초).
- `python -m examples.backend_integration_demo`: 조회 5회, POST 0건, 행동 입력 부족 표시.
- `python -m examples.backend_integration_demo --with-mock-behavior`: 조회 5회, POST 1건,
  180ml / `weatherBriefing=true` 요청 Mock 접수, `execution_ack_not_provided` 유지.

새 테스트는 기존 `tests/test_runtime_regressions.py`에 추가했다. 기존 테스트 실패는 없었다.
Mock 접수는 실제 소등·출수 실행을 확인한 결과가 아니다. 위의 실전 연결 전 계약 목록과
별도 행동 데이터 수신 방식, yes/no 피드백·낙상 API·자동 복구의 미구현/차단 상태는 그대로다.
