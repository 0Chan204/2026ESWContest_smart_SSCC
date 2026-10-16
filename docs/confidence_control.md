# Confidence 기반 자동 제어

기존 `CentralController.evaluate()` 단건 API, 실시간 위험 상태, 아침 출수, 욕실 낙상,
LLM/TTS 연결은 유지한다. 새 자동 기기 제어는 다음 흐름을 사용한다.

```text
SensingUpdate + ApplianceUpdate
  → FeatureExtractor
  → ConfidenceEngine
  → scenario threshold
  → AutomationAction
  → FeedbackManager
  → 사용자·시나리오별 weight 갱신
```

시간 임계값은 위치 후보 확인과 긴급 안전 상태를 위한 guard/state tracking에 남아 있다.
`reduce_power`, `restore_power`, `turn_on`, `turn_off` 명령 자체는 단일 시간 조건이 아니라
여러 feature의 가중 합이 scenario threshold 이상일 때만 생성된다.

## 설정

`src/control/confidence/config.py`의 `ConfidenceConfig`에서 초기 weight, scenario threshold,
medium threshold, learning rate, weight 최소/최대, 각 feature 정규화 기준을 변경한다.

| scenario | threshold | features |
| --- | ---: | --- |
| kitchen_leave_reduce_power | 0.82 | location, duration, stove_power, outside_home, consistency, activity, previous_action, feedback |
| kitchen_return_restore | 0.80 | location, return_duration, consistency, stove_state, control_state, feedback |
| light_auto_on | 0.72 | location, presence_duration, consistency, activity, feedback |
| light_auto_off | 0.78 | location, leave_duration, consistency, activity, feedback |
| bathroom_fall_alert | 0.90 | fall_signal, still_duration, location, consistency, feedback |

욕실 낙상은 생명 안전 시나리오이므로 현재의 검증된 상태 머신과 LLM/TTS 경로를 유지한다.
`bathroom_fall_alert` 설정은 향후 기존 경고를 대체하지 않고 보조 점수를 붙일 수 있도록 예약했다.

confidence는 모든 feature를 0~1로 제한한 뒤 다음처럼 계산한다.

```text
contribution(feature) = feature_score × scenario_weight
confidence = clamp(sum(contributions), 0, 1)
```

high threshold 이상은 `execute`, medium 이상은 `wait_for_more_evidence`, 그 미만은
`do_nothing`이다. 화구 OFF, stale 기기 상태, 이미 감소한 화력, `USER_OVERRIDE`는 점수와
무관하게 실행을 막는 hard guard다.

## 백엔드 입력과 출력

기존 `SensingUpdate.confidence`는 위치 confidence로 사용한다. 선택적인
`activity_confidence`를 추가했으며, 없으면 위치 confidence를 재사용한다.
`ApplianceUpdate.power_watts`와 선택적인 `control_state`를 전달한다.

`control_state` 값은 `NONE`, `HOMEVIS_REDUCED`, `USER_OVERRIDE` 중 하나다. 백엔드는
HomeVIS가 화력을 낮춘 뒤 원래 화력 수치를 보관해야 한다. AI 모듈은 복귀 시 수치 없이
`restore_power`만 보낸다.

```python
actions = controller.drain_automation_actions()
for action in actions:
    payload = action.to_dict()
```

```json
{
  "action_id": "...",
  "timestamp": 0,
  "scenario": "kitchen_leave_reduce_power",
  "confidence": 0.84,
  "device": "stove",
  "action": "reduce_power",
  "reason": {"location": 0.95, "duration": 1.0}
}
```

전등은 현재 전등 상태가 기존 센싱 모델에 없으므로 명시적인 API를 사용한다.

```python
decision = controller.evaluate_light(LightContext(
    room="bedroom",
    light_on=True,
    user_present=False,
    timestamp=30,
    absence_duration=30,
    location_confidence=0.95,
    activity_confidence=0.9,
    sensor_consistency=0.95,
))
```

