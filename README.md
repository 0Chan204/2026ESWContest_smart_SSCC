# HomeVIS AI

Wi-Fi 센싱의 **최종 재실·행동 추론 결과**와 백엔드의 기기 상태를 받아 생활·안전 시나리오를 판단하는 Python 프로젝트입니다.
사용자 1명이 거주하는 환경을 기준으로 연속 탐지, 자동 제어 요청, 안내문 생성, 선택적 음성 상호작용을 제공합니다.

**실제 가전 제어는 전부 백엔드가 수행합니다.** AI는 `POST /api/v1/ai/decisions`로 판단을 전달하며 기기 MQTT command 토픽에 직접 발행하지 않습니다.
Wi-Fi 신호 수집·모델 학습, 공기질 임계값 판단, 백엔드·DB 운영은 이 프로젝트의 역할이 아닙니다.

이 문서는 **2026-10-27 현재 작업 트리** 기준입니다. 원격 저장소 반영과 실제 보드 배포는 별도이며,
기능이 구현되어 있다는 것과 실기기 연동이 완료되었다는 것은 구분해야 합니다.

ARM64 Docker 배포 파일과 외부 LLM 장애 대응은 [배포·검증 안내](docs/arm64_deployment.md)를 참고하세요.
Docker가 있는 환경에서는 배포 안내의 `docker buildx build`와 Compose 명령으로 빌드하고 실행합니다.
현재 작업 환경에서는 Docker가 없어 이미지 빌드·실제 보드 실행은 아직 확인하지 못했습니다.

## 1. 먼저 확인할 현재 상태

연속 실행기는 구현되어 있지만, 아래 연동 조건 때문에 지금 모든 기능을 실기기에서 자동 실행할 수 있는 상태는 아닙니다.

| 항목 | 현재 상태 |
| --- | --- |
| 연속 수신·판단·전송 | 센싱 HTTP GET, 기기 상태 GET, 판단 POST를 한 프로세스에서 반복 |
| Wi-Fi → 백엔드 연결 | 양쪽 토픽·JSON이 달라 변환 연결이 필요. AI 실행만으로 해결되지 않음 |
| 인덕션 화력 감소 | 최신 상태·재실·점수 조건을 만족하면 요청 가능 |
| 인덕션 켜기·화력 증가·복구 | 온도 유효성 계약 미확인으로 **live 기본 보류**. 자동 복구도 포함 |
| 조리 중 공기청정기 ON | 유효한 기기 상태가 있으면 요청 가능. 임베디드가 다시 끄지 않도록 유지하는 계약은 미확정 |
| 조리 종료 후 공기청정기 OFF | 로직은 구현. 현재 백엔드 GET에 명령 출처가 없어 **운영에서는 보류** |
| 외출 전체 OFF | 로직은 구현. 집 전체 부재 의미 확인 전까지 **기본 보류** |
| 행동 기반 기상·취침·낙상 | 실제 행동 입력 필요. 현재 확인한 Wi-Fi main은 위치만 발행 |
| 음성 상호작용 | 선택 기능, 기본 OFF. 백엔드 STT·확인·TTS와 LLM 설정 필요 |
| 자동 신고 | 확인한 백엔드는 상태·이벤트 기록까지 구현. 실제 119 신고 연동은 별도 |

