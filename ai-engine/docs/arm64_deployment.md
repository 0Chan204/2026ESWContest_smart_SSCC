# ARM64 Docker 배포와 외부 API 장애 대응

기존 중앙 판단 엔진, provider별 어댑터, `/api/v1/ai/decisions` 계약을 그대로 사용한다.
LLM은 안내 문구·자연어 해석을 담당하며, 안전 판단이나 명령 생성의 필수 의존성이 아니다.

이후 단일 파일 실행·장애 복구·Windows 상태 파일 충돌을 추가로 검증했다.
최신 연속 실행 결과와 `run_homevis.py` 사용법은 [연속 실행 문서](continuous_runner.md)를 참고한다.

## 검증 범위

- 이 작업 환경은 Windows이며 Docker CLI/Engine과 WSL 배포판이 없다. **ARM64 이미지 빌드·컨테이너 실행·실제 보드 실행은 아직 검증되지 않았다.**
- Python 3.11/Linux aarch64 조건으로 Python 의존성 wheel 31개(약 12.4MB)의 다운로드를 확인했다. torch·transformers·CUDA 의존성은 없다. Windows의 의존성 조건을 Linux로 바꾸어 확인했으며, 이 검사는 이미지 교차 빌드나 Linux 실행을 대신하지 않는다.
- 자동 테스트는 격리된 Windows x64/Python 3.13.5 환경에서 실행했다. GPT/EXAONE/Gemini는 Mock Client 또는 Mock HTTP transport만 사용했고 유료 API를 호출하지 않았다. 이후 개발용 테스트·검증 스크립트·CI·임시 환경을 삭제했다. 아래 표는 삭제 전 기록이다.
- Docker가 있는 환경에서는 아래 Buildx/Compose 명령으로 직접 빌드하고 실행한다. 원격 CI 실행이나 이미지 게시는 수행하지 않았다.

2026-10-27 검증 결과:

| 검사 | 결과 |
|---|---|
| 전체 `python -m pytest -q -ra` | **833 passed, 11 skipped**, 186.76초 |
| API 선택·Mock 응답·연결/타임아웃/인증 장애·복구 | 통과; 실제 유료 API 호출 없음 |
| 즉시 외출 OFF·반복/과거 입력·unknown/오류·귀가 재점화 방지 | 통과; 기존 두 센싱 포맷 검사 포함 |
| LLM 없이 또는 실패 중 낙상·주방 화력 감소·전등 OFF | 통과; 기존 공기청정기·수동 보호 회귀 검사 포함 |
| 설정·SQLite 판단 이력·외출 episode·잠금·학습 가중치 재개 | 호스트에서 동일 배포 probe의 write/read 검사 통과 |
| `--check-config`, mock 연속 실행, Python 구문 검사 | 통과 |
| Compose/workflow YAML 구문, `git diff --check` | 통과; Docker Compose 엔진을 통한 검사는 미실행 |
| ARM64/Python 3.11 wheel 확보 | 31개 모두 성공, 무거운 모델 런타임 없음 |
| ARM64 cross-build·컨테이너 비루트/파일 제외/재시작·보드 실기기 | **미실행: Docker/WSL 및 보드 없음** |

skip 11개는 실제 유료 GPT/EXAONE API 테스트 2개와 별도 백엔드 checkout이 필요한 계약 테스트 9개다. Docker 검사를 pytest 통과 개수에 포함하지 않는다.

## provider 구현 상태

| `LLM_PROVIDER` | 구현 및 보존한 호출 경로 | ARM64 기본 이미지 |
|---|---|---|
| `gpt` | `GPTAdapter` → OpenAI `client.responses.create` | SDK 포함, 선택할 때만 초기화 |
| `exaone` | `EXAONEAdapter` → FriendliAI `client.chat.completions.create` | SDK 포함, 선택할 때만 초기화 |
| `gemini` | `GeminiAdapter` → Vertex AI `models.generate_content`, ADC 인증 | SDK 포함, 선택할 때만 초기화 |
| `qwen` | 기존 로컬 Qwen 어댑터와 로컬 파일 로딩 유지 | 코드만 포함. 모델 가중치·torch·transformers·CUDA 제외 |
| `llama` | 기존 미구현 placeholder 유지 | 실제 추론 지원으로 취급하지 않음 |
| `none` | API 호출 없이 기존 기본 문구 사용 | 인증 없이 실행 가능 |

Qwen은 기존 별도 로컬 설치 환경에서 계속 사용할 수 있다. 경량 이미지에서 `qwen`을 선택하면 추가 런타임이 없으므로 LLM 초기화 실패 후 기본 문구를 사용한다. 다른 provider의 실패로 Qwen이나 다른 유료 API를 자동 선택하지 않는다.

## 설정과 인증

