# HomeVIS 주방 중앙 제어 및 안전 알림 모듈

## 실시간 상태 추적 추가

기존 단건 `CentralController.evaluate()`와 LLM/TTS 기능을 유지하면서,
`update_sensing(SensingUpdate)`, `update_appliance(ApplianceUpdate)`, `tick(timestamp)`를 추가했습니다.
새 API는 위치 확인 시간, 주방 이탈 시간, 외출, 출력·온도 변화, 데이터 끊김을 평가합니다.
통신 프로토콜 대신 외부 센싱/기기 모듈이 호출하는 입력 API를 제공합니다.

```powershell
python test_realtime.py
python -m unittest discover -s tests -v
```

기본 예제는 가상 시간으로 상태 변화를 재생하고 기존 LLM fallback/DryRunTTS를 사용합니다.
설정과 23개 시나리오, JSONL 입력 방법은 [실시간 판단 설계](docs/realtime_control.md)를 참고하세요.
임계값은 `src/control/realtime_config.py`에서 변경할 수 있습니다.

HomeVIS는 외부 Wi-Fi Sensing 모듈이 추론한 사용자 상태와 조리기기 상태를 입력받아 주방 상황과 위험도를 판단하고, 필요한 경우 안내 문구와 TTS 음성 파일을 생성하는 모듈입니다.

이 프로젝트는 Wi-Fi 신호를 직접 측정하거나 실제 기기를 제어하지 않습니다. 이미 가공된 센싱 결과와 기기 상태를 받아 다음 파이프라인을 처리합니다.

```text
SensingState + DeviceState
            ↓
     CentralController
            ↓
       DecisionEngine
            ↓
      ControlDecision
            ↓
       RiskDecision
            ↓
       AlertService
            ↓
   LLM → TTS → AlertOutput
```

## 주요 기능

- 사용자 위치와 화구 상태에 따른 규칙 기반 상황 판단
- 중앙 제어 위험도와 기존 알림 위험도의 분리 및 매핑
- LLM 실패 시 기본 안내 문구로 자동 fallback
- 음성 안내용 WAV 파일 생성
- 실제 경고음 재생 없이 장비 연동용 신호 제공
- 향후 Decision Tree 엔진으로 교체 가능한 구조

## 프로젝트 구조

```text
src/
├─ control/
│  ├─ central_controller.py   # 중앙 제어 진입점
│  ├─ models.py               # 센싱·기기·판단 데이터 모델
│  ├─ policy.py               # 위험도 매핑 및 정책 설정
│  └─ decision/
│     ├─ base.py              # DecisionEngine 인터페이스
│     └─ rule_based.py        # 현재 규칙 기반 판단 엔진
├─ alert_service.py           # 알림 정책, 메시지 및 TTS 실행
├─ models.py                  # RiskDecision, AlertOutput
├─ llm/
│  ├─ message_generator.py    # LLM 호출 및 fallback
│  ├─ prompts.py              # 버전별 프롬프트
│  ├─ factory.py              # LLM adapter 생성
│  └─ adapters/               # Gemini, Qwen, Llama, EXAONE
├─ voice/tts.py               # pyttsx3 및 테스트용 TTS
└─ output/output_writer.py    # AlertOutput JSON 저장

tests/
├─ test_alert_service.py
└─ test_central_controller.py
```

## 입력 모델

### SensingState

외부 센싱 모듈에서 전달받는 사용자 상태입니다.

```python
SensingState(
    location="OTHER_ROOM",
    activity="moving",
    away_duration=10,
)
```

| `location` | 의미 |
| --- | --- |
| `STOVE_AREA` | 화구 바로 근처 |
| `KITCHEN` | 주방 안이지만 화구 바로 앞은 아님 |
| `OTHER_ROOM` | 집 안의 다른 공간 |
| `OUTSIDE_HOME` | 집 밖 |
| `UNKNOWN` | 위치 판단 불가 |

`away_duration`은 화구 주변을 벗어난 시간(초)이며, 음수는 허용하지 않습니다.

### DeviceState

외부 기기 연동 모듈에서 전달받는 화구 상태입니다.

```python
DeviceState(stove_on=True, heat_level="medium")
```

## 상황 판단 규칙

화구가 꺼져 있으면 위치보다 먼저 `STOVE_OFF / SAFE`로 판단합니다. 화구가 켜져 있을 때는 위치에 따라 다음 규칙을 적용합니다.

| 화구 | 위치 | 상황 | 중앙 제어 위험도 |
| --- | --- | --- | --- |
| OFF | 모든 위치 | `STOVE_OFF` | `SAFE` |
| ON | `STOVE_AREA` | `COOKING` | `SAFE` |
| ON | `KITCHEN` | `TEMP_AWAY` | `LOW` |
| ON | `OTHER_ROOM` | `IN_HOME_AWAY` | `LOW` |
| ON | `OUTSIDE_HOME` | `HOME_EXIT_WITH_STOVE_ON` | `HIGH` |
| ON | `UNKNOWN` | `LOCATION_UNKNOWN` | 정책값, 현재 `LOW` |

`OTHER_ROOM`의 장시간 이탈 기준은 아직 임의로 적용하지 않았습니다. 향후 정책을 추가할 수 있도록 `LONG_AWAY_THRESHOLD`를 별도로 두었습니다.

