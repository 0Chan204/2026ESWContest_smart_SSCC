# HomeVIS AI 중앙 판단 및 안전 알림

HomeVIS는 Wi-Fi 센싱 추론 모듈의 최종 위치 결과와 가전 상태를 받아 위험 상태를 판단하고,
자동 제어 요청과 사용자 안내를 생성하는 Python 모듈입니다. 별도로 측정한 행동 결과가 있으면
취침 소등, 기상 기반 출수, 욕실 낙상 시나리오에도 사용합니다.

백엔드 클라이언트, 측정 시각 기반 판단 런타임, SQLite outbox, MockBackend를 포함합니다.
실제 Wi-Fi 신호 측정·분류와 가전 명령 실행은 외부 센싱 모듈 및 백엔드가 담당합니다.

## 주요 기능

| 기능 | 동작과 필요한 입력 |
| --- | --- |
| 실시간 주방 위험 판단 | 위치 확인, 주방 이탈 시간, 출력·온도 변화, 기기 종료, 센싱 불확실·timeout 추적 |
| Confidence 기반 자동 제어 | 여러 feature의 가중합으로 화력 감소·복구 및 일반 조명 요청 평가, 판단 근거 기록 |
| 취침 소등 | 유효한 침실 `lying` 행동 관측이 기본 600초 이어지면 소등 요청 생성 |
| 아침 출수 | 기상 확인, 주방 체류, 허용 시간대, 정수기 준비 상태 확인 후 기본 120mL 요청, 하루 최대 1회 |
| 욕실 낙상 | 낙상 신호 또는 행동 전이와 움직임 관측으로 확인·경고·긴급 단계 추적 |
| 피드백 | 기존 판단에 대한 구조화·자연어 피드백을 사용자·시나리오별 가중치에 반영 |
| 안내·음성 | 판단 결과로 안내문과 WAV 생성, LLM 안내 생성 실패 시 기본 문구 사용 |
| 백엔드 연동 | 기기 상태 조회, 판단 요청 전달, 송신 전 재검증, 제한된 재시도와 디스크 예약 |

내부 요청 생성과 백엔드 전송은 별도 조건을 따릅니다. 통합 기본 설정에서 미확정 제어 라우트,
규칙 confidence 표현, 정수기 준비 상태는 전송을 차단합니다. 자동 화력 복구와 낙상 요청도
실제 제어 이력 및 API 계약이 필요합니다.

## 처리 구조

```text
센싱 추론의 최종 위치 JSON ──┐
별도 행동 관측(선택) ────────┼─> IntegrationRuntime
백엔드 기기 상태 GET ───────┘       │ 측정 시각 정렬·유효성 확인
                                   v
                            CentralController
                                   │ 위험 판단·제어 요청
                                   v
                             SQLite outbox
                                   │ 송신 직전 최신 상태 재검증
                                   v
                        백엔드 판단 POST / 접수 기록
```

`AlertService`는 판단 결과를 받아 안내문과 TTS 파일을 만드는 별도 경로입니다.
통합 런타임이 음성을 자동 재생하거나 백엔드로 음성 파일을 전송하지는 않습니다.
LLM은 안내문 생성·자연어 피드백 해석에 사용하며, 위험 상태와 제어 요청은 판단 엔진이 결정합니다.

## 설치와 빠른 실행

Python 3.10 이상을 사용합니다. 명령은 `README.md`, `src/`, `tests/`가 있는 저장소 루트에서
실행합니다. Mock 데모는 표준 라이브러리로 실행되며 실제 백엔드, 가전, LLM 모델, GPU가 필요하지 않습니다.

```sh
git clone https://github.com/2026ESEC-SSCC/HomeVIS-AI_main.git
cd HomeVIS-AI_main
python -m venv .venv
```

Windows PowerShell에서 가상환경을 활성화합니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

활성화가 제한되면 이후 명령의 `python` 대신 `.\.venv\Scripts\python.exe`를 사용합니다.
Linux/macOS에서는 다음 명령을 사용합니다. `python` 명령이 없는 환경에서는 `python3`를 사용합니다.

```sh
source .venv/bin/activate
```

테스트 의존성을 설치하고 두 Mock 데모를 실행합니다.

```sh
python -m pip install pytest
python -m examples.backend_integration_demo
python -m examples.backend_integration_demo --with-mock-behavior
```

| 데모 | 입력과 예상 결과 |
| --- | --- |
| 기본 | 위치만 공급. 기기 조회 5회, POST 0건. 행동이 필요한 기능은 `missing_inputs`에 표시 |
| `--with-mock-behavior` | 별도 가상 행동 공급. 기기 조회 5회, 120mL 출수·날씨 안내 요청 1건을 Mock에 접수 |

행동 데모는 명시적 침실 매핑, 정수기 `idle` 상태, 규칙 confidence의 `null` 표현을
Mock 전용 계약으로 사용합니다. 출수량은 `ScenarioConfig`의 기본값을 사용합니다.
낙상에 필요한 motion/fall 정보는 이 데모에도 없습니다.

