# HomeVIS 인덕션 백엔드 — FastAPI + MQTT 처음부터 따라하기

ESWC 개발계획서 기준: 백엔드는 **Python FastAPI**, 가전과의 통신은 **MQTT(Mosquitto 브로커)**.
이 문서는 FastAPI/MQTT를 한 번도 안 써봤다는 가정으로, 개념 → 설치 → 실행 → 테스트 순서로 씁니다.

---

## 0. 먼저 개념만 짧게

- **FastAPI**: 파이썬으로 REST API(웹 서버)를 만드는 프레임워크. 대시보드(프론트)가 "지금 인덕션 상태 알려줘", "이렇게 제어해줘" 라고 호출하는 창구입니다.
- **MQTT**: 가전(인덕션)과 서버가 실제로 데이터를 주고받는 통신 방식. HTTP처럼 "요청하면 응답"이 아니라, 브로커(우체국)를 사이에 두고 서로 메시지를 던지고(publish) 받는(subscribe) 방식입니다.
- **Mosquitto**: MQTT 브로커 소프트웨어 이름. 이번 프로젝트에서는 이게 그 "우체국" 역할을 합니다.
- 이 프로젝트에서의 역할 분담:
  - 인덕션(가전) → MQTT publish(telemetry) → 우리 FastAPI 서버가 MQTT subscribe로 받아서 상태 저장
  - 인덕션(가전) → MQTT publish(ack) → 서버가 명령 처리 결과(applied/rejected/failed) 반영
  - 대시보드 → FastAPI REST 호출(`POST /api/v1/appliances/{id}/burners/{burnerId}/commands`) → 우리 서버가 MQTT publish → 인덕션이 subscribe해서 실행

> v0.2 업데이트: 프론트/임베디드 팀과 API 명세를 확정하면서 화구를 1개로 줄이고,
> REST 경로는 `/api/v1` 하위로 정리했습니다. Swagger 문서는 `/docs` 하나이고, 그 안에서
> 기능별 섹션(회원 정보 / 낙상 사고 감지 / AI 재실 판단 / 인덕션 제어 / 대시보드 화면 /
> 안전 이벤트)으로 나뉩니다. 자세한 엔드포인트 목록은 `docs/dev-note.md`를 참고하세요.

즉 우리 FastAPI 서버는 **REST와 MQTT를 동시에 다루는 다리(hub) 역할**을 합니다.

---

## 1. 폴더 구조

```
induction-backend/
├── requirements.txt        # 설치할 파이썬 패키지 목록
├── .env.example             # 환경변수 예시 (복사해서 .env로 사용)
├── Dockerfile                # 백엔드 이미지 빌드 설정
├── docker-compose.yml        # MongoDB + Mosquitto + 백엔드 실행 구성 (10장)
├── mosquitto/mosquitto.conf  # Mosquitto 설정
├── app/
│   ├── main.py                # FastAPI 앱 진입점 (Swagger 문서 2개 분리 설정 포함)
│   ├── config.py               # 설정값 (브로커 주소, 토픽 이름, 부재중 정책 기본값 등)
│   ├── schemas.py               # v0.2 API 명세를 코드로 옮긴 것 (Pydantic 모델)
│   ├── rules.py                  # overheated 등 안전 규칙 검증 로직
│   ├── state_store.py             # 모든 상태를 담아두는 메모리 저장소
│   ├── mqtt_client.py              # MQTT 연결/구독(telemetry, ack)/발행(command) 담당
│   ├── device_service.py           # telemetry/ack 처리, 조리 세션 관리
│   ├── commands_service.py         # 화구 제어 명령 발행/ack 반영
│   ├── safety_service.py           # 안전 이벤트, 부재중 자동 제어 정책
│   ├── weather_service.py          # 날씨 받아오기(Open-Meteo, 30분 캐시) + 안내 문장 (v0.3.2)
│   ├── edge_service.py             # 엣지 노드 메시지 합쳐 전달 + 최종 재실 판단 결과 저장·조회 (v0.4)
│   ├── ws_hub.py                   # WebSocket(/stream) 연결 관리 + 브로드캐스트
│   └── routers/
│       ├── device.py                # 인덕션(디바이스) 조회용 REST (tag=device)
│       ├── dashboard.py              # 프론트 대시보드용 REST (tag=dashboard)
│       └── stream.py                 # WebSocket /stream
└── tests/simulate_device.py          # 실제 하드웨어 없이 테스트할 수 있는 가짜 인덕션 (화구 1개)
```

