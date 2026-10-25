# Wi-Fi 행동 연동 · 화장실 낙상 의심 · 아침 방 전등

## 확인 범위와 실행

2026-10-26 원격 확인: 팀/개인 `HomeVIS-AI_main/main` 32153ec,
`HomeVIS-AI_Wifi/main` f73c0ff, `HomeVIS-Backend/develop` fb22929 (AI 명세 v0.7).
Wi-Fi 저장소에는 아직 행동 이벤트 생산자가 없고, `HomeVIS-EM_Wifi-RPI`는 접근 가능한 팀 저장소에서
확인되지 않았습니다. 수집 안내의 입력 200이나 CSV 550→500 절차를 추론 JSON 계약으로 해석하지 않습니다.

```sh
python -m pip install -r requirements-runtime.txt
python -m src.integration --sensing-source backend --base-url http://백엔드IP:8000
```

기본 설정도 backend HTTP 모드입니다. 기존 `.env`의 `HOMEVIS_SENSING_SOURCE`가 mqtt면 backend로 바꾸세요.
센싱 GET은 기본 1초, 기기 GET은 2초이며 판단은 기존 `POST /api/v1/ai/decisions`로만 전송합니다.
AI는 raw CSI 재처리/학습이나 기기 MQTT command 발행을 하지 않습니다. 백엔드·센싱 추론기는 별도 실행되어야 합니다.

## 실제로 확인된 필드와 아직 모르는 것

| 경계 | 확인된 계약 |
| --- | --- |
| Wi-Fi 최종 위치 | `wifi/occupancy/state`: `time`, `location`, `location_confidence`, 선택적 진단 `reason` |
| 백엔드 최종 결과 | `home/edge/result` 저장 후 GET `/api/v1/sensing/results?since=...&limit=5000` |
| 백엔드 공통 필드 | `resultId`, `observedAt`, `room`, `present`, `confidence`, `activity`, `activityConfidence`, `validSec`, `modelVersion`; 서버 `savedAt` |
| 기존 내부 행동 어댑터 | `activity`, `motion_state`, `fall_detected` 및 유효 시각·confidence. 후자의 두 필드는 백엔드의 공식 필수 필드가 아닌 기존 확장 입력 |
| 사용자 제공 학습 로그에서 확인 | 행동 클래스 `none`, `fall`, `lie_down`, `get_up` |
| 미확정 | 실제 행동 생산자의 JSON, 이벤트 ID, 독립 측정 시각, 정상 설명·진단·오류 필드, 실제 움직임 제공 여부 |

백엔드가 임의 추가 필드를 저장한다고 해서 해당 필드의 의미까지 검증된 것은 아닙니다.
현재 Wi-Fi 특징 토픽과 백엔드의 `home/{room}/edge/{node}/features`·`home/edge/combined`는 서로 다릅니다.
노드 매핑도 Wi-Fi r2=주방/r3=방/r4=화장실, 백엔드 문서 r1=방/r2=주방/r3=화장실로 달라 확인이 필요합니다.
이 변경은 다른 저장소의 통신 코드를 고치지 않습니다. 실제 백엔드에 결과가 저장되어야 GET이 유효한 데이터를 반환합니다.

위치의 unknown/empty는 유효한 화장실 또는 outside로 바꾸지 않습니다. 기본 어댑터는 확인되지 않은 행동 문자열을
이벤트로 변환하지 않고 `unverified_activity_label`로 보류합니다. 허용 자세 상태는 기존
unknown/lying/sitting/standing/walking이며, 이벤트와 별개입니다.

## 확정된 행동 클래스와 연결

| 학습 클래스 (`activity`) | 내부 처리 | 만들지 않는 정보 |
| --- | --- | --- |
| `none` | 유효한 분류 결과지만 대상 이벤트 없음 | 외출, 빈집, still, 낙상 회복 |
| `fall` | 명시적 `fall` 이벤트 → 기존 화장실 낙상 경로 | 지속 자세, 움직임 없음 |
| `lie_down` | `lie_down` 이벤트 → 화장실에서는 로컬 의심 후보 | 지속 `lying`, 취침 확정 |
| `get_up` | 내부 `wake` 이벤트 → 조건 충족 시 아침 방 전등 | 지속 `standing`이나 5초 자세 관측 |