판단 가중치·시간·신뢰도 하한·LLM 선택은 `config/decision_policy.toml`에서 조정한다. 각 항목의 `#` 주석에 의미와 단위가 있다. 변경 후 설정 검사와 재시작이 필요하다.

기존 `LLM_PROVIDER` 환경변수 방식은 그대로 지원한다. 기본 정책 파일의 `[llm].provider`와 `model`은 빈 문자열이므로 환경변수를 따른다. 앞서 추가한 파일 내 명시적 provider/model 선택도 유지하며, 값을 지정하면 해당 항목은 환경변수보다 우선한다. Docker에서 환경변수로 선택하려면 두 값을 비워 둔다. API 키·ADC는 정책 파일에 쓰지 않는다.

`.env.example`을 `.env`로 복사하고 실제 배포값을 로컬에서 입력한다. `.env`, 인증 JSON, 키, 모델 가중치는 이미지에 넣지 않는다. Compose는 `env_file: .env`, 단독 Docker 실행은 `--env-file .env`를 사용한다. 선택하지 않은 provider의 인증은 필요하지 않다.

GPT 예:

```dotenv
LLM_PROVIDER=gpt
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_TIMEOUT_SECONDS=30
OPENAI_MAX_RETRIES=2
OPENAI_MAX_OUTPUT_TOKENS=2048
```

