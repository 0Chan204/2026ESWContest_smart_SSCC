# HomeVIS AI 중앙 판단 및 안전 알림

HomeVIS는 Wi-Fi 센싱 추론 모듈의 최종 위치 결과와 가전 상태를 받아 위험 상태를 판단하고,
자동 제어 요청과 사용자 안내를 생성하는 Python 모듈입니다. 별도로 측정한 행동 결과가 있으면
취침 소등, 기상 기반 출수, 욕실 낙상 시나리오에도 사용합니다.

백엔드 클라이언트, 측정 시각 기반 판단 런타임, SQLite outbox, MockBackend를 포함합니다.
실제 Wi-Fi 신호 측정·분류와 가전 명령 실행은 외부 센싱 모듈 및 백엔드가 담당합니다.

## 연속 실행

Python 3.11 이상에서 한 번 설치하고 `.env.example`을 `.env`로 복사해 보드 주소를 설정합니다.

```sh
python -m pip install -r requirements-runtime.txt
python -m src.integration
```

기본은 **live·무기한 실행**입니다. MQTT `wifi/occupancy/state`와 백엔드 기기 정보를 계속 받아
탐지하고, 모든 기기 제어는 `POST /api/v1/ai/decisions`로 보냅니다. 종료는 `Ctrl+C`입니다.
브로커·백엔드·Wi-Fi 추론 서버는 실행 중이어야 합니다. 한 명령은 이 AI 수신·판단 프로세스를 실행합니다.

```sh
python -m src.integration --mode mock --duration 15
python -m src.integration --sensing-source backend
```

두 번째 명령은 백엔드에 저장된 `home/edge/result` 센싱을 HTTP로 받습니다.
설정은 [config/homevis.toml](config/homevis.toml), 상태는 `output/integration/live/status.json`에서 확인합니다.
낙상 사건 조회·재시작 복구, TTS 전달, 인증·TLS, 테스트 방법은 [연속 실행 안내](docs/continuous_runner.md)에 있습니다.
현재 팀 Wi-Fi 코드는 위치만 발행하므로 행동이 필요한 출수·취침·낙상에는 추가 실제 행동 입력이 필요합니다.
일반 전등 자동 점·소등과 인덕션 감소·복구는 기본 `location_level_v1` 프로필로
위치와 실제 기기 상태만 사용합니다. 등록된 각 구역 전등은 재실 5초/부재 30초 확인 후,
인덕션은 이탈 40초/복귀 5초 확인 후 신뢰도·안전 조건을 만족하면 백엔드에 요청합니다.
측정 시각 정렬(기본 4초)과 통신 지연은 별도로 더해집니다.

현재 위치 기반 자동화는 **사용자 1명**을 전제로 합니다. 여러 사람의 위치를 개별 추적하지 않습니다.
센싱 미수신이나 `unknown/empty`만으로 외출·부재를 확정하지 않으며, 제어에는 유효한 위치와
최신 기기 상태가 필요합니다. 인덕션을 자동으로 켜지 않습니다. 복구는 HomeVIS가 낮춘
화력이 실제 상태에 반영되었고, 사용자가 복귀했으며, 온도 등 안전 조건을 만족할 때만 요청합니다.

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

내부 요청 생성과 백엔드 전송은 별도 조건을 따릅니다. 계산된 AI confidence는 그대로 전달하고,
live 실행기의 규칙형 출력은 실제 위치·행동 입력의 신뢰도를 전송합니다. 백엔드 v0.5는 `null`을 허용하지 않습니다.
기존 직접 호출용 `IntegrationConfig()`와 Mock 데모의 `null` 정책은 호환용으로 유지합니다.
낙상 시작은 AI가 판단하고, 최초 요청 이후 단계 알림·신고 상태와 사용자 확인은 백엔드가 관리합니다.

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

연속 실행기는 Python 3.11 이상을 사용합니다. 명령은 `README.md`, `src/`, `tests/`가 있는 저장소 루트에서
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

`room`은 기본적으로 취침·기상 판단에 쓰는 방입니다. 이 기존 Mock 데모는 `idle`을 출수 준비 조건으로 쓰지 않습니다.
데모는 별도의 가상 기기 준비 필드 `mock_readiness=ready`를 사용하며, 이는 실제 백엔드 필드가 아닙니다.
규칙 confidence의 `null`은 이 기존 Mock 데모의 호환 정책이며 실제 백엔드 v0.5에 전송하지 않습니다. 출수량은 `ScenarioConfig`의 120mL 기본값을 사용합니다.
낙상에 필요한 motion/fall 정보는 이 데모에도 없습니다.