`dataset/empty`는 none 학습에 사용한 파일 출처이지 행동 `none`과 재실 `empty`가 같은 뜻이라는 의미가 아닙니다.
분류기의 네 클래스에는 실제 자세 상태·moving/still이 없습니다. 따라서 이 정보만으로
취침 소등의 lying 600초 또는 눕기 후 still 5초를 만들어내지 않습니다.

아래는 **기존 백엔드 필드에 맞춘 연동 예시**이며, Wi-Fi 생산자에게서 수신한 실제 패킷은 아닙니다.
Mock 옵션 없이 사용할 수 있고 원본 라벨·각 신뢰도를 보존합니다. 생산자가 다른 필드를 사용한다면 경계 어댑터를 맞춰야 합니다.

```json
{
  "resultId": "example-result-1",
  "observedAt": "2026-10-26T07:00:00+09:00",
  "room": "room",
  "present": true,
  "confidence": 0.96,
  "activity": "get_up",
  "activityConfidence": 0.95,
  "validSec": 10
}
```

공통 `observedAt/room/validSec`이 위치와 행동에 모두 적용되는 결과라는 전제입니다.
행동 측정 시각이 위치와 다르면 기존 별도 `BehaviorObservation` 결합 경로로 실제 시각을 전달해야 합니다.
`validSec: 10`은 예시이지 자동 기본값이 아닙니다. 누락된 유효기간/행동 신뢰도는 채우지 않습니다.
독립 JSON 샘플을 받은 후 공통 시각 사용 가능 여부를 확인해야 합니다.

이벤트 생산자 ID가 미확정인 동안에는 구역+측정 시각에서 결정적인 `behavior-window:` ID를 만듭니다.
이는 물리적 사건 ID가 아닌 **동일 관측 창의 재전송 중복 제거용**입니다. 수신 시각/DB resultId/클래스/신뢰도가 바뀌어도
같은 구역·측정 시각의 ID는 같으므로 반복 GET이 이벤트를 갱신하지 못합니다. 서로 다른 겹친 창을 한 사건으로 묶는 것은
이 ID의 역할이 아니며 기존 낙상 사건 latch와 하루 전등/출수 제한이 중복 제어를 막습니다.

## 학습 로그를 해석할 때의 제한

사용자 제공 로그: `fda1298c`, 전처리 20Hz, 6초 창, 31개 특성, 수신 속도 중앙값 25Hz.
온도 보정 T=1.40과 SVM은 Wi-Fi 쪽 책임입니다. AI에서는 보정된 신뢰도를 다시 보정하거나 모델을 로드하지 않습니다.

- file 단위 교차검증의 전체 정확도 92.6%는 none이 2,855/3,288개인 불균형에 영향을 받습니다. 보고된 macro F1은 0.643입니다.
- 임계값 적용 후 파일별 이벤트 감지는 fall 6/14(43%), lie_down 3/22(14%), get_up 5/24(21%)입니다.
- 학습 출력 θ는 fall 0.58 / lie_down 0.90 / get_up 0.90입니다. 뒤 두 값은 정밀도 90%를 만족하는 값이 없어 둔 대체값이지 성능 보장이 아닙니다.
- 창 기준 오탐 약 3.2회/시간이며 걷기·뛰기·앉기 같은 오탐 유발 동작이 평가에 없었습니다. 실제 배치 성능을 보장하지 않습니다.
- 중앙의 기존 명시적 낙상 최소 신뢰도(0.6), 보조 눕기 후보 기준(각 0.8)을 자동으로 θ=0.58로 낮추지 않습니다.
  새 기상 이벤트 정책의 기본 0.9도 중앙 정책값이며 설정으로 바꿀 수 있습니다.

6초는 모델 입력 창 길이지 결과 유효기간이나 기상 확인 시간, still 관측 시간이 아닙니다.
`observedAt`이 창 시작/끝 중 어느 것인지와 발행 지연을 확인해야 합니다. 실행기의 기본 lateness 4초,
독립 위치/행동 결합 오차 1초를 이 로그만 보고 바꾸지 않았습니다. 오래된 결과는 새 관측으로 되살리지 않습니다.
`behavior_svm.pkl`/`behavior_config.json` 배치와 scikit-learn 버전 일치는 Wi-Fi 담당 서버/노드에서 관리합니다.

## 정규화와 이유 처리