## 위험도 변환

중앙 제어 시스템과 기존 `AlertService`는 서로 다른 위험도를 사용합니다. 변환 규칙은 `src/control/policy.py`에서 관리합니다.

| 중앙 제어 위험도 | AlertService 위험도 |
| --- | --- |
| `SAFE` | `NORMAL` |
| `LOW` | `WARNING` |
| `HIGH` | `HIGH` |
| `CRITICAL` | `HIGH` |

중앙 제어 코드에서는 기존 알림 위험도인 `NORMAL`, `WARNING`, `HIGH`를 직접 사용하지 않습니다.

## 전체 사용 예시

```python
from src.alert_service import AlertService
from src.control import CentralController, DeviceState, SensingState
from src.llm.message_generator import LLMMessageGenerator
from src.voice.tts import DryRunTTS

controller = CentralController()
sensing = SensingState(
    location="OUTSIDE_HOME",
    activity="moving",
    away_duration=15,
)
device = DeviceState(stove_on=True, heat_level="high")

control_decision = controller.evaluate(sensing, device)
risk_decision = control_decision.to_risk_decision()

alert_service = AlertService(
    message_generator=LLMMessageGenerator(llm=None),
    tts=DryRunTTS(),
    output_dir="output",
)
alert_output = alert_service.handle(risk_decision)
```

위 입력의 처리 결과는 다음과 같습니다.

```text
HOME_EXIT_WITH_STOVE_ON / HIGH
                ↓
RiskDecision(risk_level="HIGH", user_state="OUT", device="induction")
                ↓
warning_sound=True, voice=True, message 및 TTS 파일 생성
```

## 알림 출력 정책

| 위험도 | 경고음 신호 | 음성 안내 | 동작 |
| --- | --- | --- | --- |
| `NORMAL` | False | False | 메시지와 TTS를 생성하지 않음 |
| `WARNING` | False | True | 안내 메시지와 TTS 생성 |
| `HIGH` | True | True | 경고음 요청 신호, 메시지와 TTS 생성 |

`warning_sound=True`는 실제 경고음을 재생한다는 의미가 아닙니다. 장비 제어 모듈에 전달하는 요청 신호입니다. `voice=True`일 때 생성된 `tts_file` 역시 이 프로젝트에서 자동 재생하지 않습니다.

## LLM과 fallback

- `none`: LLM을 호출하지 않고 기본 안내 문구 사용
- `gemini`: Vertex AI의 `gemini-2.5-flash` 호출
- `qwen`, `llama`, `exaone`: 교체 구조만 구현된 placeholder

LLM 호출 실패, 빈 응답 또는 미설정 시 기본 안내 문구를 사용하며 `fallback_used=True`가 됩니다.

Gemini 사용 시 환경 변수가 필요합니다.

```powershell
$env:GOOGLE_CLOUD_PROJECT="your-project-id"
$env:GOOGLE_CLOUD_LOCATION="global"
```

## 설치

Python 3.10 이상이 필요합니다.

```bash
python -m pip install -r requirements.txt
```

## 단독 알림 파이프라인 실행

기존 `RiskDecision`부터 시작하는 알림 파이프라인은 다음 명령으로 확인할 수 있습니다.

```bash
python test_alert.py --risk HIGH --situation HOME_EXIT_WITH_STOVE_ON --user_state OUT --user_location OUTSIDE_HOME --device induction --heat high --duration 15 --llm none --tts dry-run
```

기본 출력 위치:

```text
output/alert_output.json
output/alert_high_<고유값>.wav
```

OS에 설치된 음성을 사용하는 경우:

```bash
python test_alert.py --risk HIGH --llm none --tts pyttsx3
```

## 테스트

```bash
python -m unittest discover -s tests -v
```

현재 테스트는 다음을 검증합니다.

- 6개 중앙 제어 시나리오와 화구 OFF 우선 판단
- 중앙 제어 위험도와 알림 위험도 매핑
- `ControlDecision`에서 `RiskDecision`으로의 변환
- LLM fallback과 위험도별 알림 정책
- Dry-run WAV와 JSON 생성
- 중앙 제어부터 `AlertService`까지의 통합 흐름

테스트에서는 실제 경고음이나 스피커 출력을 사용하지 않습니다.

## Decision Tree 확장 지점

상황 판단은 `DecisionEngine` 인터페이스로 분리되어 있습니다.

```python
class DecisionEngine:
    def predict(
        self,
        sensing: SensingState,
        device: DeviceState,
    ) -> ControlDecision:
        ...
```

현재는 `RuleBasedDecisionEngine`을 사용합니다. 향후 같은 인터페이스를 구현한 엔진을 주입하면 나머지 파이프라인을 변경하지 않고 판단 방식만 교체할 수 있습니다.

```python
controller = CentralController(engine=DecisionTreeDecisionEngine(...))
```

## 현재 구현 범위 밖

- 실제 Wi-Fi Sensing, CSI, RSSI 처리
- 위치 및 행동 추론 모델
- 실제 화구 센서 통신과 기기 제어
- Decision Tree 학습 및 모델 구현
- MQTT, 데이터베이스, 대시보드
- 실제 경고음 및 TTS 파일 자동 재생
