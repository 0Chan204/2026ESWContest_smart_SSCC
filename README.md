# HomeVIS AI 중앙 판단 및 안전 알림

HomeVIS는 Wi-Fi 센싱 추론 모듈이 만든 최종 위치와 가전 상태를 받아 위험 상태를 판단하고,
자동 제어 요청과 사용자 안내를 생성하는 Python 모듈입니다. 별도로 측정한 행동 결과가 있으면
취침 소등, 기상 기반 출수, 욕실 낙상 시나리오에도 사용합니다.

현재 저장소는 [Purrloiner/HomeVIS-AI_main](https://github.com/Purrloiner/HomeVIS-AI_main)입니다.
백엔드 클라이언트, 시간순 판단 런타임, SQLite outbox, MockBackend와 회귀 테스트를 포함합니다.
실제 Wi-Fi 신호 측정·분류와 가전 명령 실행은 외부 센싱 모듈 및 백엔드가 담당합니다.

## 빠르게 실행하기

Python 3.10 이상을 사용합니다. 아래 명령은 `README.md`, `src/`, `tests/`가 있는
저장소 루트에서 실행합니다. Mock 데모와 자동 테스트에는 실제 백엔드, 가전, LLM 모델, GPU가 필요하지 않습니다.

Windows PowerShell:

```powershell
git clone https://github.com/Purrloiner/HomeVIS-AI_main.git
cd HomeVIS-AI_main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install pytest
python -m examples.backend_integration_demo
python -m examples.backend_integration_demo --with-mock-behavior
```

이미 내려받은 저장소라면 clone 단계는 건너뛰고 그 루트에서 시작합니다.
PowerShell에서 가상환경 활성화가 제한되면 이후의 `python`을
`.\.venv\Scripts\python.exe`로 바꾸어 실행할 수 있습니다.
Linux/macOS의 가상환경 활성화 명령은 `source .venv/bin/activate`입니다.

| 데모 | 입력과 예상 결과 |
| --- | --- |
| 기본 | 위치만 공급. 기기 조회 5회, POST 0건. 행동이 필요한 기능은 `missing_inputs`에 표시 |
| `--with-mock-behavior` | 별도 가상 행동 공급. 기기 조회 5회, 180ml 출수·날씨 안내 요청 1건을 Mock에 접수 |

행동 데모는 침실 매핑, 정수기 `idle`, 규칙 confidence의 `null`을 **Mock 전용 설정**으로 사용합니다.
낙상에 필요한 motion/fall 정보는 이 데모에도 없습니다. 응답의 `accepted`와 `sent`는
접수·전송 상태이며 실제 출수나 전등 동작의 완료를 뜻하지 않습니다.

데모는 기본적으로 임시 저장소를 사용합니다. 결과와 출수 예약을 유지하려면
`--data-dir output/demo`를 추가합니다. 같은 저장소로 다시 실행하면 일일 출수 예약 때문에
새 출수 요청이 생성되지 않을 수 있습니다. 이 데모의 정렬 지연은 0초이고,
운영 설정의 기본 2초 지연은 별도 런타임 회귀 테스트에서 검증합니다.

## 구현된 기능

| 기능 | 현재 동작 |
| --- | --- |
| 실시간 위험 판단 | 위치 확인, 주방 이탈 시간, 화력·온도 변화, 기기 OFF, 센싱 불확실·timeout을 추적 |
| Confidence 기반 제어 | feature와 가중치로 화력 감소·복구 및 일반 조명 요청을 평가하고 근거를 기록 |
| 취침 소등 | 실제 `lying` 관측이 이어져야 요청 생성. 기본 유지 시간은 600초 |
| 아침 출수 | 기상 확인과 주방 체류, 정수기 준비 상태를 확인. 기본 250ml, 하루 최대 1회 |
| 욕실 낙상 | 행동·움직임 관측으로 확인/경고/긴급 단계를 추적. 통합 전송은 낙상 API 계약이 필요 |
| 피드백 | 구조화·자연어 피드백을 사용자·시나리오별 가중치에 반영 |
| 안내와 음성 파일 | 판단 결과를 문구와 WAV로 변환. LLM 생성 실패 시 기본 안내 문구 사용 |
| 백엔드 클라이언트 | 기기 상태 GET, 판단 POST, 응답 검증, 제한된 재시도와 재시작 복구 |

시나리오가 요청을 생성하는 것과 백엔드로 전송할 수 있는 것은 별개의 조건입니다.
현재 통합 기본 설정은 미확정 라우트·규칙 confidence·정수기 준비 상태를 차단하며,
자동 화력 복구와 낙상 시작 요청도 실제 계약이 필요합니다.

## 처리 구조

```text
센싱 추론의 최종 위치 JSON ──┐
별도 행동 관측(선택) ────────┼─> IntegrationRuntime
백엔드 기기 상태 GET ───────┘       │ 측정 시각 정렬·유효성 확인
                                   v
                            CentralController
                                   │ 위험 판단·제어 요청
                                   v
                         SQLite outbox에 먼저 저장
                                   │ 최신 상태 재검증
                                   v
                         백엔드 판단 POST / 접수 기록
```

LLM은 안내문 생성과 자연어 피드백 해석에 사용합니다. 실시간 상태 판단과 제어 요청은
규칙·시나리오·confidence 계층에서 생성합니다.
`AlertService`는 판단 결과를 받아 문구와 TTS 파일을 만드는 별도 경로이며,
현재 통합 CLI가 음성을 자동 재생하거나 백엔드에 음성 파일을 전송하지는 않습니다.

## 센싱 입력 계약

통합 런타임은 Pi의 `features` 배열 대신 센싱 추론이 완료된 위치 JSON을 받습니다.

```json
{
  "time": "2026-10-02T15:05:03+09:00",
  "location": "kitchen",
  "location_confidence": 0.87
}
```

불확실한 결과도 원본을 유지합니다.

```json
{
  "time": "2026-10-02T15:05:04+09:00",
  "location": "unknown",
  "location_confidence": null,
  "reason": "node_offline:r3"
}
```

| 원본 위치 | 내부 처리 |
| --- | --- |
| `kitchen` | `kitchen` |
| `toilet` | `bathroom` |
| `room` | `room_is_bedroom=True`로 명시했을 때만 `bedroom` |
| `empty`, `unknown` | 내부 위치는 `unknown`, 원본 의미는 각각 보관. `outside`로 변환하지 않음 |
| `r2/r3/r4` 등 미등록 값 | 장소로 해석하지 않고 무효 관측으로 진단 |

`time`은 시간대가 있는 원본 측정 시각입니다. 수신·조회 시각과 구분하여 저장하고,
같은 측정 결과를 반복 조회해도 새 관측으로 누적하지 않습니다.
원본 `null`, 전체 `reason`, 유효 여부를 별도로 보존하며 내부 숫자 confidence에만 0을 사용합니다.
`node_offline:r3`, `config_mismatch` 등 비어 있지 않은 오류 사유는 무효 관측으로 처리합니다.

`runtime.sensing_health()`는 메시지 미수신, 오래된 측정, 명시적 무효 입력을 구분합니다.
마지막 확인 위치가 남아 있어도 현재 유효한 재실 근거로 사용하지 않으며,
불확실한 센싱만으로 기존 위험을 정상으로 해제하지 않습니다.

### 별도 행동 입력

위치 JSON에는 `activity`, `motion_state`, `fall_detected`가 없습니다.
미측정 행동의 신뢰도에 위치 신뢰도를 복사하지 않으며, confidence 계산에서 미측정 행동의 기여도는 0입니다.

별도 행동 입력 경계는 [BehaviorObservation](src/integration/sensing.py)입니다.
`measured_at`, `valid_until`, 내부 위치, 행동 confidence 및 유효성을 검사한 뒤 위치와 결합합니다.
같은 공간이며 행동 측정이 위치 측정보다 미래가 아니고, 기본 최대 시각차 1초 이내이며
행동 유효기간이 끝나지 않았을 때 결합할 수 있습니다.
실제 행동 데이터 수신 어댑터는 아직 연결되지 않았습니다.

취침에는 lying, 기상 출수에는 기상 전이, 낙상에는 낙상 신호 또는 행동 전이와 motion 정보가 필요합니다.
필요 입력의 부재는 `runtime.missing_inputs`로 확인합니다.

## 시간순 판단과 송신 검증

기본 `allowed_lateness=2.0`에서 `advance(now)`는 `now-2초`까지 도착한 이벤트를 처리합니다.
각 센싱 이벤트에는 그 측정 시각 이하의 기기 상태를 적용하고, 조명은 마지막 평가 시각에서 판단합니다.
동일 시각에 처리 가능한 데이터가 있으면 기기 관측·무효화 정보를 먼저 반영한 뒤 센싱을 평가합니다.

| 상태 | 용도 |
| --- | --- |
| `evaluated_devices` | 평가 시각 이하에서 마지막으로 적용된 기기 상태 |
| `latest_received_devices` / `devices` | 송신 직전에 현재 시각으로 재검증할 최신 수신 기기 상태 |

현재가 T+10이고 평가 시각이 T+8이면 판단에는 T+8 이하 관측을 씁니다.
T+10의 기기가 offline이면 T+8의 정상 관측으로 생성한 요청도 전송을 차단합니다.
더 최근의 offline·invalid를 건너뛰어 예전 정상 상태로 돌아가지 않습니다.
측정 시각·수신 시각·평가 시각·송신 시각은 별도로 취급합니다.

조명 재검증은 outbox의 원래 시나리오와 대상을 기준으로 수행합니다.

- `light_auto_off`: 유효한 부재 근거가 필요하며 사용자가 돌아오면 차단합니다.
- `bedtime_light_off`: 실제 취침 조건으로 생성된 현재 요청인지 확인하고, 유효한 lying 관측이 유지돼야 합니다.
  기상·이탈·관측 공백으로 근거가 끊긴 과거 요청은 다시 누워도 재사용하지 않습니다.
- `light_auto_on`: 현재 재실과 확정 위치, 대상 전등의 방을 확인합니다.

송신 검증은 상태를 읽기만 합니다. 최신의 유효한 행동 관측으로 이미 충족한 취침 조건의 유지를
확인할 수 있지만, 엔진 시각이나 취침 지속 시간을 앞당기지 않습니다.

센싱 자체의 전환 확인이 2~3초라면, 새 측정이 계속 들어오는 조건에서 AI 위치 확인 5초와
정렬 지연 2초까지 합쳐 처리 시점 기준 약 9~10초에 조회·전송 지연이 더해질 수 있습니다.
자세한 조건은 [백엔드 통합 문서](docs/backend_integration.md)를 참고하세요.

## 백엔드 연결과 저장

사용하는 API 경로는 다음과 같습니다.

- `GET /api/v1/ai/device-states`: 기기 상태 조회
- `POST /api/v1/ai/decisions`: 판단과 제어 요청 전달

Mock polling 호스트 실행:

```powershell
python -m src.integration --mode mock --duration 3
```

이 CLI는 기기 조회와 주기적 판단을 수행하며 센싱 어댑터가 붙어 있지 않음을 출력합니다.
실제 입력 연결은 한 실행 스레드에서 `runtime.ingest_location(payload, received_at=..., behavior=...)`와
`runtime.run_once()`를 호출하는 방식입니다. HTTP 작업 스레드는 통신만 수행합니다.

실제 연결은 확인된 서버 주소를 `--mode live --base-url <URL>`로 명시합니다.
`HOMEVIS_BACKEND_URL` 환경 변수도 지원합니다. 인증 헤더와 배포별 설정은
[IntegrationConfig](src/integration/config.py)에 주입합니다.
[.env.example](.env.example)은 참고 파일이며 자동으로 읽지는 않습니다.

주요 기본값:

| 설정 | 기본값 |
| --- | --- |
| `mode` | `mock` |
| `poll_interval` / `allowed_lateness` | 각각 2초 |
| `http_timeout` | 3초 |
| `max_attempts` / `retry_interval` | 최대 3회 / 2초 |
| `command_ttl` | 요청 원본 timestamp 기준 15초 |
| `device_max_age` | 20초 |
| `room_is_bedroom` | `False` |
| `water_ready_states` | 빈 튜플 |
| `rule_confidence_policy` | `block` |
| `action_routes` | 빈 매핑 |

출력은 outbox 저장에 성공한 뒤에만 컨트롤러 큐에서 제거합니다. 재시도·재시작에서도
`decisionId`와 본문을 유지하며 만료된 명령은 보내지 않습니다.
일일 출수 예약과 미해결 낙상 사건도 디스크에 보관합니다.
낙상 종료 계약이 없으므로 단순 움직임이나 재시작으로 사건을 해제하지 않습니다.

기본 저장 위치:

```text
output/integration/mock/outbox.sqlite3   # Mock 요청·응답·감사 기록·예약
output/integration/live/outbox.sqlite3   # Live 전용 저장소
output/integration/<mode>/controller/   # 통합 컨트롤러의 판단·피드백·루틴 기록
output/confidence/                     # 컨트롤러 직접 호출 시 기본 기록
output/realtime/                       # 실시간 단독 데모의 판단과 알림
```

런타임과 컨트롤러는 한 스레드, outbox는 한 프로세스가 소유하는 구조입니다.

## 컨트롤러 직접 사용과 알림

통합 런타임 외에 기존 단건 API와 실시간 API를 직접 사용할 수 있습니다.

| API | 입력 / 역할 |
| --- | --- |
| `CentralController.evaluate()` | `SensingState` + `DeviceState`의 단건 규칙 판단 |
| `update_sensing()` / `update_appliance()` / `tick()` | `SensingUpdate` + `ApplianceUpdate` 및 시간 경과로 상태 추적 |
| `evaluate_light()` | `LightContext`로 일반 조명 confidence 평가 |
| `apply_feedback()` / `apply_natural_language_feedback()` | 기존 판단에 대한 피드백 반영 |

단건 API의 `STOVE_AREA/KITCHEN/OTHER_ROOM/OUTSIDE_HOME/UNKNOWN` 값은 기존 입력 모델의 값입니다.
외부 최종 위치 JSON은 앞의 통합 입력 계약을 사용합니다.
판단 엔진은 `DecisionEngine` 인터페이스로 교체할 수 있으며 현재 단건 구현은 `RuleBasedDecisionEngine`입니다.

```powershell
python test_realtime.py --llm none --tts dry-run
python -m tests.manual_all_test
python test_alert.py --risk HIGH --situation HOME_EXIT_WITH_STOVE_ON --user_state OUT --user_location OUTSIDE_HOME --device induction --heat high --duration 15 --llm none --tts dry-run
```

첫 명령은 내장 실시간 이벤트를 재생하고, 두 번째는 시나리오·confidence·피드백을 가상 입력으로 확인합니다.
마지막 명령은 위험 판단 이후의 알림 경로를 확인하며 기본적으로 `output/alert_output.json`과 WAV를 만듭니다.

| 알림 위험도 | 경고음 요청 | 문구·음성 파일 |
| --- | --- | --- |
| `NORMAL` | 없음 | 생성하지 않음 |
| `WARNING` | 없음 | 생성 |
| `HIGH` | `warning_sound=True` | 생성 |

경고음은 요청 신호입니다. `DryRunTTS`의 WAV는 테스트용 톤이고,
실제 안내 음성이 필요하면 OS 음성을 사용하는 `--tts pyttsx3`를 선택합니다. 파일은 자동 재생하지 않습니다.

### 선택적 LLM·TTS 설정

`requirements.txt`에는 `pyttsx3`와 `google-genai`가 있습니다.

```powershell
python -m pip install -r requirements.txt
```

| LLM 선택 | 현재 구현과 준비 사항 |
| --- | --- |
| `none` | 외부 모델 없이 기본 문구 사용. Mock/자동 테스트의 기본 경로 |
| `gemini` | Vertex AI adapter. 코드 기본 모델은 `gemini-2.5-flash`; 프로젝트·인증 설정 필요 |
| `qwen` | 로컬 Qwen3-8B 로딩 구현. 기본 경로는 사용자 홈의 `models/Qwen3-8B` |
| `llama`, `exaone` | adapter 인터페이스만 있는 placeholder |

Gemini는 `GOOGLE_CLOUD_PROJECT`와 선택적인 `GOOGLE_CLOUD_LOCATION`(기본 `global`)을 읽습니다.
Qwen은 로컬 모델 파일과 별도로 설치한 `torch`, `transformers`, `accelerate` 등이 필요하며
이 패키지와 모델은 기본 requirements에 포함되어 있지 않습니다.
모델 생성 단계의 인증·파일·의존성 오류는 먼저 해결해야 합니다.
메시지 생성 중 호출 실패나 빈 응답은 기본 안내 문구로 처리합니다.

구조화 피드백과 자연어 피드백은 기존 `FeedbackManager`와 `WeightManager`를 사용합니다.
백엔드 yes/no 피드백 자동 연결은 아직 구현되지 않았습니다.

## 테스트

```powershell
python -m pytest -q
python -m unittest discover -s tests -v
python -m pytest -q tests/test_backend_integration.py tests/test_runtime_regressions.py
```

코드 커밋 `92f7030`까지 확인한 실행 결과는 전체 pytest **221개 통과**, unittest **104개 통과**입니다.
`tests/test_runtime_regressions.py`의 회귀 테스트 **53개**는 pytest 전체 결과에 포함됩니다.
unittest 명령은 기존 unittest 클래스들을 실행하므로 pytest 함수형 통합 테스트까지 확인하려면 pytest를 사용합니다.

자동 테스트는 위치/행동 유효성, 2초 지연의 시간순 기기 상태, 취침 요청 재검증,
중복·충돌·stale, outbox 저장 실패, 재전송 본문/ID, 명령 만료, 재시작 출수 예약을 검증합니다.
실제 LLM·GPU·가전은 호출하지 않습니다.
`tests/manual_test.py`와 `tests/manual_morning_water_test.py`는 로컬 Qwen을 로딩하는 별도 수동 실행 파일입니다.

## 프로젝트 구조와 상세 문서

```text
src/
├─ integration/             # 백엔드 클라이언트, 입력 변환, 시간순 런타임, SQLite outbox
├─ control/
│  ├─ central_controller.py # 단건·실시간 판단과 시나리오 진입점
│  ├─ decision/             # 단건 규칙 엔진과 실시간 상태 엔진
│  ├─ confidence/           # feature, 가중치, 점수, 판단 이력
│  ├─ feedback/             # 구조화·자연어 피드백
│  ├─ routine/              # 루틴 기록
│  ├─ bedtime_light.py      # 취침 소등
│  ├─ morning_water.py      # 기상·주방 체류·출수
│  └─ bathroom_fall.py      # 욕실 낙상 상태 머신
├─ alert_service.py         # 판단 이후 안내·TTS 정책
├─ llm/                     # 안내 prompt, adapter, fallback
├─ voice/tts.py             # 실제 TTS 및 테스트용 WAV
└─ output/output_writer.py  # 알림 JSON 저장
examples/                   # 백엔드 Mock 데모
tests/                      # 자동 회귀 테스트와 수동 시나리오
docs/                       # 세부 설계와 계약
```

- [백엔드 통합](docs/backend_integration.md): 외부 JSON 계약, 최신 런타임 동작, 전송 차단 및 재시작 정책
- [실시간 판단](docs/realtime_control.md): 직접 호출 모델, 상태 전이, JSONL 재생
- [Confidence 제어](docs/confidence_control.md): 점수·가중치·피드백 설계와 직접 호출 예시
- [생활·안전 시나리오](docs/scenarios.md): 취침·출수·낙상 상태와 출력 모델

외부 통합에서의 입력 유효성·미측정 행동·자동 복구 정책은 백엔드 통합 문서를 기준으로 확인하세요.
실전 연결에는 제어 라우트와 규칙 confidence 표현, 정수기 준비 상태, 화력 단계와 W의 대응,
제어·실행 이력, 낙상 시작/확인/종료 API, 실제 위치·행동 수신 방식의 합의가 필요합니다.
백엔드 서버, MQTT 통신, Wi-Fi 추론 모델, LG OS 탑재 및 실가전 실행 검증은 현재 저장소의 구현 범위에 포함되지 않습니다.