`SensingUpdate`에 내부 `activity_event`, `activity_event_id`, `location_reason`, `activity_reason`,
`raw_activity`, `received_at`을 추가했습니다. `BehaviorObservation`과 `join_behavior()`를 그대로 사용합니다.
위치와 행동 confidence는 따로 보존하며, 기존 규칙의 출력 confidence 정책만 두 관측 중 최솟값을 사용합니다.
가중치 계산·FeedbackManager/WeightManager를 바꾸지 않았습니다.

측정/수신 시각, confidence 범위, 공간 일치, 기본 1초 이내 시각차, 유효기간을 검사합니다.
수신 전에 만료된 행동은 시각 등의 감사 정보만 보존하고 관측으로 사용하지 않습니다.
이벤트 ID는 SQLite `behavior_events`로 중복 제거하며, 같은 ID의 내용 변경도 새 사건으로 해석하지 않습니다.
프로세스 재시작 후에도 이벤트 ID는 보존합니다. 동일 이벤트를 재전송할 때 측정 시각·만료를 갱신하면 안 됩니다.

기존 `reason`은 아직 진단 사유로 취급합니다. `node_offline`, `config_mismatch` 및 알려지지 않은 사유를
설명이라고 무조건 허용하지 않습니다. 정상 설명은 내부 `location_explanation` / `BehaviorObservation.explanation`과
분리했지만, 실제 백엔드의 정상 설명 필드 매핑은 샘플 확인 후 추가해야 합니다. 원본 JSON은 audit에 남습니다.

## 화장실 낙상 정책

| 증거 | 로컬 처리 | 백엔드 전송 |
| --- | --- | --- |
| 유효한 명시적 낙상 | 기존 FALL_SUSPECTED 및 후속 단계 | 기존 `fall_detected` 경로 유지 |
| 실제 standing/walking → lying 자세 전이 | 기존 전이 정책 유지 | 기존 경로 유지 |
| 화장실 눕기 이벤트 또는 lying 관측, 양쪽 confidence 각각 ≥0.8 | FALL_SUSPECTED, `candidate_only=true`, 사건 ID 없음 | 전송하지 않음 |
| 눕기 후보 + 유효한 별개의 still 관측이 5초 구간을 채움 | FALL_CONFIRMED, 사건 생성 | 기존 `fall_detected`, `actions=[]` |
| 눕기 반복 또는 이후 무응답 | 후보 유지/센싱 불확실, 확인 시간 증가 금지 | 전송하지 않음 |
| 실제 moving 관측이 회복 확인 시간(기본 5초)을 채움 | 기존 RECOVERED 처리 | 기존 백엔드 사건을 임의 종료하지 않음 |

추가 still 증거의 confidence도 두 기준을 충족해야 합니다. 중간 미관측·만료·오류·낮은 confidence는 확인 구간을
끊으며, 만료된 후보 뒤의 still만으로 과거 눕기를 계속 사용하지 않습니다. 새 눕기 근거나 명시적 낙상이 필요합니다.
`fall_detected=false`만으로 후보를 안전 확정하지 않습니다. lying과 true 낙상이 함께 있으면 명시적 낙상 경로를 사용합니다.
눕기 이벤트가 자세 상태를 만들어내지 않으며, 이벤트만 있었던 경우 실제 자세 전이로 승격하지 않습니다.
방/주방/unknown/empty의 눕기로 낙상 대응을 시작하지 않습니다. 화장실 밖 명시적 낙상도 이번 변경에서 확대하지 않습니다.

후보는 SQLite 사건 latch, 긴급 제어, 사용자·보호자 문자, 신고를 시작하지 않습니다. 후보를 위한 새 HTTP scenario도 없습니다.
실제 사건 이후의 SMS·대기 타이머·기기 차단·깜빡임·종료는 기존 백엔드 책임입니다.
백엔드가 안전 종료를 확인한 **이후**의 새 `none` 관측은 이전 낙상 출력의 재발 방지 잠금만 해제하여 다음 낙상을 받을 수 있게 합니다.
종료 전의 none으로 사건을 끝내거나, 물리적 회복 상태를 만들어내지는 않습니다.
실제 119 연동은 확인한 백엔드에서 미구현이며 이 작업으로 구현되지 않습니다.

