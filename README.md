# HomeVIS 조리 안전 안내 생성 / TTS 모듈

이 프로젝트는 **위험도를 판단하는 모듈이 아니라**, 이미 판단된 조리 상황 결과를 받아
사용자에게 전달할 안내 문구와 TTS 음성 파일을 생성하는 후처리 모듈입니다.

## 전체 구조

```text
Wi-Fi Sensing 결과 + 조리 장비 상태
        ↓
상황/위험 판단 모델
Decision Tree 또는 다른 모델
※ 향후 별도 구현
        ↓
RiskDecision
        ↓
현재 모듈
- LLM 안내 문구 생성
- 실패 시 기본 안내 문구 fallback
- TTS 음성 파일 생성
- 경고음 필요 여부 신호 생성
        ↓
AlertOutput / JSON
        ↓
장비 담당
- 실제 경고 효과음 재생
- 생성된 TTS 파일 스피커 재생
```

## 현재 구현하지 않는 것

- Wi-Fi Sensing / CSI / RSSI
- 사용자 위치·행동 추론
- IN/OUT 판별 알고리즘
- 장비 상태 수집
- Decision Tree
- 위험도 계산
- 실제 로컬 LLM 다운로드/실행
- 경고 효과음 재생
- TTS 파일 스피커 재생
- MQTT / DB / 대시보드 / STT / 가전 제어

`risk_level`은 이 모듈이 계산하지 않고 외부 판단 모델이 이미 결정한 입력입니다.

## 출력 정책

| Risk Level | Warning Sound | Voice | 동작 |
| --- | --- | --- | --- |
| NORMAL | False | False | 아무 안내 없음 |
| WARNING | False | True | 안내 문구 + TTS 파일 |
| HIGH | True | True | 경고음 필요 신호 + 안내 문구 + TTS 파일 |

`warning_sound=True`는 실제 경고음을 재생한다는 뜻이 아닙니다.
장비 담당 모듈에 경고음을 재생해야 한다는 신호만 전달합니다.

## 구조

```text
src/
├─ alert_service.py
├─ models.py
├─ llm/
│  ├─ message_generator.py
│  ├─ prompts.py
│  ├─ factory.py
│  └─ adapters/
│     ├─ base.py
│     ├─ qwen.py
│     ├─ llama.py
│     └─ exaone.py
├─ voice/
│  └─ tts.py
└─ output/
   └─ output_writer.py

output/
tests/
test_alert.py
requirements.txt
README.md
```

## 설치

```bash
python -m pip install -r requirements.txt
```

현재는 `pyttsx3`만 포함합니다.
Qwen/Llama/EXAONE 모델 패키지는 아직 추가하지 않습니다.

## 독립 실행

```bash
python test_alert.py   --risk HIGH   --situation COOKING_UNATTENDED   --user_state OUT   --device induction   --heat HIGH   --duration 120   --llm none   --tts dry-run
```

`dry-run`은 실제 음성이 아닌 테스트 WAV를 만들어 파일 생성 흐름만 검증합니다.

OS TTS를 사용하려면:

```bash
python test_alert.py --risk HIGH --llm none --tts pyttsx3
```

생성된 WAV는 자동 재생되지 않습니다.

## LLM 교체 실험

모델별 호출 코드는 `src/llm/adapters/`에 분리되어 있습니다.

```text
qwen.py   → Qwen
llama.py  → Llama
exaone.py → EXAONE
```

현재는 placeholder입니다. 실제 모델은 다운로드하거나 실행하지 않습니다.

향후 각 adapter의 `generate()` 내부에만 실제 로컬 모델 코드를 연결하면 됩니다.

```bash
python test_alert.py --risk HIGH --llm qwen --tts dry-run
python test_alert.py --risk HIGH --llm llama --tts dry-run
python test_alert.py --risk HIGH --llm exaone --tts dry-run
```

현재는 adapter가 미구현이므로 자동으로 기본 안내 문장으로 fallback합니다.

## Prompt 버전

프롬프트는 `src/llm/prompts.py`에서 관리합니다.

```bash
python test_alert.py --risk HIGH --prompt v1
```

향후 `SYSTEM_PROMPTS`에 `v2`, `v3`를 추가하면 동일한 파이프라인으로 비교할 수 있습니다.

## 향후 Decision Tree 연결

현재:

```python
decision = RiskDecision(
    risk_level="HIGH",
    situation="COOKING_UNATTENDED",
    user_state="OUT",
    device="induction",
    heat_level="HIGH",
    duration=120,
)

alert_output = alert_service.handle(decision)
```

향후:

```python
wifi_result = ...
device_result = ...

decision = decision_model.predict(wifi_result, device_result)
alert_output = alert_service.handle(decision)
```

즉 Decision Model과 안내 생성/TTS 모듈을 분리합니다.

## AlertOutput 예시

```json
{
  "risk_level": "HIGH",
  "warning_sound": true,
  "voice": true,
  "message": "조리 중 위험 상황이 감지되었습니다. 즉시 주방 상태를 확인해 주세요.",
  "tts_file": "output/alert_high_1234abcd.wav",
  "llm_name": "none",
  "prompt_version": "v1",
  "fallback_used": true,
  "llm_error": null,
  "tts_error": null
}
```

장비 담당에서는:

```text
warning_sound == true
→ 실제 경고 효과음 재생

voice == true
→ tts_file 음성 파일을 실제 스피커로 재생
```

으로 연결하면 됩니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## Central kitchen controller

The controller accepts already-inferred sensing and device state. It does not
perform Wi-Fi sensing or communicate with the stove.

```python
from src.control import CentralController, DeviceState, SensingState

control_decision = CentralController().evaluate(
    SensingState(
        location="OUTSIDE_HOME", activity="moving", away_duration=15
    ),
    DeviceState(stove_on=True, heat_level="high"),
)
risk_decision = control_decision.to_risk_decision()
alert_output = alert_service.handle(risk_decision)
```

`DecisionEngine.predict(sensing, device)` is the replaceable decision boundary.
The default `RuleBasedDecisionEngine` can later be replaced by a decision-tree
engine without changing `CentralController` or `AlertService`.

Control risks are mapped in `src/control/policy.py`: `SAFE` to `NORMAL`, `LOW`
to `WARNING`, and both `HIGH` and `CRITICAL` to `HIGH`. Unknown location uses
the separately configurable `LOW` policy. `LONG_AWAY_THRESHOLD` is reserved
for a future rule and currently does not alter the specified scenarios.

테스트에서는 실제 경고음이나 스피커 출력을 사용하지 않습니다.