키와 계정에서 사용할 수 있는 모델 ID를 채운다. GPT는 기존 Responses API를 그대로 호출한다. SDK의 요청 timeout과 제한된 retry 옵션을 사용한다. [OpenAI Python SDK 문서](https://developers.openai.com/api/reference/python)

EXAONE 예:

```dotenv
LLM_PROVIDER=exaone
FRIENDLI_API_KEY=
EXAONE_MODEL=LGAI-EXAONE/EXAONE-4.0-32B
EXAONE_BASE_URL=https://api.friendli.ai/serverless/v1
EXAONE_TIMEOUT_SECONDS=30
EXAONE_MAX_RETRIES=2
EXAONE_MAX_TOKENS=256
EXAONE_TEMPERATURE=0.3
```

Gemini 예:

```dotenv
LLM_PROVIDER=gemini
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_RETRIES=2
HOMEVIS_GOOGLE_ADC_FILE=/secure/homevis/google_adc.json
```

`compose.vertex.yaml`을 함께 적용하면 호스트 ADC 파일을 `/run/secrets/google_adc.json`에 읽기 전용으로 연결한다. 호스트 인증 파일은 컨테이너 UID/GID `10001:10001`이 읽을 수 있어야 한다. 파일을 읽을 수 있는 권한과 Vertex AI 권한은 운영 환경에서 확인한다. 인증 파일의 내용을 출력하거나 Docker build argument로 전달하지 않는다. ADC 파일 없이 보드에 적절한 기본 인증 환경이 제공된다면 기본 Compose만 사용할 수 있다.

Gemini는 Vertex 설정을 유지하면서 SDK `HttpOptions`의 밀리초 timeout과 최초 요청을 포함하는 `HttpRetryOptions.attempts`를 지정한다. [Google Gen AI Python SDK 문서](https://googleapis.github.io/python-genai/)

API 없이 실행하려면 `.env`에 `LLM_PROVIDER=none`을 지정한다. 실제 로컬 서비스에 연결할 때는 `HOMEVIS_MODE=live`, 장치 제어 없는 시뮬레이션은 `mock`을 사용한다. CLI의 mock 실행은 유료 API 호출을 사용하지 않는다.

## 빌드·실행

저장소 루트에서 실행한다. Python 3.11 기반이며 아키텍처는 Buildx가 선택한다.

```sh
docker buildx create --name homevis-builder --driver docker-container --use
docker buildx inspect --bootstrap
docker buildx build --platform linux/arm64 --load -t homevis-ai:arm64 .
```

이미 같은 이름의 builder가 있다면 `docker buildx use homevis-builder`로 선택한다. x86 개발 PC에서는 QEMU 지원이 있는 Docker/Buildx가 필요하다. [Docker 멀티 플랫폼 빌드 문서](https://docs.docker.com/build/building/multi-platform/)

운영 설정 검사 및 실행:

```sh
cp .env.example .env
# .env의 백엔드/MQTT 주소, provider, 필요한 인증을 편집한다.
docker compose run --rm homevis --check-config
docker compose up -d --no-build
docker compose exec homevis python -m src.integration --healthcheck
docker compose logs --tail=30 homevis
```

Gemini ADC 파일을 사용할 때:

```sh
docker compose -f compose.yaml -f compose.vertex.yaml run --rm homevis --check-config
docker compose -f compose.yaml -f compose.vertex.yaml up -d --no-build
```

단독 Docker 실행:

```sh
docker run -d --name homevis --platform linux/arm64 --network host \
  --env-file .env --env HOMEVIS_DATA_DIR=/data \
  --mount type=volume,source=homevis-data,target=/data \
  --mount type=bind,source="$PWD/config",target=/app/config,readonly \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --restart unless-stopped homevis-ai:arm64
```

Compose의 host 네트워크는 Linux 보드의 기존 백엔드/MQTT에 연결하기 위한 것이다. 다른 장비에서 서비스를 실행한다면 `.env` 주소를 해당 LAN 주소로 바꾼다. Windows Docker Desktop의 host 네트워크 지원 여부는 별도로 확인한다.

`--check-config`는 TOML/정책을 검증하며 API 접속이나 인증 성공을 보증하지 않는다. `--healthcheck`와 Docker HEALTHCHECK는 판단 루프의 최근 heartbeat만 검사한다. LLM 또는 백엔드 장애 상태에서도 루프가 살아 있으면 healthy일 수 있다. `status.json`의 `llm`, `backend_available`, `sensing`, `home_automation`을 함께 본다.

## 저장소와 권한

- `/data/live`와 `/data/mock`에 각 모드의 `outbox.sqlite3`, 판단·음성·낙상 이력, episode ID, 복원 잠금, controller 학습 파일, 상태 파일, 로컬 안내 WAV가 저장된다.
- `homevis-data` named volume은 재시작과 컨테이너 재생성 뒤에도 유지된다. `docker compose down -v`는 보존 데이터를 삭제하므로 운영 재시작에 사용하지 않는다.
- `/app/config`는 호스트 설정 디렉터리를 읽기 전용으로 연결한다. 정책 파일은 이미지 재생성 후에도 호스트 파일을 따른다. 설정 변경 후 `--check-config`, `docker compose restart homevis`를 실행한다. `.env` 변경은 `docker compose up -d --force-recreate`로 컨테이너에 다시 적용한다.
- 사용자 `10001:10001`로 실행한다. 이미지가 `/data`의 소유권을 준비하며 신규 named volume은 이를 이용한다. 기존 volume이나 직접 bind mount하는 데이터 디렉터리는 관리자가 해당 UID/GID의 쓰기 권한을 준비해야 한다. 프로그램이 root로 권한을 자동 변경하지 않는다.
- 동일 데이터 디렉터리를 두 프로세스가 동시에 쓰지 못하도록 기존 instance lock을 유지한다.
- 한국어 TTS 품질·실제 스피커 출력은 보드에서 확인해야 한다. 이미지의 eSpeak 라이브러리는 기존 로컬 WAV 생성 경로를 위한 것이며, 백엔드 v0.7 음성 상호작용의 TTS/재생은 계속 백엔드가 담당한다.

## API 장애와 로컬 백엔드 장애

`IntegrationRuntime`은 항상 지연 초기화되는 `SharedLLM`을 사용한다. 어댑터 생성 자체가 실패해도 `LLMMessageGenerator` 안에서 처리되어 기본 안내 문구가 남는다. 기존 비동기 worker가 LLM/TTS를 실행하므로 요청 지연이 센싱·중앙 판단 루프를 막지 않는다.

요청/인증/초기화 오류가 나면 `llm.state=degraded`, `fallback_active=true`와 예외 종류만 상태·로그에 기록한다. API 응답 본문, 키, 원본 예외 문자열은 기록하지 않는다. `config/decision_policy.toml`의 `llm.failure_retry_seconds` 동안 추가 API 호출/초기화를 억제한다. 기본값은 30초이며 **LLM 복구 간격일 뿐 외출/안전 판단 대기가 아니다.** 간격이 지난 뒤 다음 안내·해석 요청이 오면 같은 provider를 다시 사용한다. 생성된 클라이언트는 재사용하며 성공 시 `ready`로 돌아간다. 주기적인 유료 API 탐색 요청은 보내지 않는다.

SDK retry는 0~5회로 제한되며 timeout은 유한한 양수만 허용한다. timeout은 SDK의 개별 요청 제한으로, retry가 있으면 총 소요 시간은 늘어날 수 있다. 음성 요청은 남은 deadline으로 timeout을 더 줄이고 추가 retry를 끈다. Qwen 같은 기존 로컬 추론은 API timeout 제어 대상이 아니다.

외부 LLM만 끊겼다면 로컬 백엔드/MQTT를 통한 안전 요청은 계속 가능하다. 로컬 백엔드까지 끊기면 기존 outbox가 명령 ID, 만료 시간, 재검증, 재시도를 관리한다. 복구 후에도 오래되거나 더 이상 유효하지 않은 명령을 무조건 보내지 않는다. 별도의 직접 제어 MQTT 토픽은 추가하지 않았다.

`accepted`, 백엔드의 `executed`, 개별 action의 `sent`는 물리 기기 동작 완료를 의미하지 않는다. 실행 ACK가 없으면 기존 `execution_ack_not_provided` 진단을 유지한다.

## 센싱 → 외출 OFF 경로와 기존 안전 기능

1. 기본 입력은 `BackendSensingSource`가 `/api/v1/sensing/results`를 조회한다. `present=false`와 `room=null`, 유효한 측정 시각·`validSec` 등이 있는 결과를 정규화한다.
2. 직접 Wi-Fi MQTT 입력은 `HOMEVIS_SENSING_SOURCE=mqtt`일 때 사용한다. `location=empty`, `time`, `location_confidence` 계약을 별도로 검증한다. backend 포맷과 같은 것으로 가정하지 않는다.
3. `InputRouter`/`IntegrationRuntime.observe_presence`가 수신 시점의 증거를 `HomeAutomation`에 전달한다. 시각, 만료, 유효성·오류, 신뢰도를 검사하고 `whole_home_presence_verified`가 true인 경우에만 집 전체 부재로 사용한다. 운영 기본값은 false를 유지한다.
4. 첫 유효한 `empty`를 처리하는 주기에 `away_all_off`, `actions=[]`를 기존 outbox에 저장한다. 600초 누적 대기, 추가 확인 타이머, 행동 join/reorder 대기를 외출 판단에 적용하지 않는다.
5. 기존 `/api/v1/ai/decisions`로 전송하며 실제 OFF 대상은 백엔드가 결정한다. 반복·재전송·재시작에서는 episode ID와 저장된 수신 cursor로 중복을 막는다. 귀가해도 `away_restore_lock`은 자동으로 해제하지 않는다.

낙상은 기존 `BathroomFallScenario`의 위치·전이·신뢰도·움직임·유효성 조건을 그대로 사용한다. `lie_down`만으로 낙상을 확정하지 않는다. 주방 이탈 화력 감소, 재실/부재 전등 제어, 조리 중 공기청정기, 사용자 수동 조작 보호, confidence 계산·피드백 학습 알고리즘은 변경하지 않았다. 오류나 `unknown`은 부재 또는 안전 해제 근거가 아니다.

## 변경 파일

| 파일 | 변경 목적 |
|---|---|
| `Dockerfile`, `.dockerignore`, `requirements-arm64.txt` | Python 3.11 ARM64용 경량 배포, 필요한 파일만 복사, 비루트 실행·heartbeat |
| `compose.yaml`, `compose.vertex.yaml` | 상태 volume, 설정 mount, 런타임 환경변수, 선택적 ADC 읽기 전용 전달 |
| `.env.example`, `.gitignore`, `requirements.txt` | provider 설정 예시, 인증 파일 제외, 필요한 Gemini SDK 버전 범위 |
| `src/llm/shared.py`, `src/integration/runtime.py`, `src/integration/host.py` | 지연 초기화 실패 fallback, 같은 provider 복구, 상태·로그 분리 |
| `src/llm/adapters/exaone.py`, `src/llm/adapters/gemini.py` | 유한 timeout·retry, Vertex 유지, 안전한 예외 출력 |
| `src/llm/message_generator.py`, `src/control/feedback/natural_language_interpreter.py` | 원본 API 오류 문자열 대신 예외 종류만 기록; 판단/학습 로직 유지 |
| `src/llm/config.py`, `src/integration/decision_policy.py`, `config/decision_policy.toml` | 설명 주석이 있는 LLM 복구 간격 설정 연결 |

이전에 요청한 즉시 외출 OFF, 한 파일 설정, LLM 모델 선택 변경은 유지한다. 실행에 불필요한 자동·수동 테스트, 별도 데모, 검증 스크립트와 CI는 삭제했다. Dockerfile·Compose·런타임 healthcheck는 유지한다.

## 백엔드·임베디드 팀 확인 필요

- Wi-Fi `empty`가 집 전체 부재를 확정한다는 계약을 검증한 뒤에만 `whole_home_presence_verified`를 활성화한다.
- 공기청정기 펌웨어의 자체 ON이 외출 OFF를 덮어쓸 수 있다. 외출/긴급 제어의 우선권과 유지·해제·ACK 계약이 아직 없어 이를 소프트웨어에서 해결했다고 표시하지 않는다.
- 현재 인덕션 센서 실패 시 마지막 온도를 반복하는 계약 문제를 고려해 `stove_temperature_validity_verified=false`를 유지한다. 자동 재점화 허용으로 바꾸지 않는다.
- 실제 Wi-Fi 행동 producer, 낙상 후 보호자 통지, 기기 ACK, ADC 권한, 보드 리소스 사용량과 한국어 음성 출력은 현장 통합 검증이 필요하다.