판단 근거는 기존 `fall_state_changed`/`evaluation`/`location_received` audit, DecisionHistory와 outbox source에 저장됩니다.
시각, 위치/행동 신뢰도·설명, 이벤트 ID, 직접 낙상 여부, 실제 motion, 후보 최초 근거, 확인 시간, 상태를 보존합니다.
백엔드 사건 ID·응답·전송 상태는 기존 outbox의 사건/판단 기록과 연결합니다. 없는 움직임이나 신고 완료를 생성하지 않습니다.

## 아침 방 전등과 기존 시나리오

MorningWaterScenario에서 방의 유효한 `get_up` 이벤트(행동 신뢰도 기본 ≥0.9)를 기상으로 받습니다.
기존 방 lying → sitting/standing/walking 확인(기본 5초) 경로도 유지합니다.
두 경로 모두 기상이 기존 아침 허용 시간대에 들어오면 `morning_light_on` 내부 요청을 만듭니다.
백엔드에는 이미 사용하는 `scenario=light_auto_on`, `device=light`, `action=on`, 설정된 방 전등 ID를 보냅니다.
기본 시간대는 06:00~10:00이고 기존 기상 패턴이 충분히 쌓이면 기존 학습 시간대를 재사용합니다.

확정 라벨 `get_up`은 자세를 만들어내지 않고 이벤트 자체로 기상을 처리합니다. 기존 합성 `mock_wake` 테스트 경로는
여전히 유효기간 내 실제 후속 자세를 5초 확인해야 합니다. 눕기 이벤트만으로 SLEEPING이나 lying 상태를 만들지 않습니다.
전등 요청은 출수와 독립적입니다. 정수기는 여전히 주방 체류, 시간대, 준비 상태, 하루 횟수를 검사합니다.
`get_up` 단독으로 출수하지 않으며, 이후 유효한 주방 위치/행동 결과(`none` 가능)가 5초 체류를 확인해야 합니다.
취침 소등의 연속 lying 600초는 변경하지 않았습니다. 실제 지속 자세가 없으면 자동 소등은 보류됩니다.

전송 직전에 현재 방 위치, 유효한 기상 근거, 온라인·최신 전등 상태, 취침 소등 우선권, 미해결 낙상을 다시 검사합니다.
이벤트 기반 전등 요청은 최초 기상 관측의 만료 시각까지만 유효합니다. 후속 none은 만료를 연장하지 않으며,
새 눕기/낙상·방 이탈·오류·만료로 오래된 요청을 승인하지 않습니다.
정렬 대기 중 들어온 방 이탈·눕기·오류도 수신 시각에 기록하므로, 그 뒤 none이 와서 최신 값만 바뀌어도
앞선 기상 요청을 다시 승인하지 않습니다.
켜진 전등에는 중복 요청하지 않으며 진행 중인 일반 자동 켜기와 겹치면 추가 요청을 보류합니다.
기상 전등 예약 날짜는 SQLite에 보존해 같은 날 재시작으로 재발행하지 않습니다.
일반 위치 기반 전등 켜기/끄기는 기존대로 따로 동작합니다.

## 설정

`config/homevis.toml`의 `[scenarios]`는 기존 ScenarioConfig로 전달됩니다.

```toml
[scenarios]
toilet_lying_suspicion_enabled = true
toilet_lying_min_location_confidence = 0.8
toilet_lying_min_activity_confidence = 0.8
fall_confirm_seconds = 5.0
morning_light_enabled = true
wake_event_min_activity_confidence = 0.9
```

0.8은 새 보조 후보의 정책 기본값이지 검증된 사고 확률이 아닙니다. 실제 환경에서 오탐/누락을 검증해야 합니다.
기존 FALL_CONFIRM/WARNING/EMERGENCY 시간의 증가 관계 검증을 유지합니다. 행동 유효기간은 생산자가 제공하며
누락된 validSec을 AI가 임의로 채우지 않습니다. 새 가중합이나 피드백 학습은 추가하지 않았습니다.

## Mock 전용 예시 — 실제 운영 계약 아님

아래는 테스트에서만 쓰는 가상 형식입니다. `mode=mock`과 `[backend] mock_behavior_contract=true`가 모두 필요합니다.
live에서 이 옵션을 켜면 시작 시 오류가 나며, 기본 어댑터는 아래 payload를 거부합니다.
`mock_lie/mock_wake/mock_fall`은 각각 내부 lie_down/wake/fall 이벤트로 변환할 테스트 라벨입니다.
합성 라벨은 테스트 전용이며 확정된 실제 학습 클래스와 별개입니다. 실제 기상 라벨은 `get_up`이지 `wake_up`이 아닙니다.