파일이 이렇게 나뉘어 있는 이유: 처음엔 "그냥 main.py 하나에 다 쓰면 안 되나?" 싶을 수 있는데,
FastAPI 프로젝트가 조금만 커져도 역할별로 파일을 나눠두면 어디를 고쳐야 할지 훨씬 빨리 찾을 수 있습니다.
(예: MQTT 토픽 이름을 바꾸고 싶다 → config.py만 보면 됨)

---

## 2. 개발 환경 설치

Python 3.11 이상을 권장합니다. (터미널에서 `python3 --version`으로 확인)

```bash
cd induction-backend

# 가상환경 생성 (프로젝트마다 독립된 패키지 공간을 만드는 것 — 필수는 아니지만 강력 추천)
python3 -m venv venv
source venv/bin/activate       # Windows는: venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# 환경변수 파일 생성 (기본값 그대로 써도 로컬 테스트는 가능합니다)
cp .env.example .env
```

> 참고: 이 코드는 Cowork 세션 안에서 문법 검사(py_compile)와 스키마/규칙 로직 단위 테스트까지는
> 통과시켰지만, 이 샌드박스에는 PyPI 네트워크 접근이 막혀 있어서 `fastapi`, `paho-mqtt`를
> 직접 설치해 서버를 띄우는 것까지는 이 환경에서 실행해보지 못했습니다.
> 실제 개발 환경(본인 PC)에서는 위 `pip install -r requirements.txt`가 정상 동작할 겁니다.
> 혹시 설치나 실행 중 에러가 나면 에러 메시지를 그대로 알려주시면 같이 고치겠습니다.

---

## 3. 로컬 MQTT 브로커(Mosquitto) 띄우기

두 가지 방법 중 편한 걸 쓰세요.

**방법 A) Docker로 실행 (Docker 설치되어 있다면 가장 간단)**
```bash
docker compose up -d mosquitto
```
(서비스 이름 없이 `docker compose up -d`를 하면 MongoDB와 백엔드까지 전부 뜹니다. 10장 참고)

**방법 B) Mosquitto 직접 설치**
```bash
# macOS
brew install mosquitto
mosquitto -c mosquitto/mosquitto.conf

# Ubuntu/Debian
sudo apt install mosquitto
mosquitto -c mosquitto/mosquitto.conf
```

정상적으로 뜨면 1883 포트에서 대기 중이라는 로그가 보입니다.

---

## 4. FastAPI 서버 실행

새 터미널을 열고 (가상환경 다시 activate):
```bash
uvicorn app.main:app --reload
```

Swagger 문서는 `http://127.0.0.1:8000/docs` 하나이고, 기능별 섹션으로 나뉘어 있습니다:
회원 정보 / 낙상 사고 감지 / AI 재실 판단 / 인덕션 제어 / 대시보드 화면 / 안전 이벤트

여기서 바로 API를 테스트해볼 수 있습니다.

---

## 5. 가짜 인덕션으로 전체 흐름 테스트

하드웨어가 아직 없으니, 하드웨어 역할을 대신하는 시뮬레이터를 또 다른 터미널에서 실행합니다.

```bash
source venv/bin/activate
python tests/simulate_device.py
```

이 스크립트는 3초마다 인덕션 상태를 MQTT로 publish하고, 제어 명령이 오면 반영해서
다시 상태에 반영합니다. 로그가 계속 출력되는지 확인하세요.

이제 세 개의 터미널이 동시에 떠 있어야 합니다: **① Mosquitto, ② uvicorn 서버, ③ 시뮬레이터**

### 5-1. 상태(telemetry) 조회
```bash
curl http://127.0.0.1:8000/api/v1/devices/induction-01/telemetry
```
시뮬레이터가 publish한 최신 telemetry(JSON)가 그대로 보이면 성공입니다.