## 피드백과 저장

지원 값은 `positive`, `unnecessary`, `too_sensitive`, `too_late`, `cancel`,
`user_override`다.

```python
result = controller.apply_feedback(action_id, "unnecessary")
```

`positive`, `too_late`는 당시 contribution에 비례해 weight를 높이고 나머지는 낮춘다.
변화량은 `learning_rate × contribution`이며 이후 모든 weight를 `[MIN_WEIGHT, MAX_WEIGHT]`
범위에 고정하고 합이 1이 되도록 정규화한다. 안전 guard는 피드백으로 바뀌지 않는다.

기본 저장 디렉터리는 `output/confidence/`다.

- `user_weights.json`: 사용자·scenario별 조정 weight
- `decision_history.jsonl`: feature, weight, contribution, confidence, action 전체 이력
- `feedback.jsonl`: 피드백과 변경 전후 weight
- `routines.jsonl`: timestamp, location, activity, device, action, confidence

다른 위치가 필요하면 `CentralController(confidence_data_dir=...)`로 지정한다. 저장 클래스가
분리되어 있어 이후 DB 구현으로 교체할 수 있다.

## 자연어 피드백

자연어 피드백은 기존 학습 로직 앞에 해석 계층만 추가한다.

```text
action_id → DecisionHistoryStorage 조회
→ 기존 LLM 객체로 공통 prompt 실행
→ NaturalLanguageFeedbackInterpreter
→ feedback confidence 검증
→ 기존 FeedbackManager.apply_feedback
→ 기존 WeightManager.update_from_feedback
```

Qwen을 다시 생성하지 않는다. 안내문 생성기와 컨트롤러에 같은 adapter 인스턴스를 전달한다.

```python
llm = create_llm("qwen")
message_generator = LLMMessageGenerator(llm)
controller = CentralController(feedback_llm=llm)

result = controller.apply_natural_language_feedback(
    action_id,
    "나 아직 거실에 있는데 왜 불 껐어?",
)
```

LLM은 `positive`, `unnecessary`, `too_sensitive`, `too_late`, `cancel`,
`user_override`, `unknown` 중 하나와 `reason`, `confidence`만 JSON으로 반환한다.
`src/llm/prompts.py`의 공통 prompt가 scenario, device, action, reason, action confidence,
features, weights, contributions를 context로 전달한다. Interpreter에는 scenario별 분기가 없다.

`FEEDBACK_APPLY_THRESHOLD=0.80`, `FEEDBACK_REVIEW_THRESHOLD=0.50`이며
`src/control/confidence/config.py`에서 변경한다.

- `0.80` 이상: 기존 `FeedbackManager`를 호출해 weight 갱신
- `0.50` 이상 `0.80` 미만: 피드백만 저장하고 검토 대기
- `0.50` 미만: ambiguous/unknown으로 저장하고 갱신하지 않음

`action_confidence`와 자연어 해석의 `feedback_confidence`는 별도 필드다. action ID가 없거나
조회되지 않으면 scenario를 추정하지 않고 ambiguous로 저장한다. JSON 앞뒤 설명과 Markdown
code fence는 허용하지만, key 누락·미지원 label·범위 밖 confidence·빈 응답·generation 실패는
최대 한 번만 재시도한 뒤 `unknown`으로 저장한다.

자연어 기록은 별도 저장소를 만들지 않고 기존 `feedback.jsonl`에 다음 필드를 추가한다.

```json
{
  "action_id": "...",
  "raw_feedback": "나 아직 거실에 있는데 왜 불 껐어?",
  "parsed_feedback": {
    "feedback": "unnecessary",
    "reason": "user_was_still_using_room",
    "confidence": 0.94
  },
  "scenario": "light_auto_off",
  "action_confidence": 0.84,
  "feedback_confidence": 0.94,
  "weight_updated": true,
  "status": "applied"
}
```

## 검증

```powershell
python -m unittest discover -s tests -v
python tests/manual_all_test.py
```