안전 확인용 설정을 단순히 `true`로 바꾸어 미확인 연동을 우회하지 마세요.
구체적인 팀 확인 사항은 [배포 전 확인](#10-배포-전-확인)을 참고하세요.

## 2. 설치와 실행

### 환경 준비

Python **3.11 이상**을 사용합니다. 아래 명령은 `README.md`, `src/`, `tests/`가 있는 저장소 루트에서 실행합니다.
백엔드·센싱 생산자, MQTT 사용 시 브로커는 별도로 실행되어 있어야 합니다.

```sh
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-runtime.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

Linux/macOS (`python`이 없으면 `python3` 사용):

```sh
source .venv/bin/activate
python -m pip install -r requirements-runtime.txt
[ -f .env ] || cp .env.example .env
```

PowerShell에서 활성화가 제한되면 이후 명령의 `python` 대신 `.\.venv\Scripts\python.exe`를 사용합니다.
기존 `.env`는 덮어쓰지 말고 [.env.example](.env.example)의 추가 항목을 확인하세요.

### 백엔드 주소 설정

`.env`에서 실제 서버 주소를 지정합니다. AI가 보드 밖에서 실행된다면 `localhost`가 아닌 보드 주소를 사용하세요.

```ini
HOMEVIS_MODE=live
HOMEVIS_BACKEND_URL=http://localhost:8000
HOMEVIS_BACKEND_TOKEN=
HOMEVIS_SENSING_SOURCE=backend
HOMEVIS_MQTT_HOST=localhost
HOMEVIS_MQTT_PORT=1883
HOMEVIS_MQTT_USERNAME=
HOMEVIS_MQTT_PASSWORD=
HOMEVIS_VOICE_ENABLED=false
LLM_PROVIDER=none
```

`HOMEVIS_BACKEND_URL`에는 서버 기본 주소를 넣습니다. `/api/v1` 경로는 클라이언트가 붙입니다.
토큰·API 키·MQTT 비밀번호는 실제 값을 저장소에 작성하지 않습니다.

### 먼저 Mock으로 확인

```sh
python -m src.integration --check-config
python -m src.integration --mode mock --duration 15
python -m src.integration --mode mock --mock-scenario fall --duration 15
```

Mock은 가상 센싱·백엔드를 사용하며 실제 MQTT·가전·유료 LLM에 연결하지 않습니다.
`--check-config`는 로컬 설정 형식을 검사할 뿐 서버 연결이나 API 키의 유효성을 확인하지 않습니다.

### 실제 연속 실행: 명령어 하나

연결·안전 조건을 확인한 뒤 실행합니다.

```sh
python run_homevis.py
```

기본은 **live·무기한 실행**, 종료는 `Ctrl+C`입니다. 이 명령은 **AI 프로세스만** 실행합니다.
백엔드 Docker Compose, MongoDB, Mosquitto, Wi-Fi 추론 프로그램까지 함께 시작하지는 않습니다.
`run_homevis.py`는 기존 `python -m src.integration`과 같은 통합 실행기를 호출합니다.
어느 작업 폴더에서 파일을 실행해도 이 프로젝트의 `.env`·설정·저장 폴더를 사용합니다.
`--duration`을 지정하지 않으면 시간 제한이 없습니다. 콘솔을 닫으면 프로세스도 종료됩니다.

기존 `.env`에 MQTT 센싱 모드가 남아 있다면 `HOMEVIS_SENSING_SOURCE=backend`로 변경하거나 다음처럼 명시합니다.

```sh
python -m src.integration --sensing-source backend
```

직접 Wi-Fi 위치 MQTT를 받는 기존 경로는 `--sensing-source mqtt`로 선택할 수 있습니다.
HTTP 오류 시 자동으로 MQTT 경로로 전환하지 않으며, 어느 모드든 가전 제어는 백엔드를 거칩니다.

## 3. 데이터 흐름과 역할

```text
Wi-Fi 센싱·추론
   │  최종 위치 / 실제 행동 결과
   │  ※ Wi-Fi → 백엔드 형식 변환 연결은 팀 확인·구현 필요
   ▼
백엔드 센싱 저장 ── HTTP GET (기본 1초) ──┐
백엔드 기기 상태 ── HTTP GET (기본 2초) ──┼→ AI 유효성 검사·시간 정렬
                                        │     ├─ 중앙 판단·confidence·시나리오
                                        │     └─ 조리 공청기·전체 외출 규칙
                                        │                ↓
                                        │       SQLite Outbox·송신 재검증
                                        │                ↓
                                        └──── POST /api/v1/ai/decisions
                                                         ↓
                                                  백엔드 → 실제 가전

선택: 백엔드 STT → MQTT home/voice/request → AI 의도·안전 검증
                                              └→ 같은 판단 POST → 백엔드 확인·TTS·제어
```

| 경로 | 사용 목적 |
| --- | --- |
| `GET /api/v1/sensing/results` | `since`·`limit` 기반 센싱 이력 반복 조회 |
| `GET /api/v1/ai/device-states` | 기기 상태를 `items` 배열로 조회 |
| `POST /api/v1/ai/decisions` | 제어·안내·음성 판단 전달 |
| `GET /api/v1/fall-incidents/{incident_id}` | 백엔드가 관리하는 낙상 진행·종료 확인 |
| `GET /api/v1/sensing/results/latest` | 음성 재실 질문 등에 최신 센싱 조회 |
| `home/voice/request` | 선택적 음성 입력 MQTT 토픽 |

Pi의 원시 CSI나 `features` 배열을 중앙 판단기에 직접 넣지 않습니다.
기기 상태의 `is_on/current_state/control_state/updatedAt`은 사용자 행동 관측과 별개로 처리합니다.
`level`은 화력 단계이며 W로 임의 환산하지 않습니다.

### 재실·행동 의미

- 구역은 `room`(방), `kitchen`(주방), `toilet`(화장실)입니다.
- `unknown/empty`, 센서 오프라인, 메시지 미수신만으로 집 전체 외출을 확정하지 않습니다.
- 행동 클래스는 제공된 학습 결과의 `none/fall/lie_down/get_up`을 처리합니다.
- `none`은 대상 이벤트 없음입니다. 부재·정지·낙상 회복을 뜻하지 않습니다.
- `lie_down`은 눕는 이벤트이지 지속 자세 `lying`이나 `motion_state=still`이 아닙니다.
- 위치와 행동의 신뢰도·측정 시각·유효성을 구분하며, 누락된 행동이나 설명을 만들어 넣지 않습니다.

현재 Wi-Fi의 `wifi/occupancy/state`는 `time/location/location_confidence`,
백엔드 입력 `home/edge/result`는 `observedAt/room/confidence` 등 다른 계약을 사용합니다.
**토픽 이름만 변경해서는 연결되지 않습니다.** 행동 생산자의 실제 JSON과 정상 추론 이유 필드도 합의가 필요합니다.

제공된 학습 로그의 이벤트 단위 감지율은 낙상 43%, 눕기 14%, 기상 21%였습니다.
전체 정확도 92.6%를 낙상 안전 성능으로 해석하지 않으며, 학습 모델의 임계값을 중앙 정책에 일괄 복사하지 않습니다.
자세한 내용은 [Wi-Fi 행동 연동](docs/wifi_behavior.md)을 참고하세요.

## 4. 자동화 시나리오

아래 시간은 기본 설정입니다. 시간만 채워서는 실행하지 않으며 최신 입력·기기 상태·신뢰도·송신 재검증을 통과해야 합니다.
측정 시각 정렬 지연(기본 4초), 센싱 자체 확인 시간, 통신 지연은 별도로 발생합니다.

| 시나리오 | 판단 조건과 요청 |
| --- | --- |
| 일반 전등 ON/OFF | 등록된 구역 전등에 대해 재실 5초 / 부재 30초 확인 후 점수 기준을 만족하면 요청 |
| 주방 이탈 화력 감소 | 인덕션 사용 중 주방 이탈 40초 확인 후 현재보다 1단계 감소, 최저 1단계. 전원 OFF와 다름 |
| 주방 복귀 화력 복구 | 복귀 5초, HomeVIS 감소 이력·실제 반영 상태·안전 조건 필요. **live 온도 검증 전 보류** |
| 취침 소등 | 방에서 실제 지속 `lying` 관측이 600초 유지. `lie_down` 이벤트만으로 실행하지 않음 |
| 아침 방 전등 | 방의 유효한 `get_up`(행동 신뢰도 ≥0.9) 또는 기존 자세 기반 기상 확인 후 허용 아침 시간대에 요청. 출수와 독립 |
| 아침 물 출수 | 기상·주방 체류·시간대·정수기 online/최신 idle 상태 확인 후 기본 120mL, 하루 최대 1회 |
| 화장실 낙상 | `toilet`의 명시적 낙상·기존 실제 자세 전이 경로. 눕기 이벤트는 별도 의심 후보로 처리 |
| 조리 공기청정기 | 인덕션 ON + 최신 유효한 공청기 OFF이면 `cooking_air_clean` ON 요청, 조리 구간당 중복 방지 |
| 외출 전체 OFF | 검증된 집 전체 `empty`를 처음 수신한 처리 주기에 `away_all_off`, `actions=[]`. **전체 부재 계약 확인 전 보류** |

아침 기본 시간대는 06:00~10:00(KST)이며, 충분한 기상 기록이 쌓이면 기존 기상 패턴 창을 사용합니다.
출수의 주방 체류 기본값은 5초입니다. 세부 조건은 [ScenarioConfig](src/control/scenario_config.py)에 있습니다.
날씨 안내 요청은 백엔드로 전달하며 날씨 수집·저장·문장 생성은 백엔드 역할입니다.

### 낙상 대응

화장실 `lie_down`은 위치·행동 신뢰도가 각각 0.8 이상일 때 로컬 의심 후보로만 기록합니다.
그 뒤 **별개의 실제 still 관측**이 5초 구간을 채워야 기존 낙상 대응으로 연결합니다.
반복 눕기, 침묵, 센싱 오류는 정지 증거가 아니며 방·주방의 눕기를 화장실 낙상으로 확대하지 않습니다.

낙상 확정 시 AI가 `fall_detected`를 보내고, 이후 대응은 백엔드가 소유합니다.

1. 백엔드: 인덕션 비상 차단·전등 10초 깜빡임·대시보드 경고.
2. AI: 사용자 안내 문장 생성·전달. 백엔드: 사용자 확인 링크 문자, 무응답 시 보호자 알림.
3. 백엔드: 보호자 무응답 시 다음 신고 단계 진행, 확인 응답 시 종료.

공유된 백엔드 정책의 대기 기본값은 사용자 30초, 보호자 알림 후 60초이며 백엔드 정책에서 조정합니다.
AI가 타이머를 중복 실행하거나 “괜찮아”라는 음성만으로 사건을 닫지 않습니다.
백엔드 사건 조회의 종료 상태를 반영하며, 실제 119 신고 연결 여부는 별도로 확인해야 합니다.

### 공기청정기와 외출 제어의 경계

공기질 측정·임계값·공기질 자체 ON/OFF는 **임베디드 담당**입니다. AI는 PM 기준을 새로 만들지 않습니다.

- 조리 종료는 인덕션 ON → OFF 또는 정상 `cooling` 전이로 확인합니다.
- 종료 후 good/normal이 30초 유지되어도, 실제 `lastControl.commandId`가 AI의 조리 ON 명령과 일치해야 공청기 OFF를 검토합니다.
- 수동 ON·임베디드 자동 ON·출처 불명은 임의로 해제하지 않습니다. `control_state=homevis`만으로는 부족합니다.
- 외출은 집 전체 부재 계약이 검증된 경우, 첫 유효한 `empty` 관측을 받은 처리 주기에 즉시 판단합니다. 추가 확인 대기는 없습니다.
- 백엔드 입력은 `present=false`, 명시적 `room=null`, 신뢰도 ≥0.8, 양수 `validSec`을 검사하며, 직접 Wi-Fi MQTT의 `location=empty`는 해당 포맷의 시각·유효성 조건으로 별도 검사합니다.
- 외출 OFF 대상은 백엔드가 선택하는 전등·인덕션·환풍기·공청기이며 **정수기는 제외**합니다.
- 동일 조리·외출 구간의 중복 요청을 막습니다. 외출 후 귀가만으로 인덕션을 다시 켜거나 이전 화력을 복구하지 않습니다.

현재 백엔드는 AI GET에서 `lastControl`을 제외하고, 임베디드와 공유하는 유지·우선순위 계약도 없습니다.
따라서 “조리 ON 후 임베디드가 다시 OFF”, “외출 OFF 후 공기질 bad로 다시 ON”을 물리적으로 막았다고 보장하지 않습니다.
[공기청정기·외출 통합 문서](docs/home_automation_v07.md)에 조건·충돌 시험·남은 계약을 정리했습니다.

## 5. Confidence와 피드백

기본 운영 프로필 `location_level_v1`은 실제 위치·화력 단계로 일반 전등과 인덕션 감소·복구를 평가합니다.
화력 감소의 **초기 가중치**는 다음과 같습니다.

```text
confidence = 0.30 × 위치 신뢰도
           + 0.30 × clamp(주방 이탈 초 / 40, 0, 1)
           + 0.10 × (관측 화력 단계 / 9)
           + 0.20 × 센싱 일관성
           + 0.10 × 피드백 점수
```

위치 신뢰도·일관성 0.95, 이탈 40초, 화력 5단계, 피드백 0.5이면 약 **0.881**입니다.
기준은 감소 0.82, 복구 0.80, 전등 ON 0.72 / OFF 0.78입니다.
이 값은 **정책 점수이지 실제 정확도 확률이 아닙니다.** 피드백 학습 후 가중치는 달라질 수 있고, 높은 점수가 안전 차단을 해제하지 않습니다.

기존 `legacy` 프로필과 학습 구조는 유지하며 운영 프로필의 가중치·피드백 파일은 분리합니다.
신규 공청기 규칙은 기기 관측의 최신성 점수, 외출 규칙은 첫 유효한 전체 부재 관측의 신뢰도를 사용합니다.
live 규칙 출력에는 관측 근거를 사용하며 아래 부록의 Mock `confidence=null`을 실제 백엔드로 보내지 않습니다.

기존 구조화·자연어 피드백 경로를 유지합니다. “왜 껐어?” 같은 질문 자체는 학습시키지 않고,
명시적 평가·판단 대상·사용자·프로필이 확인된 피드백만 기존 학습 경로로 전달합니다.
백엔드 대시보드 yes/no 피드백을 자동으로 조회해 학습시키는 연결은 아직 구현되어 있지 않습니다.

## 6. LLM 선택과 TTS

LLM은 안내문, 음성 의도 분류, 자연어 피드백 해석에 사용합니다.
중앙 위험 판단이나 가전 안전 검증을 LLM의 자유로운 답변에 맡기지 않습니다.

| `LLM_PROVIDER` | 방식 | 준비 사항 |
| --- | --- | --- |
| `none` | 기본 문구·보수적 처리, 기본값 | 모델·키 불필요. LLM 기반 음성 해석은 사용 불가 |
| `qwen` | 기존 로컬 Qwen3-8B | 로컬 모델 및 `torch/transformers/accelerate` |
| `exaone` | FriendliAI Chat Completions API | `FRIENDLI_API_KEY` |
| `gpt` | OpenAI Responses API | `OPENAI_API_KEY`, `OPENAI_MODEL` |

`requirements-runtime.txt`는 `requirements.txt`의 OpenAI SDK와 선택적 TTS/API 의존성을 포함합니다.
EXAONE·GPT를 선택하면 Qwen을 다운로드하거나 GPU에 로딩하지 않습니다.
기존 Gemini(Vertex AI) 어댑터도 유지되며 `llama`는 실행용 모델이 아닌 placeholder입니다.

### EXAONE

연속 실행기가 읽는 `.env` 예시입니다.

```ini
LLM_PROVIDER=exaone
FRIENDLI_API_KEY=
EXAONE_MODEL=LGAI-EXAONE/EXAONE-4.0-32B
EXAONE_BASE_URL=https://api.friendli.ai/serverless/v1
EXAONE_TIMEOUT_SECONDS=30
EXAONE_MAX_RETRIES=2
EXAONE_MAX_TOKENS=256
EXAONE_TEMPERATURE=0.3
```

`FRIENDLI_API_KEY`에 본인의 Personal API Key를 설정합니다. 모델과 URL은 환경변수로 변경할 수 있습니다.

### GPT

```ini
LLM_PROVIDER=gpt
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_TIMEOUT_SECONDS=30
OPENAI_MAX_RETRIES=2
OPENAI_MAX_OUTPUT_TOKENS=2048
```

`OPENAI_MODEL`은 본인 API 계정에서 사용할 모델 ID로 지정합니다. 코드에 기본 모델을 고정하지 않았습니다.
현재 어댑터의 URL은 `https://api.openai.com/v1`로 고정하며 `OPENAI_BASE_URL`을 상속하지 않습니다.

### Qwen과 오류 처리

Qwen은 `LLM_PROVIDER=qwen`으로 선택합니다. 기본 로컬 모델 경로는 사용자 홈의 `models/Qwen3-8B`이며
기존 추론 설정을 유지합니다. 사용할 때만 `python -m pip install -r requirements-qwen.txt`를 실행하고,
`config/decision_policy.toml`의 `[llm].model`에 준비한 로컬 모델 폴더를 지정하세요.
어댑터 모듈을 불러오는 데에는 torch가 필요하지 않습니다. Qwen 초기화 시 폴더와 선택 의존성을 확인하며 모델을 자동 다운로드하지 않습니다.

API 어댑터는 클라이언트를 재사용하고 timeout·제한적 재시도·인증/설정 오류·비정상 응답을 처리합니다.
최종 답변만 추출하며 reasoning을 TTS나 피드백 JSON에 섞지 않습니다.
안내 생성 실패 시 기본 문구를 사용하고 중앙 판단 결과는 보존합니다. Qwen으로 자동 대체 로딩하지 않습니다.

기존 위험·낙상 `AlertService`는 텍스트와 WAV를 생성하며, 통합 실행기는 안내 문장을 `announcement`로 전달합니다.
로컬 WAV를 자동 재생하거나 백엔드에 파일을 업로드하지 않습니다. **음성 명령 응답은 백엔드 TTS 경로**를 사용합니다.

연속 실행기는 `config/decision_policy.toml`의
`[llm]`에서 선택하며, provider/model을 비워 두면 기존 `LLM_PROVIDER`와 provider별 모델 환경변수를 사용합니다.

## 7. 음성 명령과 사용자 상호작용

`.env`에서 `HOMEVIS_VOICE_ENABLED=true`와 사용할 LLM을 설정합니다.
실행 명령은 같은 `python -m src.integration`이며 HTTP 센싱과 MQTT 음성 수신을 함께 실행합니다.

- 백엔드가 시작어·STT를 처리합니다. AI는 `text`만 해석하고 `rawText`는 기록용으로 보존합니다.
- 전등, 환풍기, 정수기, 공청기와 인덕션 제어를 기존 허용 액션으로 변환합니다.
- 상태 변경은 안전 검증 후 백엔드 사용자 확인을 요청합니다. 인덕션 끄기만 확인 없이 요청합니다.
- “인덕션 3단으로 켜줘”는 명시적 1~9단·최신 OFF 상태·주방 재실·온도 검증이 필요합니다. 현재 live 온도 차단도 적용됩니다.
- “왜 껐어?”는 실제 판단 이력에 근거해 설명합니다. 대상이 모호하면 임의로 선택하거나 학습하지 않습니다.
- 장기 지시는 SQLite에 `proposed`로 저장할 뿐 자동 적용하지 않습니다. 다중 사용자 인증도 구현하지 않았습니다.
- `voiceId` 중복 제거, 확인 대기 상태 조회, 재시작 복구, 만료 시 무제어 처리를 포함합니다.

실제 AI를 연결할 때 백엔드의 `voice-ai-simulator`는 중지해 중복 응답을 피하세요.
지원 명령·확인 흐름·상세 제약은 [음성 상호작용](docs/voice_interaction.md)에 있습니다.

## 8. 설정·저장·장애 대응

**판단 기준은 [config/decision_policy.toml](config/decision_policy.toml) 한 파일에서 조정합니다.**
현재 기본값이 들어 있으며, `python -m src.integration` 실행기가 시작할 때 읽어 각 판단 모듈에 전달합니다.
네트워크 주소·토픽·실행 주기는 [config/homevis.toml](config/homevis.toml), 환경변수 예시는 [.env.example](.env.example)입니다.
지원되는 항목에 한해 **CLI > OS 환경변수 > .env > TOML** 순으로 적용합니다.
모든 TOML 키에 환경변수 별칭이 있는 것은 아닙니다.

| decision_policy.toml 항목 | 조정 대상 / 예시 |
| --- | --- |
| `[automation]` | 주방 이탈 40초·복귀 5초, 전등 ON 5초·OFF 30초, 화력 감소 단계 |
| `[confidence.weights.location_level_v1.시나리오]` | 현재 운영 프로필의 항목별 가중치. 시나리오별 합계 1.0 |
| `[confidence.thresholds]` | 실행 기준 점수. 예: `light_auto_on = 0.72` |
| `[confidence]` | 중간 판단 점수, 피드백 학습률·적용 기준, 가중치 상·하한 |
| `[realtime]`, `[sensing]` | 신뢰도·측정 지연·센싱 만료·온도·화력 기준 |
| `[scenarios]` | 낙상 확인/경고/긴급 시간, 취침 소등, 아침 시간대·출수량 |
| `[home_automation]` | 공청기 깨끗한 상태 유지 시간, 외출 최소 신뢰도·전체 부재 계약 확인 |
| `[voice]` | STT·의도 신뢰도, 설명에 사용할 이력 범위 |
| `[llm]` | `provider`로 LLM 종류, `model`로 API 모델 ID 또는 Qwen 로컬 모델 경로 선택 |

모든 설정값 옆의 `#` 주석에 조정 대상·단위·사용 조건을 적었습니다. LLM은 다음처럼 선택합니다.

```toml
[llm]
provider = "exaone" # none / exaone / gpt / qwen / gemini; 빈 문자열이면 LLM_PROVIDER 사용
model = "LGAI-EXAONE/EXAONE-4.0-32B" # 빈 문자열이면 해당 어댑터의 환경변수/기본값 사용
```

`[llm]`에 명시한 값은 환경변수보다 우선하며, API 키는 계속 `.env`에서 읽습니다.
GPT는 `model` 또는 `OPENAI_MODEL`에 사용할 모델 ID가 필요하고, Qwen의 `model`은 로컬 폴더 경로입니다.
Llama는 아직 미구현이라 정책 파일에서 선택하면 시작 시 거부합니다. 선택한 모델은 live 실행에서
안내문·음성·자연어 피드백이 공유하며, 호출 실패 시 기존 안내문 대체 및 기기 판단 경로를 유지합니다.
통합 설정으로 선택한 모델은 mock에서 자동 호출하지 않습니다. `--check-config`는 모델을 호출하지 않고 설정을 표시합니다.

수정 후 `python -m src.integration --check-config`로 확인하고 프로그램을 재시작하면 적용됩니다.
가중치 합계·지원하지 않는 항목·시간 순서·범위가 잘못되면 시작을 거부합니다.
정책 파일 경로는 `homevis.toml`의 `decision_policy`에 지정하며, 해당 TOML 파일의 디렉터리를 기준으로 찾습니다.
두 파일에 같은 판단 항목을 중복 정의하면 오류로 알립니다. 정책 파일을 지정하지 않은 기존 단일 TOML도 지원합니다.

가중치나 가중치 상·하한을 바꾸면 그 구성 전용 `user_weights.*.policy-<식별자>.json`을 사용하므로
저장된 이전 학습값이 새 설정을 덮지 않습니다. 같은 설정으로 재시작하면 해당 학습값을 이어 쓰며,
기존 학습 파일과 피드백 이력은 보존합니다. 점수 기준이나 시간만 바꿀 때는 기존 가중치 학습을 이어 씁니다.
외출 전체 OFF는 계약이 확인된 첫 유효 `empty`에서 즉시 판단하며 확인 대기 시간을 설정하지 않습니다.

| 설정 | 기본값 / 용도 |
| --- | --- |
| `[backend].poll_interval` | 2초, 기기 상태 GET |
| `[runtime].sensing_poll_interval` | 1초, 센싱 GET |
| `[runtime].tick_interval` | 0.1초, 판단 루프 |
| `decision_policy.toml: [sensing].allowed_lateness` | 4초, 측정 시각 정렬 |
| `decision_policy.toml: [sensing].device_max_age` | 20초, 기기 상태 최신성 기준 |
| `[backend].stove_temperature_validity_verified` | `false`, live 인덕션 ON·증가·복구 차단 |
| `decision_policy.toml: [home_automation].whole_home_presence_verified` | `false`, 전체 부재 계약 미확인 시 외출 OFF 차단 |
| `decision_policy.toml: [home_automation].away_min_confidence` | 0.8, 첫 유효한 전체 부재 관측에서 즉시 판단 |
| `decision_policy.toml: [home_automation].air_purifier_clean_hold_seconds` | 30초 |
| `[voice].enabled` | `false`, 선택적 음성 입력 |

온도 확인 플래그는 **팀의 계약·구현 검증을 마쳤다는 운영 설정**이지 센서 유효성을 자동 증명하는 기능이 아닙니다.
`temperature_is_celsius=true`라는 단위 설정과도 다릅니다.
차단 중에도 인덕션 OFF 및 이미 ON인 화구의 실제 단계 감소는 기존 안전 검증을 거쳐 요청할 수 있습니다.

### 저장과 재전송

- 상태: `output/integration/live/status.json`
- 요청·응답·중복 방지·출수 예약·음성/자동화 이력: `output/integration/live/outbox.sqlite3` 등
- Mock은 `output/integration/mock/`로 분리합니다.
- 재시도·재시작 시 원본 decisionId와 본문을 유지하며 만료된 일반 제어를 보내지 않습니다.
- `sent`나 백엔드 `executed`는 실제 가전 동작 완료 ACK가 아닙니다. 후속 기기 관측으로 확인합니다.
- 하루 출수 예약은 물리적 출수 성공과 별개로 요청 중복을 막습니다. 저장소를 지우면 안전·중복 방지 이력도 잃으므로 임의 삭제하지 마세요.
- 한 운영 저장소·고정 MQTT client ID에는 AI 프로세스 하나만 실행합니다.

잘못된 HTTP 형식, 미래 시각, 통신 실패, 큐 초과는 센싱 오류로 처리합니다.
정상 자동화의 누적 근거를 끊고 오류 이전의 지연 관측으로 유효성이 되살아나지 않게 차단합니다.
활성 낙상은 종료하지 않으며, 오류 전에 이미 수신·검증된 명시적 낙상 보고는 보존합니다.

```sh
python -m src.integration --healthcheck
```

이 검사는 실행기 heartbeat만 확인합니다. 센싱 연결·기기 안전·모든 자동화 정상 동작을 보증하지 않습니다.
`.env`·`.env.*`·`output/`은 Git에서 제외하고 `.env.example`만 공유합니다.
음성 원문과 판단 이력에도 개인 정보가 포함될 수 있으므로 공개 업로드하지 마세요.

## 9. 실행 확인

개발용 `tests/`, 수동 테스트 파일, 별도 데모, 검증 스크립트·CI와 임시 검증 환경은 정리했습니다.
실행에는 pytest가 필요하지 않습니다. 설정과 기동은 실제 실행 파일로 확인합니다.

```sh
python run_homevis.py --check-config
python run_homevis.py --mode mock --duration 15
python run_homevis.py --mode mock --mock-scenario fall --duration 15
```

Mock은 실제 판단 엔진과 가상 센싱·백엔드를 사용하며 실가전이나 유료 API를 호출하지 않습니다.
실제 운영은 `python run_homevis.py`로 시작하며 종료 시간 없이 계속 실행됩니다.
상세 문서의 회귀 테스트 결과는 테스트 파일 삭제 전의 검증 기록입니다.

## 10. 배포 전 확인

담당 팀에 전달할 요청·필요한 샘플·완료 기준은 [팀 전달용 요청사항](docs/home_automation_v07.md#팀-전달용-요청사항)에 정리했습니다.
다른 팀 저장소는 수정하지 않으며, 미확정 계약에 대한 AI의 안전 차단은 유지합니다.

- [ ] Wi-Fi → 백엔드 토픽·JSON 변환, 측정 시각·유효기간·오프라인·전체 부재 의미를 합의하고 실제 데이터를 확인한다.
- [ ] `fall/lie_down/get_up/none` 생산자의 실제 JSON·행동 신뢰도·시각을 확인한다. 자세·still은 실제 측정이 있을 때만 연결한다.
- [ ] 임베디드·백엔드가 무효/오래된 온도를 정상 숫자로 제공하지 않도록 수정·검증한 뒤 온도 확인 설정을 검토한다.
- [ ] 공청기 `lastControl` 출처 전달과 수동/임베디드/AI/외출 제어 우선순위·유지 계약을 확정한다.
- [ ] 백엔드 낙상 문자·보호자 확인·사건 복구와 실제 신고 수단을 별도로 시험한다.
- [ ] 보드 주소·인증·MQTT TLS·시간 동기화·데이터 디렉터리 쓰기 권한을 확인한다.
- [ ] Mock → 로컬 계약 테스트 → 감독하의 실가전 테스트 순으로 검증한다.

검토 기준 소스는 백엔드 develop `fb22929879d255f6c1788f465df48c941b9338b7`,
Wi-Fi main `f73c0ff0d72bcdf1e04769270e7fb401103bde90`,
임베디드 develop `1f0e26278e8575000547200954a22c53ad4fe89d`입니다.
이후 변경은 다시 대조해야 합니다. 상세 계약 링크와 근거는 [통합 검증 문서](docs/home_automation_v07.md)에 있습니다.

## 11. 코드와 상세 문서

| 경로 | 역할 |
| --- | --- |
| `src/control/` | 중앙 판단, 위험 상태, 생활·낙상 시나리오 |
| `src/control/confidence/` | feature, 가중치, 점수, 판단 이력 |
| `src/control/feedback/`, `src/control/routine/` | 구조화·자연어 피드백, 루틴 기록 |
| `src/integration/` | 입력 변환, 연속 실행, 백엔드 요청, Outbox, 공청기·외출 규칙 |
| `src/interaction/` | 음성 의도·검증·설명·확인 상태·사용자 지시 저장 |
| `src/llm/` | 공통 LLM 인터페이스, Qwen·EXAONE·GPT 등 |
| `src/alert_service.py`, `src/voice/` | 기존 위험 안내문·TTS |
| `run_homevis.py`, `config/` | 전체 실행 진입점, 연결 설정, 주석이 있는 판단 기준·LLM 설정 |

- [연속 실행·운영](docs/continuous_runner.md)
- [백엔드 입력·전송·저장 계약](docs/backend_integration.md)
- [Wi-Fi 행동 연동](docs/wifi_behavior.md)
- [공기청정기·외출·검증과 남은 계약](docs/home_automation_v07.md)
- [음성 상호작용](docs/voice_interaction.md)
- [실시간 위험 판단](docs/realtime_control.md)
- [Confidence와 피드백](docs/confidence_control.md)
- [생활·안전 시나리오](docs/scenarios.md)

## 부록. Mock 요청·응답 기록

아래는 삭제 전 개발용 데모에서 생성했던 요청·응답 기록입니다.
**실제 백엔드 전송 예시가 아닙니다.** 기존 직접 호출용 Mock의 `confidence=null` 정책과 가상 식별자·날씨를 사용합니다.
현재 실행 결과를 나타내는 예시는 아닙니다.

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

Mock 서버의 전체 HTTP 202 응답:

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

같은 ID·본문 재전송은 HTTP 200 + `duplicate: true`로 처리합니다.
`rejected/failed`를 새 decisionId로 임의 재실행하지 않으며 `sent`를 물리적 출수 완료로 해석하지 않습니다.