### 5-2. 제어 명령 보내기 (화구 화력을 5로 설정)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/appliances/induction-01/burners/burner-1/commands \
  -H "Content-Type: application/json" \
  -d '{"type": "set_level", "level": 5}'
```
- uvicorn 로그에 "제어 명령 발행" 이 찍히고
- 시뮬레이터 터미널에 "제어 명령 수신" + "명령 적용 결과=applied" + "ack 발행" 이 찍히고
- 응답으로 받은 `commandId`를 `GET /api/v1/commands/{commandId}`로 조회하면
  상태가 `sent` → (시뮬레이터가 ack를 보낸 뒤) `acked`로 바뀌는 걸 확인할 수 있습니다.
  (명령이 실제로 적용됐다는 증거이자, 팀이 확정한 "별도 ack" 방식입니다.)

### 5-3. 과열 상황 테스트
화력을 계속 높게 켜두면(level 8~9) 시뮬레이터가 온도를 계속 올려서 150도가 넘는 순간
자동으로 `overheated` 상태가 됩니다. 이 상태에서 다시 켜보면:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/appliances/induction-01/burners/burner-1/commands \
  -H "Content-Type: application/json" \
  -d '{"type": "turn_on"}'
```
`409 Conflict`와 함께 `BURNER_OVERHEATED` 사유가 나오는 걸 확인할 수 있습니다.
(MQTT까지 나가지도 않고 서버 단계에서 막힙니다 — "overheated 상태에서는
turn_on/set_level을 거부한다" 규칙입니다. turn_off는 항상 허용됩니다.)

### 5-4. 실시간 스트림 / 부재중 자동 제어 (v0.2 신규)
```bash
# 실시간 이벤트 구독 (다른 터미널에서, websocat 등 WS 클라이언트 필요)
websocat ws://127.0.0.1:8000/api/v1/stream

# AI 모델이 "10분 넘게 자리를 비웠다"고 보고하는 상황을 재현
curl -X POST http://127.0.0.1:8000/api/v1/presence \
  -H "Content-Type: application/json" \
  -d '{"room": "kitchen", "zone": "kitchen", "present": false, "absentSec": 700, "confidence": 0.95, "observedAt": "2026-09-30T10:00:00+09:00", "modelVersion": "v1"}'
```
`absentSec`이 정책(`GET /api/v1/policies/kitchen-absence`)의 `offAfterSec`(기본 600초)을 넘으면
서버가 자동으로 화구를 끄고 `auto_power_off` 안전 이벤트를 생성하며, WS로 구독 중이면 실시간으로 알림이 옵니다.

---

## 6. 지금 이 코드가 아직 안 하는 것 (다음 단계)

- **DB는 MongoDB(Atlas)에 연결됨**: 읽기는 서버 메모리에서 하고, 쓰기는 메모리와 DB 양쪽에 반영합니다.
  서버가 시작될 때 DB의 내용을 메모리로 불러오므로 재시작해도 데이터가 유지됩니다. `.env`에
  `MONGODB_URI`가 없으면 DB 없이 메모리로만 동작합니다 (`GET /health`의 `storage` 값으로 확인).
  컬렉션 구조는 `docs/DB.md` 참고.
- **부재중 자동 제어는 v0.2에서 반영됨**: "조리 중 이탈 감지 시 자동으로 화력을 낮춘다/끈다"
  로직은 `safety_service.evaluate_presence()`에 구현되어 있습니다. 다른 팀원이 만드는 실제
  AI 재실 판단 모델이 `POST /api/v1/presence`를 호출하기만 하면 이 로직이 그대로 동작합니다.
  지금은 이 엔드포인트를 curl로 흉내 내서 테스트하고 있는 상태입니다.
- **인증 없음**: 지금은 아무나 MQTT/REST에 접근할 수 있습니다. 대회 시연 단계에서 필요하면 추가합니다.
- **환경 센서 데이터 없음**: `/api/v1/snapshot` 응답의 `rooms.kitchen.environment`는 아직 빈
  객체로만 채워둔 자리입니다. 실제 센서 연동 시 채워 넣으면 됩니다.

이것들은 지금 당장 필요한 게 아니라면, 먼저 이 기본 골격이 잘 도는 것부터 확인하고
다음 단계로 넘어가는 걸 추천합니다.

---

## 7. 낙상 사고 안전 기능 (v0.2.1, v0.3.1 단계화)

인덕션 비상 차단 + 전등 깜빡임 + 사용자 → 보호자 → 자동 신고 단계별 알림 기능입니다. 전체 로직은 `app/fall_service.py` 하나에 모여 있고,
라우터(`app/routers/dashboard.py`)는 입출력 변환만 합니다.

**흐름**

1. AI 중앙 판정 엔진이 `POST /api/v1/ai/decisions`(scenario `fall_detected`) 또는
   `POST /api/v1/safety/fall-events`로 낙상을 알립니다. 판단은 AI가, 조치는 서버가 합니다.
2. 접수 즉시 서버가 수행:
   - 인덕션 **비상 전원 차단** (재실 부재 정책의 점진적 저감과 달리 바로 `turn_off`)
   - 전등 **10초 깜빡임** (낙상 구역 전등, 없으면 첫 번째 전등)
   - 안전 이벤트(`fall_detected`) 생성 + WebSocket `/stream`으로 대시보드에 실시간 알림
   - **1차**: 사용자 본인에게 SMS로 확인 링크 발송 (`확인 링크 = FRONTEND_BASE_URL/fall/{incidentId}?token=...`)
3. **2차**: `userAlertWaitSec`(기본 30초) 안에 응답이 없으면 보호자에게 같은 확인 링크 발송
   (안전 이벤트 `fall_escalated`). 사용자 문자를 못 보내도 대시보드로 응답할 수 있으므로 대기는 그대로이며,
   `userAlertWaitSec`를 0으로 하면 사용자와 보호자에게 동시에 보냅니다.
4. **3차**: 보호자 알림 뒤 `autoReportSec`(기본 60초) 안에도 응답이 없으면 `auto_reported`로
   처리합니다 (안전 이벤트 `fall_auto_reported`).
5. 사용자나 보호자가 링크(프론트가 만드는 모바일 페이지)에서 "괜찮음"/"신고"를 누르면 그 페이지가
   `POST /api/v1/fall-incidents/{id}/resolve` 또는 `.../report`를 `?token=...`과 함께 호출하고,
   그 뒤 단계는 진행되지 않습니다. 서버를 다시 켜도 진행 중인 단계를 이어갑니다.

**새 엔드포인트**

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| PUT | `/api/v1/user` | 사용자(거주자 본인) 연락처 등록/변경. 저장과 동시에 확인 문자 발송 |
| GET | `/api/v1/user` | 사용자 연락처 조회 |
| PUT | `/api/v1/guardian` | 보호자 연락처 등록/변경 (1명). 저장과 동시에 확인 문자 발송 |
| GET | `/api/v1/guardian` | 보호자 연락처 조회 |
| GET | `/api/v1/sms-logs` | 문자 발송 이력 조회 (본문은 저장하지 않음) |
| POST | `/api/v1/safety/fall-events` | 낙상 감지 AI 모델 -> 서버 |
| GET | `/api/v1/fall-incidents/{id}` | 낙상 사건 상태 조회 (프론트 모바일 페이지가 폴링용으로 사용 가능) |
| POST | `/api/v1/fall-incidents/{id}/resolve?token=` | "해결" 처리 |
| POST | `/api/v1/fall-incidents/{id}/report?token=` | "신고" 처리 |
| GET/PUT | `/api/v1/policies/fall-safety` | `userAlertWaitSec`, `autoReportSec` 조회/수정 |

**SMS 연동**: 솔라피(SOLAPI) (`app/sms_service.py`). 네이버 SENS는 사업자 계정 전용이라 변경했습니다.
솔라피 콘솔에서 발신번호를 등록하고 API Key를 만들어(허용 IP에 서버 외부 IP 입력) `.env`의
`SOLAPI_API_KEY` / `SOLAPI_API_SECRET` / `SOLAPI_SENDER_PHONE`에 채워 넣으면 됩니다. **비워둬도 서버는
정상 동작**하고, 그럴 땐 실제 발송 대신 로그만 남깁니다 — 키 발급 전에도 나머지 흐름은 테스트 가능.

**테스트 방법**: `python tests/simulate_fall.py` 로 가짜 낙상 이벤트를 하나 보내고,
출력된 `confirmUrl`로 해결/신고를 curl로 시뮬레이션해볼 수 있습니다.

**아직 안 된 것 / 다음 단계**:
- 모바일 확인 페이지(해결/신고 버튼 UI)는 프론트 팀 작업 — 백엔드는 API만 제공
- "신고" 처리는 지금 안전 이벤트/로그만 남깁니다. 실제 119·응급 연동은 아직 없음 (범위 밖)
- 보호자는 현재 1명만 지원 (팀 결정)
- 날씨 안내는 v0.3.2에서 백엔드에 추가 (9-2 참고)

---

## 9. 실제 임베디드 하드웨어와 연동하기

지금까지는 `tests/simulate_device.py`라는 가짜 인덕션으로 테스트했습니다. 실제 ESP32/Pico W로 바꿀 때 체크할 것들을 정리합니다.

1. **네트워크**: 로컬 개발에서는 브로커가 `localhost`였지만, 실제 기기는 물리적으로 분리된 장치라 **같은 Wi-Fi 네트워크**에 있어야 하고, `.env`의 `MQTT_BROKER_HOST`를 브로커가 돌아가는 컴퓨터(또는 최종적으로 Raspberry Pi 4)의 **LAN IP**로 바꿔야 합니다. 맥에서 IP 확인: `ipconfig getifaddr en0`. Mosquitto 기본 설정은 이미 모든 네트워크 인터페이스에서 접속을 받으므로, 방화벽이 1883 포트를 막고 있지 않은지만 확인하면 됩니다.

2. **데이터 계약(스키마) 고정**: 하드웨어 담당 팀원에게 `app/schemas.py`와 인덕션 데이터 명세 PDF를 그대로 전달해서, Pico W 펌웨어가 publish하는 JSON이 필드명/값/타입까지 정확히 일치하도록 맞춰야 합니다. 조금이라도 다르면 서버가 파싱에 실패합니다.

3. **토픽 이름 고정**: `home/kitchen/induction/induction-01/state`, `.../command` — 이 문자열을 펌웨어 코드에도 그대로 박아넣어야 합니다 (`app/config.py`의 템플릿 참고).

4. **단계적 검증(중요)**: 센서/액추에이터 배선을 다 하기 전에 먼저 "연결"만 확인하는 걸 추천합니다.
   - 우리 쪽: `mosquitto_sub -h <브로커 IP> -t 'home/kitchen/induction/+/state' -v` 로 원시 MQTT 메시지를 직접 구독해서 지켜봅니다.
   - 하드웨어 쪽: 센서 로직 없이 하드코딩된 더미 JSON 하나만 몇 초마다 publish하는 최소 펌웨어를 먼저 올려서, 위 `mosquitto_sub` 화면에 찍히는지 확인합니다.
   - 그 다음 `GET /induction/.../state`로도 같은 값이 조회되는지 확인 → 여기까지 되면 통신 자체는 검증된 것이고, 이후 실제 온도 센서/릴레이 제어 로직을 붙여나가면 됩니다.

5. **신뢰성 보강**: 지금은 QoS 1만 쓰는데, 상태 메시지에 `retain` 플래그를 추가하면(하드웨어 쪽 publish 코드에서 설정) 서버가 재시작돼도 마지막 상태를 바로 조회할 수 있습니다. 또한 명세서의 "네트워크 단절 시 Fallback 안전 로직"은 서버가 아니라 **Pico W 펌웨어 쪽에 반드시 구현**되어야 하는 부분이라는 걸 하드웨어 팀과 공유해주세요.

6. **최종 배포 위치 이전**: 대회 보드(라즈베리파이 4, LG AI-Native OS)에서는 Docker로 실행합니다. 10장을 참고하세요. 하드웨어가 항상 같은 주소로 접속할 수 있게 보드의 IP를 고정해 두는 것이 좋습니다.

7. **보안**: 지금 Mosquitto는 `allow_anonymous true`로 인증 없이 열려 있습니다. 발표/시연 시 공유 와이파이에서는 같은 네트워크에 있는 아무나 명령을 위조해서 보낼 수 있으니, 최소한 사용자명/비밀번호 인증(`.env`의 `MQTT_USERNAME`/`MQTT_PASSWORD`, `mosquitto_passwd`로 설정) 정도는 시연 전에 추가하는 걸 권장합니다.

---

## 9-1. AI 중앙 판정 엔진 · 전등 · 정수기 연동 (v0.3)

모든 제어 판단은 AI 중앙 판정 엔진이 하고, 백엔드는 판단 결과(`POST /api/v1/ai/decisions`)를 받아
인덕션·전등·정수기를 제어하고 기록합니다. 판정 엔진용 API와 전등·정수기 MQTT 메시지 형식은
`docs/AI-INTEGRATION.md`에 정리되어 있습니다. (v0.3부터 `POST /presence`는 저장·전달만 하고 직접 제어하지 않습니다.)

## 9-2. 날씨 · 음성 안내 (v0.3.2, v0.4.1)

- 판정 엔진이 판단에 `announcement`(안내 문장)를 담아 보내면 대시보드로 WebSocket `ai.announcement`를 보내고,
  대시보드가 화면 표시 + 음성 재생을 합니다. 날씨는 판정 엔진이 `GET /api/v1/weather`로 가져가 문장에 넣습니다.
- 판단에 `expiresAt`을 담으면, 그 시각이 지나서 도착한 판단은 실행하지 않고 `status: expired`로 기록합니다
  (낙상은 예외로 항상 실행).

- 판단 결과에 `weatherBriefing: true`가 오면(물 출수 시나리오) 날씨 안내 문장을 만들어 대시보드(WebSocket
  `weather.briefing`)로 보내고 판단 기록에도 남깁니다. 대시보드는 `GET /api/v1/weather`로도 조회할 수 있습니다.
- 날씨는 Open-Meteo(API 키 불필요)에서 30분마다 미리 받아 메모리와 DB에 저장합니다. 대회장 인터넷이 끊겨도
  마지막으로 받은 날씨로 안내하고, 오래된 값이면 "몇 시 기준"을 붙입니다.
- 위치는 `.env`의 `WEATHER_LOCATION_NAME` / `WEATHER_LAT` / `WEATHER_LON` (기본 서울). 로직은 `app/weather_service.py`.

## 9-3. 엣지 노드 · 최종 재실 판단 결과 (v0.4)

```
엣지 노드 ──MQTT home/{구역}/edge/{노드ID}/features──> 서버 ──MQTT home/edge/combined(1초마다)──> 재실 판단 담당
재실 판단 담당 ──MQTT home/edge/result──> 서버(DB 저장) <──HTTP GET /api/v1/sensing/results/latest── AI 판정 엔진
```

- 서버는 노드 메시지를 판단하지 않고, 구역별 최신 메시지를 맵으로 합쳐 원본 그대로 전달합니다
  (`{"seq", "publishedAt", "locations": {구역: {"node": 원본 메시지}}}`, v0.4.2).
- 재실 판단 담당이 보낸 최종 결과만 DB(`sensing_results`)에 저장하고, AI 판정 엔진이 HTTP로 꺼내 씁니다.
- 토픽·메시지 형식: `docs/EDGE-MQTT.md`, 조회 API: `docs/AI-INTEGRATION.md`. 로직은 `app/edge_service.py`.
- 테스트: `docker compose --profile sim up -d`로 가짜 엣지 노드·가짜 최종 판단까지 함께 띄울 수 있습니다.

---

## 10. Docker로 실행하기 (라즈베리파이 4 / 노트북 / 맥)

MongoDB, Mosquitto, 백엔드를 컨테이너 3개로 한 번에 띄웁니다. 백엔드 이미지는 `develop`에 머지될 때마다
GitHub Actions가 빌드해서 GHCR(`ghcr.io/2026esec-sscc/homevis-backend`)에 올립니다. arm64(라즈베리파이 4·5, M 시리즈 맥)와
amd64(일반 노트북, 서버)를 모두 지원합니다.

```
docker compose
 ├ mongo      MongoDB 4.4 (데이터는 mongo-data 볼륨에 저장)
 ├ mosquitto  MQTT 브로커, 1883 포트
 ├ backend    FastAPI, 8000 포트
 └ simulator  가짜 인덕션 (선택, --profile sim 일 때만)
```

**1) 실행할 기기에 필요한 것**
- Docker와 Docker Compose 플러그인
- 이 저장소의 `docker-compose.yml`, `mosquitto/` 폴더, 그리고 `.env` 파일 (`git clone`으로 받거나 이 파일들만 복사)
- 처음 받을 때 인터넷 (GHCR과 Docker Hub에서 이미지를 받음)