```json
{
  "mockContract": "homevis.behavior.v1",
  "resultId": "mock-result-1",
  "observedAt": "2026-10-26T07:00:00+09:00",
  "room": "toilet",
  "present": true,
  "confidence": 0.96,
  "validSec": 10,
  "locationExplanation": "화장실 구역 특징이 가장 강함",
  "locationValid": true,
  "mockBehavior": {
    "eventId": "mock-event-1",
    "time": "2026-10-26T07:00:00+09:00",
    "valid_until": "2026-10-26T07:00:10+09:00",
    "location": "toilet",
    "label": "mock_lie",
    "confidence": 0.92,
    "reason": "눕기로 분류됨",
    "valid": true
  }
}
```

Mock 오류는 `locationError` 또는 `mockBehavior.error`로 구분합니다. 이벤트와 별개로 실제 관측한 경우에만
`mockBehavior.activity/motion_state/fall_detected`를 추가합니다. 위 예시에는 still이나 lying 자세 관측이 없습니다.
위치를 갱신하면서 같은 이벤트를 재전달할 때 내부 행동의 원래 time/valid_until/eventId는 유지합니다.
이 형식을 운영 백엔드에 보내거나 실가전을 연결하지 마세요.

## 변경 지점과 검증

- `control/realtime_models.py`, `integration/sensing.py`: 내부 이벤트·설명·시각 보존 및 결합 검사.
- `integration/behavior_labels.py`, `backend_sensing.py`, `mqtt_source.py`: 확인된 네 클래스 정규화, 미확정 라벨 보류, 별도 Mock 어댑터.
- `control/bathroom_fall.py`, `scenario_models.py`, `scenario_config.py`: 후보 부작용 분리·추가 증거·근거 기록.
- `control/morning_water.py`, `central_controller.py`: 기존 기상 확인을 공유하는 방 전등 요청.
- `integration/runtime.py`, `outbox.py`: 후보/사건 구분, 영속 이벤트 중복 제거, 기존 이력 저장, 송신 전 재검증.
- `integration/config.py`, `settings.py`, `config/homevis.toml`, `.env.example`: HTTP 기본값·시나리오 설정.
- `tests/test_wifi_behavior.py`: 독립 confidence/설명, 오류, 미확정 라벨, 후보/확정, 시간/중복/만료/회복/재시작,
  백엔드 계약과 기상 전등·출수/취침 보호. 기존 테스트도 함께 실행합니다.

```sh
python -m pytest -q tests/test_wifi_behavior.py
python -m pytest -q
python -m src.integration --env-file .env.example --check-config
python -m src.integration --env-file .env.example --mode mock --duration 5
```

실제 API·실가전·Wi-Fi 모델 시험은 포함하지 않습니다. 기존 음성 작업의 미커밋 변경은 보존했으며,
이번 작업에 공기청정기·외출 전체 OFF·STT·TTS·새 음성 기능 개발은 포함하지 않았습니다.

Wi-Fi 팀에서 다음을 받아야 운영 이벤트 어댑터를 확정할 수 있습니다:
확정 라벨을 담은 실제 JSON 샘플, 측정 구간과 발행 지연, stable event ID, 유효기간,
위치/행동 각자의 설명·오류 필드, 움직임 관측 제공 여부, 노드/구역 매핑 및 백엔드 저장 경로.

### 이번 검증 결과 (2026-10-26)

- Windows / Python 3.13.5, 준비된 SDK·MQTT 테스트 의존성과 로컬 백엔드 참조 저장소 사용.
- 최종 전체 pytest: **641 passed, 2 skipped**. 건너뛴 두 테스트는 명시적으로 켜야 하는 실제 EXAONE/GPT 과금 API 호출.
- 행동/낙상/기상 전등 테스트 100개 포함(이전 65개 + 확정 클래스·기상 이벤트 경로 35개).
  백엔드 v0.7의 실제 Pydantic 스키마로 낙상·기상 전등 요청을 오프라인 검증.
- `--check-config`: live/backend 설정 확인. 3초 Mock 연속 실행의 시작·정상 종료 확인.
- `git diff --check`: 통과. 실제 Wi-Fi 하드웨어·가전·운영 API를 호출한 검증은 아님.