기본 데모 저장소는 임시 디렉터리입니다. `--data-dir output/demo`를 추가하면 outbox와 일일 예약을
유지합니다. 같은 날 같은 저장소에서 재실행하면 예약 때문에 새 출수 요청이 생성되지 않을 수 있습니다.

선택적 안내·음성 경로는 다음과 같이 확인합니다.

```sh
python test_realtime.py --llm none --tts dry-run
```

`dry-run`은 테스트용 WAV를 생성하며 파일을 자동 재생하지 않습니다.
실제 OS 음성은 `--tts pyttsx3`를 사용합니다. `python -m pip install -r requirements.txt`는
선택적 TTS, Gemini·EXAONE·GPT API 의존성을 설치합니다. Gemini adapter는 Vertex AI의 `GOOGLE_CLOUD_PROJECT`와
선택적인 `GOOGLE_CLOUD_LOCATION`을 사용합니다. Qwen adapter는 별도 로컬 모델과
`torch`, `transformers`, `accelerate`가 필요합니다. `llama` adapter는 placeholder입니다.
기본 `--llm none` 경로는 이러한 모델과 인증을 요구하지 않습니다.

## Qwen / EXAONE / GPT 선택

EXAONE은 로컬 모델을 다운로드하거나 GPU에 적재하지 않고 FriendliAI의 OpenAI 호환 Chat Completions
API를 사용합니다. 공통 `BaseLLMAdapter` 계약을 사용하므로 기존 안내문 생성, 위험 경고, TTS 입력 및
자연어 피드백 JSON 해석 호출부는 모델 차이를 알 필요가 없습니다. EXAONE 요청이 실패하면 기존
`LLMMessageGenerator`는 중앙 판단 결과를 바꾸지 않고 기본 안내문을 사용합니다. Qwen을 자동으로
대체 로딩하지 않습니다.

의존성을 설치합니다.

```sh
python -m pip install -r requirements.txt
```

PowerShell에서 EXAONE을 선택하는 예시는 다음과 같습니다. 연속 실행기는 `.env`도 읽습니다.
기존 개별 예제·연결 테스트는 아래처럼 실행 환경에 변수를 설정합니다.

```powershell
$env:LLM_PROVIDER = "exaone"
$env:FRIENDLI_API_KEY = "<FriendliAI Personal API Key>"
$env:EXAONE_MODEL = "LGAI-EXAONE/EXAONE-4.0-32B"
$env:EXAONE_BASE_URL = "https://api.friendli.ai/serverless/v1"
python test_alert.py --risk WARNING --tts dry-run
```

Linux/macOS에서는 다음과 같이 설정합니다.

```sh
export LLM_PROVIDER=exaone
export FRIENDLI_API_KEY='<FriendliAI Personal API Key>'
python test_alert.py --risk WARNING --tts dry-run
```

기존 로컬 Qwen은 `LLM_PROVIDER=qwen` 또는 명령행의 `--llm qwen`으로 선택합니다. 명령행
`--llm` 값이 환경변수보다 우선합니다. `LLM_PROVIDER`가 없으면 기존과 동일하게 `none`이 기본이며,
API나 로컬 모델 없이 기본 안내문을 사용합니다.

| 환경변수 | 기본값 | 의미 |
| --- | --- | --- |
| `LLM_PROVIDER` | `none` | `none`, `qwen`, `exaone`, `gpt` 등 provider 선택 |
| `FRIENDLI_API_KEY` | 없음 | EXAONE 선택 시 필수인 Personal API Key |
| `EXAONE_MODEL` | `LGAI-EXAONE/EXAONE-4.0-32B` | FriendliAI 모델 ID |
| `EXAONE_BASE_URL` | `https://api.friendli.ai/serverless/v1` | OpenAI 호환 API base URL |
| `EXAONE_TIMEOUT_SECONDS` | `30` | 요청별 timeout(초) |
| `EXAONE_MAX_RETRIES` | `2` | SDK가 네트워크 오류·429·서버 오류에 수행할 제한적 재시도 수 |
| `EXAONE_MAX_TOKENS` | `256` | 최대 응답 토큰 수 |
| `EXAONE_TEMPERATURE` | `0.3` | 생성 temperature |