기본 데모 저장소는 임시 디렉터리입니다. `--data-dir output/demo`를 추가하면 outbox와 일일 예약을
유지합니다. 같은 날 같은 저장소에서 재실행하면 예약 때문에 새 출수 요청이 생성되지 않을 수 있습니다.

선택적 안내·음성 경로는 다음과 같이 확인합니다.

```sh
python test_realtime.py --llm none --tts dry-run
```

`dry-run`은 테스트용 WAV를 생성하며 파일을 자동 재생하지 않습니다.
실제 OS 음성은 `--tts pyttsx3`를 사용합니다. `python -m pip install -r requirements.txt`는
선택적 TTS 및 Gemini 의존성을 설치합니다. Gemini adapter는 Vertex AI의 `GOOGLE_CLOUD_PROJECT`와
선택적인 `GOOGLE_CLOUD_LOCATION`을 사용합니다. Qwen adapter는 별도 로컬 모델과
`torch`, `transformers`, `accelerate`가 필요합니다. `llama`, `exaone` adapter는 placeholder입니다.
기본 `--llm none` 경로는 이러한 모델과 인증을 요구하지 않습니다.

## 주요 설정

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `KITCHEN_SHORT_ABSENCE` | 20초 | 주방 이탈 주의 기준 |
| `KITCHEN_WARNING_TIME` | 40초 | 주방 이탈 경고 기준 |
| `KITCHEN_DANGER_TIME` | 60초 | 주방 장시간 이탈 위험 기준 |
| `KITCHEN_LEAVE_FULL_SECONDS` | 60초 | 이탈 시간 feature의 최대 점수 기준 |
| `MORNING_WATER_AMOUNT_ML` | 120mL | 새로 생성하는 기본 자동 출수 요청량 |

위험 단계는 프로그램 시작 시간이 아니라 엔진이 추적하는 주방 이탈 경과시간을 기준으로 합니다.
고출력·온도 상승이나 긴급 신호가 있으면 더 높은 단계가 먼저 발생할 수 있습니다.
위치·복귀 확인 시간, 센싱·기기 timeout, 신뢰도 검증은 계속 적용됩니다.
불확실한 입력만으로 기존 위험 상태를 정상으로 해제하지 않습니다.

시간 feature는 `clamp(leave_duration / 60, 0, 1)`로 계산하므로 20초에 약 1/3,
40초에 약 2/3, 60초 이상에 1입니다. 실제 `reduce_power` 요청은 다른 feature와 합산한
confidence가 기존 threshold **0.82**에 도달하고 유효한 센싱·기기 상태 등 실행 조건을 만족할 때
생성됩니다. 전력이나 행동 입력이 부족하면 60초에도 요청이 생성되지 않을 수 있습니다.
`reduce_power`는 특정 온도만큼 낮추거나 전원을 끄는 명령으로 변환하지 않습니다.

설정은 [RealtimeConfig](src/control/realtime_config.py),
[ConfidenceConfig](src/control/confidence/config.py), [ScenarioConfig](src/control/scenario_config.py)에 있습니다.
사용자 정의 출수량도 설정할 수 있습니다. 새 기본값은 기존 pending/sending 요청의 수량·본문·ID나
과거 출수 기록을 변경하지 않습니다.

## 입력과 백엔드 연동

Pi의 `features` 배열 대신 추론이 완료된 최종 위치 JSON을 입력합니다.

```json
{
  "time": "2026-10-02T15:05:03+09:00",
  "location": "kitchen",
  "location_confidence": 0.87
}
```

| 원본 위치 | 내부 처리 |
| --- | --- |
| `kitchen` | `kitchen` |
| `toilet` | `bathroom` |
| `room` | `room_is_bedroom=True`로 명시한 경우만 `bedroom` |
| `empty`, `unknown` | 내부 위치는 `unknown`, 원본 의미는 각각 보존. `outside`로 변환하지 않음 |
| `r2/r3/r4` 등 미등록 값 | 장소로 해석하지 않고 무효 관측으로 진단 |

`time`은 시간대가 있는 측정 시각이며 조회 시각으로 덮어쓰지 않습니다. 같은 측정 결과는 중복 관측으로
누적하지 않습니다. `unknown`의 원본 `null` confidence, `node_offline:r3`나 `config_mismatch` 등의
전체 `reason`, 관측 유효 여부를 별도로 보존합니다. 명시적 무효 결과와 메시지 미수신 timeout을 구분하며,
마지막 확인 위치만으로 현재 유효한 재실을 주장하지 않습니다.

위치 JSON에는 `activity`, `motion_state`, `fall_detected`가 없습니다. 취침·기상·낙상 기능은 필요한
실제 행동 입력이 별도로 있어야 하며, 미측정 행동의 confidence 기여도는 0입니다.
[BehaviorObservation](src/integration/sensing.py)은 행동의 측정 시각·만료·공간·유효성을 검사하는
입력 경계입니다. 실제 행동 수신 어댑터는 아직 연결되지 않았습니다.