**2) 이미지 받기 위한 로그인 (이미지가 비공개일 때, 기기마다 한 번)**

GitHub > Settings > Developer settings > Personal access tokens에서 `read:packages` 권한 토큰을 만든 뒤:
```bash
echo <토큰> | docker login ghcr.io -u <GitHub 아이디> --password-stdin
```

**3) 실행**
```bash
cp .env.example .env      # 값 채우기 (MONGODB_URI는 비워두면 로컬 MongoDB 사용)
docker compose pull       # 최신 이미지 받기
docker compose up -d      # 실행
curl http://localhost:8000/health   # {"status":"ok","storage":"mongodb"} 이면 정상
```
- 가짜 인덕션도 같이: `docker compose --profile sim up -d`
- 로그 보기: `docker compose logs -f backend`
- 종료: `docker compose down` (DB 데이터는 남음. 데이터까지 지우려면 `docker compose down -v`)
- 이미지 대신 이 PC의 코드로 직접 빌드: `docker compose up -d --build`
- 특정 커밋 버전으로 되돌리기: `.env`에 `IMAGE_TAG=sha-xxxxxxx` 추가 후 `pull`, `up -d`

**4) 인터넷이 없는 곳에서 설치할 때**

인터넷이 되는 PC에서 이미지를 파일로 저장해 USB로 옮깁니다. 받을 기기와 같은 CPU용(arm64)으로 받아야 합니다.
```bash
# 인터넷 되는 PC
docker pull --platform linux/arm64 ghcr.io/2026esec-sscc/homevis-backend:develop
docker pull --platform linux/arm64 mongo:4.4
docker pull --platform linux/arm64 eclipse-mosquitto:2
docker save -o homevis-images.tar ghcr.io/2026esec-sscc/homevis-backend:develop mongo:4.4 eclipse-mosquitto:2

# 보드
docker load -i homevis-images.tar
docker compose up -d
```

**주의**
- MongoDB는 기본으로 4.4를 씁니다. 라즈베리파이 4의 CPU에서는 5.0 이상이 실행되지 않기 때문입니다.
  4.4는 공식 지원이 끝난 버전이라 대회장 로컬 네트워크 안에서만 쓰는 것을 전제로 합니다.
  파이 5나 노트북에서 최신 버전을 쓰려면 `.env`에 `MONGO_IMAGE=mongo:7`을 넣으면 됩니다.
- MongoDB 버전을 바꾸면 기존 데이터(볼륨)를 열지 못할 수 있습니다. 특히 7에서 4.4로 내릴 때는 `docker compose down -v`로 데이터를 지운 뒤 실행하세요.
- MongoDB 포트(27017)는 그 기기 안에서만 접속할 수 있게 열어 두었습니다.
- Mosquitto는 아직 인증 없이 열려 있습니다(9장 7번). 공유 와이파이에서 시연하기 전에 인증을 추가해야 합니다.

---

## 막히면

설치/실행 중 에러 메시지가 나오면 그 메시지를 그대로 붙여넣어 주세요. 어느 단계(설치/브로커/서버/시뮬레이터)에서
막혔는지만 알려주시면 바로 원인을 찾아드릴 수 있습니다.