Mock 테스트는 API 키 없이 실행됩니다.

```sh
python -m unittest tests.test_exaone_adapter -v
```

실제 FriendliAI 연결 테스트는 키가 설정된 경우에만 명시적으로 실행합니다. 기본 테스트 실행에서는
건너뛰므로 비용이나 외부 요청이 발생하지 않습니다.

```powershell
$env:RUN_EXAONE_API_TEST = "1"
python -m unittest tests.test_exaone_adapter.EXAONELiveAPITest -v
```

기존 HomeVIS 확인 명령인 `test_alert.py`와 `test_realtime.py`에서 그대로 `--llm exaone`을 사용할 수
있으며 EXAONE 전용 실행 파이프라인은 없습니다. 실제 키는 저장소에 기록하지 마세요. `.gitignore`는
`.env`와 `.env.*`를 제외하고 예시 파일 `.env.example`만 추적하도록 설정되어 있습니다.

### OpenAI GPT API

GPT도 동일한 `BaseLLMAdapter.generate(system_prompt, user_prompt)` 경로를 사용합니다.
OpenAI Docs의 [Responses API](https://developers.openai.com/api/docs/guides/text)를 기준으로
기존 system/user 프롬프트를 전달하고, 완료된 assistant 메시지의 `output_text` 부분만 추출합니다.
reasoning 항목·거절·잘린 응답·빈 응답은 TTS나 피드백 JSON으로 전달하지 않습니다.
`store=False`로 응답 저장을 요청하지 않지만, 이것이 공급자의 모든 로그 보존을 비활성화한다는 뜻은 아닙니다.

먼저 `python -m pip install -r requirements-runtime.txt`로 의존성을 설치/갱신합니다.
Responses API를 지원하는 `openai>=1.68,<3`가 필요하며 GPT는 로컬 모델이나 GPU를 사용하지 않습니다.
Qwen·EXAONE 구현과 중앙 판단·가중치·기기 제어·TTS 모듈은 그대로 유지됩니다.

`.env`에서 다음 값을 설정하고 **기존과 동일하게** `python -m src.integration`을 실행합니다.

```ini
LLM_PROVIDER=gpt
OPENAI_API_KEY=<OpenAI API 키>
OPENAI_MODEL=<계정에서 사용할 수 있는 Responses API 지원 GPT 모델 ID>
OPENAI_TIMEOUT_SECONDS=30
OPENAI_MAX_RETRIES=2
OPENAI_MAX_OUTPUT_TOKENS=2048
```

모델 ID는 의도치 않은 모델·비용 선택을 피하도록 필수 설정으로 두었습니다.
`OPENAI_API_KEY`는 FriendliAI 키와 별개이며 코드·Git·로그에 넣지 마세요.
전송 주소는 `https://api.openai.com/v1`로 고정되어 다른 용도의 `OPENAI_BASE_URL`을 상속하지 않습니다.
GPT를 선택한 경우에만 키·모델을 검사하며, `LLM_PROVIDER` 미설정 시 기존 `none` 동작을 유지합니다.

timeout은 요청별 양의 유한 초 값이고, SDK 재시도는 기본 2회(설정 범위 0~5회)입니다.
연결 장애·timeout·429·서버 오류 등 SDK의 제한적 재시도 후에도 실패하면 기존 기본 안내문을 사용합니다.
인증/권한, 잘못된 설정, timeout, 서비스 장애, 비정상 응답을 구분하며 다른 모델을 자동 로딩하지 않습니다.
자연어 피드백 실패는 기존 정책대로 `unknown`으로 처리합니다. 키/모델 누락 등 초기 설정 오류는
어댑터 생성 오류로 보고하며, 연속 실행기의 별도 안내 작업 실패가 중앙 제어 판단을 변경하지 않습니다.

`OPENAI_MAX_OUTPUT_TOKENS`는 reasoning 모델의 추론 토큰도 포함합니다. 토큰 부족으로 응답이
잘리면 기본 안내문으로 처리되므로 모델에 맞게 조정하세요. 모델별 temperature/reasoning 옵션을
강제하지 않으며, Responses API를 지원하지 않는 모델은 설정 오류로 처리합니다.

키가 필요 없는 테스트:

```sh
python -m pytest -q tests/test_gpt_adapter.py tests/test_exaone_adapter.py
```

실제 API 연결 테스트는 아래처럼 **명시적으로 실행할 때만** 요청하며 비용이 발생할 수 있습니다.
단독 pytest/예제는 `.env`를 자동으로 읽지 않으므로 환경변수를 설정합니다.

```powershell
$env:OPENAI_API_KEY = "<OpenAI API 키>"
$env:OPENAI_MODEL = "<사용할 GPT 모델 ID>"
$env:RUN_GPT_API_TEST = "1"
python -m pytest -q tests/test_gpt_adapter.py -k live_gpt_api
Remove-Item Env:RUN_GPT_API_TEST
```

Linux/macOS에서는 키와 모델을 `export`한 뒤
`RUN_GPT_API_TEST=1 python -m pytest -q tests/test_gpt_adapter.py -k live_gpt_api`로 실행합니다.
기존 개별 예제도 `python test_alert.py --risk WARNING --llm gpt --tts dry-run` 또는
`python test_realtime.py --llm gpt --tts dry-run`으로 선택할 수 있습니다. 이 예제들은 실제 API를 호출합니다.
연속 실행기의 `--mode mock`은 기존대로 LLM을 사용하지 않습니다.

## 주요 설정과 신뢰도 계산

연속 실행기의 기본 프로필은 `location_level_v1`입니다. 다음 운영 값은
[config/homevis.toml](config/homevis.toml)의 `[backend]`에서 설정합니다.

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `automation_profile` | `location_level_v1` | 현재 위치·기기 단계 입력용 점수. `legacy`로 기존 점수 선택 가능 |
| `automation_absence_seconds` | 40초 | 화력 감소를 위한 최소 주방 이탈 시간 및 시간 feature의 최대 점수 기준 |
| `automation_return_seconds` | 5초 | 화력 복구를 위한 복귀 확인 시간 |
| `light_on_seconds` / `light_off_seconds` | 5초 / 30초 | 일반 전등 점등·소등을 위한 확인 시간 |
| `multi_room_lights` | `true` | 백엔드에 등록된 room/kitchen/toilet의 전등을 각각 제어 |
| `stove_reduce_steps` | 1단계 | 현재 화력보다 낮출 단계 수. 최저 1단계 미만으로 낮추지 않음 |

위험 상태와 시나리오의 기존 기본값은 별도 설정입니다.

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `KITCHEN_SHORT_ABSENCE` | 20초 | 주방 이탈 주의 기준 |
| `KITCHEN_WARNING_TIME` | 40초 | 주방 이탈 경고 기준 |
| `KITCHEN_DANGER_TIME` | 60초 | 주방 장시간 이탈 위험 기준 |
| `KITCHEN_LEAVE_FULL_SECONDS` | legacy: 60초 / 운영: 40초 | 이탈 시간 feature의 최대 점수 기준. 운영 시 위 설정으로 주입 |
| `MORNING_WATER_AMOUNT_ML` | 120mL | 새로 생성하는 기본 자동 출수 요청량 |

위험 단계는 프로그램 시작 시간이 아니라 엔진이 추적하는 주방 이탈 경과시간을 기준으로 합니다.
고출력·온도 상승이나 긴급 신호가 있으면 더 높은 단계가 먼저 발생할 수 있습니다.
위치·복귀 확인 시간, 센싱·기기 timeout, 신뢰도 검증은 계속 적용됩니다.
불확실한 입력만으로 기존 위험 상태를 정상으로 해제하지 않습니다.

운영 프로필의 화력 감소 초기 점수는 다음 가중합입니다. 각 항목은 0~1 범위입니다.

```text
confidence = 0.30 × 위치 신뢰도
           + 0.30 × clamp(이탈 초 / 40, 0, 1)
           + 0.10 × (관측된 화력 단계 / 9)
           + 0.20 × 센싱 일관성
           + 0.10 × 피드백 점수
```

위치 신뢰도·일관성이 각각 0.95, 이탈 40초, 화력 5단계, 기본 피드백 0.5이면 약 **0.881**입니다.
감소 기준 **0.82**를 낮추지 않고 실제 관측 가능한 항목으로 도달할 수 있게 했습니다.
전등 기준도 켜기 0.72 / 끄기 0.78, 복구 기준도 0.80으로 유지합니다. 점수는 확률이 아닌
정책 점수이며, 사용자 피드백 학습 후에는 가중치가 달라질 수 있습니다.
점수 외에도 최소 확인 시간·유효한 센싱·최신 기기 상태 등 실행 조건을 모두 만족해야 합니다.

`legacy`는 기존 가중치와 `clamp(이탈 초 / 60, 0, 1)` 계산을 그대로 보존합니다.
이 프로필에서는 전력(W)·행동 입력이 부족하면 제어 기준에 도달하지 못할 수 있습니다.
새 프로필의 가중치·피드백 파일은 기존 파일과 분리하여 과거 학습값을 덮어쓰지 않습니다.
`reduce_power`는 백엔드의 `set_level` 요청이며 특정 온도만큼 낮추거나 전원을 끄는 명령이 아닙니다.

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
| `toilet` | `toilet` |
| `room` | `room`: 취침·기상 판단에 사용하는 방 |
| `empty`, `unknown` | 내부 위치는 `unknown`, 원본 의미는 각각 보존. `outside`로 변환하지 않음 |
| `r2/r3/r4` 등 미등록 값 | 장소로 해석하지 않고 무효 관측으로 진단 |

`time`은 시간대가 있는 측정 시각이며 조회 시각으로 덮어쓰지 않습니다. 같은 측정 결과는 중복 관측으로
누적하지 않습니다. `unknown`의 원본 `null` confidence, `node_offline:r3`나 `config_mismatch` 등의
전체 `reason`, 관측 유효 여부를 별도로 보존합니다. 명시적 무효 결과와 메시지 미수신 timeout을 구분하며,
마지막 확인 위치만으로 현재 유효한 재실을 주장하지 않습니다.

위치 JSON에는 `activity`, `motion_state`, `fall_detected`가 없습니다. 취침·기상·낙상 기능은 필요한
실제 행동 입력이 별도로 있어야 하며, 미측정 행동의 confidence 기여도는 0입니다.
[BehaviorObservation](src/integration/sensing.py)은 행동의 측정 시각·만료·공간·유효성을 검사하는
입력 경계입니다. 연속 실행기는 백엔드 결과 또는 설정한 별도 MQTT 행동 토픽을 이 경계에 연결합니다.
센싱 행동은 `ingest_location(..., behavior=...) → SensingUpdate.activity`로 반영됩니다.
실제 `idle → sitting/lying` 측정이 들어오면 사용자 행동만 갱신하며 기기의 전원·level·출수 기록은 바꾸지 않습니다.
위치만 있으면 행동은 `unknown`/미관측이며, GET 응답의 status를 행동 측정으로 복제하지 않습니다.

사용하는 백엔드 API는 다음과 같습니다.

- `GET /api/v1/ai/device-states`: 전체 기기 상태를 `items` 배열 한 응답으로 조회 (`device`와 `deviceId`로 식별)
- `POST /api/v1/ai/decisions`: 판단과 제어 요청 전달

출수량은 `ScenarioConfig.MORNING_WATER_AMOUNT_ML` → `DeviceCommand.amount_ml` →
`actions[].amountMl`로 전달됩니다. 기기 이름은 입력·판단·출력에서
`stove`, `light`, `water_purifier`를 사용하고, 조명 대상 공간은 `room` 필드에 따로 저장합니다.

GET 응답의 `items[]`에서 `device/deviceId/room/online/is_on/current_state/control_state/updatedAt`을
읽습니다. `room` 관측은 취침·기상에 연결되고, 전등 상태와 공간은 조명 평가·송신 재검증에 사용합니다.
인덕션 `level`은 모델과 판단 결과에 단계 값으로 보존합니다. 운영 프로필은 확인된 백엔드 범위 1~9를
단계 feature로 사용하며 W로 환산하지 않습니다. 기존 `legacy` 평가도 설정으로 선택할 수 있습니다.
`temperature`는 원문을 보존하며, live 프로필에서는 백엔드 스키마에서 확인한 섭씨 단위를 사용합니다.
백엔드의 `user/homevis/null`은 원본 제어 주체로 보존하고, 화력 감소·사용자 개입 상태로 임의 변환하지 않습니다.

### 전체 요청과 서버 응답 예시

아래는 부분 필드 예시가 아닌 **실제 Mock 데모가 직렬화한 전체 POST 본문**입니다.
가상 시각을 `2026-10-17T07:00:00+09:00`로 고정한 별도 행동 데모에서 생성됩니다.
이 예시는 기존 직접 호출용 Mock 호환 정책의 `confidence=null`을 사용하며 live 전송 예시가 아닙니다.
현재 실행기는 백엔드 모델에 맞춰 규칙 출력에도 측정된 입력 신뢰도를 넣습니다. 기존 가중합 점수는 유지합니다.
아래 예시는 Mock 검증 결과이며, 실서버 검증을 수행했다는 뜻은 아닙니다.

<!-- mock-water-request -->
```json
{
  "actions": [
    {
      "action": "dispense",
      "amountMl": 120,
      "device": "water_purifier"
    }
  ],
  "confidence": null,
  "decisionId": "dec-decb4866358b7e4f69a9f1108dbdada0",
  "reason": "Confirmed morning wake-up and kitchen stay",
  "room": "kitchen",
  "scenario": "water_dispense",
  "timestamp": "2026-10-16T22:00:12+00:00",
  "weatherBriefing": true
}
```

다음은 위 요청에 대한 **Mock 서버의 전체 HTTP 202 응답**입니다. 식별자와 날씨는 테스트 값입니다.

<!-- mock-water-response -->
```json
{
  "actions": [
    {
      "action": "dispense",
      "commandId": "mock-cmd-dec-decb4866358b7e4f69a9f1108dbdada0-0",
      "device": "water_purifier",
      "deviceId": "mock-device",
      "message": null,
      "status": "sent"
    }
  ],
  "confidence": null,
  "decisionId": "dec-decb4866358b7e4f69a9f1108dbdada0",
  "duplicate": false,
  "eventId": "mock-evt-dec-decb4866358b7e4f69a9f1108dbdada0",
  "fallIncidentId": null,
  "feedback": null,
  "receivedAt": "2026-10-16T22:00:12+00:00",
  "scenario": "water_dispense",
  "weather": {
    "available": true,
    "stale": false,
    "text": "Mock weather (not live)"
  }
}
```

동일한 ID와 본문을 다시 보내면 HTTP 200과 `duplicate: true`를 확인합니다.
`sent`는 명령 전송 상태이며 실제 기기 실행 완료를 뜻하지 않습니다.
`rejected/failed` 및 오류 메시지는 저장하며, 실패한 동작을 새 ID로 임의 재실행하지 않습니다.
위 예시는 `tests/test_backend_contract.py`에서 데모의 전체 요청·응답과 일치하는지 검사합니다.

### 제공된 명세로 확정된 범위와 확인할 사항

| 항목 | 현재 처리와 필요한 확인 |
| --- | --- |
| 구역·기기 | `room/kitchen/toilet`, `stove/light/water_purifier`를 기준으로 사용 |
| 출수 요청 | `water_dispense / water_purifier / dispense`, AI가 결정한 수량과 `weatherBriefing` 전달 |
| 정수기 준비 상태 | live는 기기의 `status=idle`·online·freshness 확인. 사용자 행동과 구분 |
| 온도·출력 | 섭씨 및 level 1~9 확인. W 환산은 검증된 설정이 있을 때만 적용 |
| confidence | 기존 점수 유지. live 규칙 출력은 관측 신뢰도, 직접 호출용 Mock은 기존 null 정책 |
| 출수 외 제어 | 전등 on/off, stove_absence의 set_level/restore_power로 연결 |
| 낙상 | fall_detected 1회 전송, 백엔드 사건 조회로 resolved 반영. 단계 타이머는 백엔드 소유 |

기존 `bedroom/bathroom/water_dispenser` 입력은 경계에서 표준 이름으로 정규화합니다.
이미 저장된 요청의 ID·본문·원본 source·과거 출수 기록은 변경하지 않습니다.
`outside/unknown/entrance/living_room` 같은 내부 상태도 유지합니다.
기존 `bathroom_fall` 시나리오·피드백 키와 클래스 이름은 이력 호환용이며 백엔드 API의 허용값을 의미하지 않습니다.
낙상 `RECOVERED`도 `fall_state_changed` 로컬 기록에 측정 시각과 함께 남깁니다.
이 판단만으로 백엔드 사건을 닫거나 신고 중단을 주장하지 않으며, 중복 후속 대응도 전송하지 않습니다.

```sh
python -m src.integration --mode mock --duration 3
```

이 CLI는 MQTT 또는 백엔드 HTTP 센싱 수신, 기기 조회, 주기적 판단, 전송을 함께 실행합니다.
실제 서버는 `--mode live --base-url <URL>` 또는 `HOMEVIS_BACKEND_URL`로 지정합니다.
인증은 환경변수, 배포별 매핑은 [실행 설정](config/homevis.toml)에서 지정합니다.
`.env`는 자동으로 읽고 기존 OS 환경변수를 우선합니다.

outbox와 출수 예약은 `output/integration/<mode>/outbox.sqlite3`에 저장합니다.
Mock과 Live 저장소는 분리되며, 재시도·재시작에서도 원본 ID와 본문을 유지하고 만료된 명령은 보내지 않습니다.
실행기 정렬 지연은 4초, 기존 직접 호출 기본값은 2초입니다. 센싱 자체의 전환 확인 시간도 고려해야 합니다.
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
python -m pytest -q tests/test_backend_contract.py tests/test_backend_integration.py tests/test_runtime_regressions.py
python -m pytest -q tests/test_location_level_automation.py tests/test_runner_network.py
python -m pytest -q tests/test_gpt_adapter.py tests/test_exaone_adapter.py
```

pytest는 unittest 클래스와 함수형 통합 테스트를 함께 실행합니다. unittest 명령만으로는 함수형 테스트가
실행되지 않습니다. 자동 테스트는 가상 시계·MockBackend·임시 저장소로 시간 경계, 관측 유효성,
출수량 전달, 취침 재검증, outbox 저장 실패, 재시도와 재시작 예약을 검증합니다.
`test_backend_contract.py`는 실제 HTTP 클라이언트를 로컬 테스트 서버에 연결해 경로·본문·중복 응답을
확인하고 README의 전체 JSON을 데모 결과와 대조합니다. 배포된 실제 백엔드나 실가전 검증은 아닙니다.
`tests/manual_test.py`, `tests/manual_morning_water_test.py`는 로컬 모델을 사용하는 별도 수동 실행 파일입니다.

`test_location_level_automation.py`는 위치만으로 전등 점·소등, 화력 감소·복귀 복구, 구역별 여러 전등,
반복 이탈·재시작·안전 차단을 검증합니다. `test_gpt_adapter.py`는 프롬프트와 TTS/피드백 계약,
오류 분류·비정상 응답·로컬 모델 미로딩 및 가짜 HTTP를 통한 SDK 재시도 한도를 검증합니다.
실제 GPT/EXAONE 호출은 위에서 안내한 별도 환경변수로 명시적으로 활성화할 때만 수행합니다.

- [실시간 판단](docs/realtime_control.md): 상태 전이, 시간 기준, 직접 호출 및 JSONL 재생
- [Confidence 제어](docs/confidence_control.md): feature·가중치·threshold와 기존 피드백
- [생활·안전 시나리오](docs/scenarios.md): 취침·출수·낙상 상태와 출력 모델
- [백엔드 통합](docs/backend_integration.md): 최종 위치 계약, 행동 결합, 전송 검증과 저장 정책

## 현재 연동 범위

팀 백엔드 develop의 AI 연동 v0.5와 실제 Wi-Fi 토픽을 확인해 연속 실행기에 연결했습니다.
낙상 최초 결정, 기기 제어, 위험·낙상 안내 문장은 백엔드 API로 전달합니다. 백엔드의
사용자/보호자 응답은 사건 조회로 반영하며 AI가 2·3차 문자·신고 타이머를 중복 수행하지 않습니다.
기존 LLM/TTS를 별도 작업 스레드에서 사용하고 문장은 `announcement`로 대시보드에 전달합니다.
로컬 WAV 자동 재생은 하지 않습니다. 직접 컨트롤러 호출의 기존 내부 단계 API는 유지합니다.
기존 피드백 API는 사용할 수 있지만 백엔드 yes/no 피드백 자동 연결은 구현되어 있지 않습니다.

행동이 필요한 기상 출수·취침·낙상은 실제 행동 입력이 있어야 합니다. 일반 전등과 인덕션 감소·복구에는
행동·W 입력이 필요하지 않습니다. W 기반 위험 평가 항목에는 여전히 실제 전력 측정/검증된 환산이 필요합니다.
확인한 백엔드의 자동 신고는 상태·이벤트 기록까지이며 실제 119 연동은 미구현입니다.
MQTT/HTTP 로컬 소켓과 백엔드 모델 검증은 실가전·LG OS 보드 실증을 대신하지 않습니다.
`sent` 응답만으로 실제 소등·출수·화력 변경 완료를 판단하지 않습니다.