사용하는 백엔드 API는 다음과 같습니다.

- `GET /api/v1/ai/device-states`: 기기 상태 조회
- `POST /api/v1/ai/decisions`: 판단과 제어 요청 전달

출수량은 `ScenarioConfig.MORNING_WATER_AMOUNT_ML` → `DeviceCommand.amount_ml` →
`actions[].amountMl`로 전달됩니다. 기본 출수 요청의 주요 필드는 다음과 같습니다.

```json
{
  "scenario": "water_dispense",
  "room": "kitchen",
  "actions": [{"device": "water_purifier", "action": "dispense", "amountMl": 120}],
  "weatherBriefing": true
}
```

위 예시는 요청의 일부 필드입니다. 전체 요청에는 `decisionId`, 측정 기반 `timestamp`, 판단 근거와
confidence 표현도 필요합니다. Mock의 `accepted`와 `sent`는 접수·전송 상태이며 실기기 실행 완료가 아닙니다.

```sh
python -m src.integration --mode mock --duration 3
```

이 CLI는 기기 조회·주기적 판단 호스트이며 센싱 수신부는 포함하지 않습니다. 실제 입력 연결은 같은 실행
스레드에서 `runtime.ingest_location(...)`과 `runtime.run_once()`를 호출합니다.
실제 서버는 `--mode live --base-url <URL>` 또는 `HOMEVIS_BACKEND_URL`로 지정합니다.
인증 헤더와 배포별 매핑은 [IntegrationConfig](src/integration/config.py)에 주입합니다.
[.env.example](.env.example)은 참고 파일이며 자동으로 읽지 않습니다.

outbox와 출수 예약은 `output/integration/<mode>/outbox.sqlite3`에 저장합니다.
Mock과 Live 저장소는 분리되며, 재시도·재시작에서도 원본 ID와 본문을 유지하고 만료된 명령은 보내지 않습니다.
기본 정렬 지연은 2초입니다. 센싱 자체의 전환 확인과 AI 위치 확인 시간도 함께 고려해야 합니다.
시간순 기기 상태, 취침 구간 검증, 송신 재검증 및 복구 정책은 [백엔드 통합 문서](docs/backend_integration.md)를 참고하세요.

## 프로젝트 구조와 테스트

| 경로 | 역할 |
| --- | --- |
| `src/control/` | 중앙 컨트롤러, 위험 상태, 생활·안전 시나리오 |
| `src/control/confidence/` | feature·가중치·점수 및 판단 이력 |
| `src/control/feedback/`, `src/control/routine/` | 구조화·자연어 피드백과 루틴 기록 |
| `src/integration/` | 입력 변환, 백엔드 클라이언트, 시간순 런타임, outbox |
| `src/alert_service.py`, `src/llm/`, `src/voice/` | 판단 이후 안내문·TTS 경로 |
| `examples/`, `tests/` | Mock 데모, 자동 회귀 테스트, 별도 수동 실행 파일 |
| `docs/` | 세부 설계와 입력·전송 계약 |

```sh
python -m pytest -q
python -m unittest discover -s tests -v
python -m pytest -q tests/test_backend_integration.py tests/test_runtime_regressions.py
```

pytest는 unittest 클래스와 함수형 통합 테스트를 함께 실행합니다. unittest 명령만으로는 함수형 테스트가
실행되지 않습니다. 자동 테스트는 가상 시계·MockBackend·임시 저장소로 시간 경계, 관측 유효성,
출수량 전달, 취침 재검증, outbox 저장 실패, 재시도와 재시작 예약을 검증합니다.
`tests/manual_test.py`, `tests/manual_morning_water_test.py`는 로컬 모델을 사용하는 별도 수동 실행 파일입니다.

- [실시간 판단](docs/realtime_control.md): 상태 전이, 시간 기준, 직접 호출 및 JSONL 재생
- [Confidence 제어](docs/confidence_control.md): feature·가중치·threshold와 기존 피드백
- [생활·안전 시나리오](docs/scenarios.md): 취침·출수·낙상 상태와 출력 모델
- [백엔드 통합](docs/backend_integration.md): 최종 위치 계약, 행동 결합, 전송 검증과 저장 정책

## 현재 연동 범위

판단 엔진, 백엔드 HTTP 클라이언트와 Mock 경로는 구현되어 있습니다. 실제 연결에는 위치·행동 수신 방식,
출수 외 제어 라우트, 규칙 confidence 표현, 정수기 준비 상태, 출력 단계와 W의 대응,
자동 복구 제어 이력, 낙상 시작·확인·종료 API와 명령 실행 ACK 계약이 필요합니다.
기존 피드백 API는 사용할 수 있지만 백엔드 yes/no 피드백 자동 연결은 구현되어 있지 않습니다.

백엔드 서버, 실제 Wi-Fi 추론, MQTT 제어, LG OS 전용 코드와 실가전 실행 검증은 이 저장소의 구현 범위에
포함되지 않습니다. Mock 접수 결과로 실제 소등·출수·화력 변경의 완료를 판단할 수 없습니다.
