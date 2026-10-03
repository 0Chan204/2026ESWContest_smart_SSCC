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
├── docker-compose.yml        # 로컬 Mosquitto 브로커 실행용
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
docker compose up -d
```

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

- **DB 연동 없음**: 지금은 모든 상태(telemetry, 명령, 안전 이벤트, 세션, 정책)를 메모리에만
  저장합니다(`state_store.py`). 서버를 재시작하면 사라집니다. 개발계획서 기준으로는 제어 이력 →
  MariaDB, 센서 이벤트 로그 → MongoDB로 나눠 저장해야 합니다. (`state_store.py`의 함수들
  내부만 DB 호출로 바꾸면 되도록 구조를 잡아뒀습니다 — DB 종류는 아직 팀에서 미정)
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

## 7. 낙상 사고 안전 기능 (v0.2.1)

보호자 알림 + 인덕션 비상 차단 기능입니다. 전체 로직은 `app/fall_service.py` 하나에 모여 있고,
라우터(`app/routers/dashboard.py`)는 입출력 변환만 합니다.

**흐름**

1. (아직 미구현/다른 팀원 담당) 낙상 감지 AI 모델이 `POST /api/v1/safety/fall-events`를
   호출합니다. 재실 판단 모델과 같은 패턴 — 모델은 "감지 사실"만 보고하고, 조치는 서버가 다 합니다.
2. 접수 즉시 서버가 동시에 수행:
   - 인덕션 **비상 전원 차단** (재실 부재 정책의 점진적 저감과 달리 바로 `turn_off`)
   - 안전 이벤트(`fall_detected`) 생성 + WebSocket `/stream`으로 대시보드에 실시간 알림
   - 등록된 보호자에게 **SMS**로 확인 링크 발송 (`확인 링크 = FRONTEND_BASE_URL/fall/{incidentId}?token=...`)
3. 보호자가 SMS 링크(프론트가 만드는 모바일 페이지)에서 "해결"/"신고"를 누르면 그 페이지가
   `POST /api/v1/fall-incidents/{id}/resolve` 또는 `.../report`를 `?token=...`과 함께 호출합니다.
4. `policies/fall-safety`의 `autoReportSec`(테스트 기본값 60초) 안에 아무 응답이 없으면
   서버가 알아서 `auto_reported`로 처리합니다 (안전 이벤트 `fall_auto_reported` 발생).

**새 엔드포인트**

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| PUT | `/api/v1/guardian` | 보호자 연락처 등록/변경 (1명). 저장과 동시에 확인 문자 발송 |
| GET | `/api/v1/guardian` | 보호자 연락처 조회 |
| POST | `/api/v1/safety/fall-events` | 낙상 감지 AI 모델 -> 서버 |
| GET | `/api/v1/fall-incidents/{id}` | 낙상 사건 상태 조회 (프론트 모바일 페이지가 폴링용으로 사용 가능) |
| POST | `/api/v1/fall-incidents/{id}/resolve?token=` | "해결" 처리 |
| POST | `/api/v1/fall-incidents/{id}/report?token=` | "신고" 처리 |
| GET/PUT | `/api/v1/policies/fall-safety` | `autoReportSec` 조회/수정 |

**SMS 연동**: 네이버 클라우드 플랫폼 SENS (`app/sms_service.py`). NCP 콘솔에서 서비스 ID/Access
Key/Secret Key/발신번호를 발급받아 `.env`의 `NAVER_SENS_*`에 채워 넣으면 됩니다. **비워둬도 서버는
정상 동작**하고, 그럴 땐 실제 발송 대신 로그만 남깁니다 — 키 발급 전에도 나머지 흐름은 테스트 가능.

**테스트 방법**: `python tests/simulate_fall.py` 로 가짜 낙상 이벤트를 하나 보내고,
출력된 `confirmUrl`로 해결/신고를 curl로 시뮬레이션해볼 수 있습니다.

**아직 안 된 것 / 다음 단계**:
- 모바일 확인 페이지(해결/신고 버튼 UI)는 프론트 팀 작업 — 백엔드는 API만 제공
- "신고" 처리는 지금 안전 이벤트/로그만 남깁니다. 실제 119·응급 연동은 아직 없음 (범위 밖)
- 보호자는 현재 1명만 지원 (팀 결정)
- 날씨 API 연동은 일단 스킵 (프론트에서 바로 가능하면 프론트에서 처리, 우선순위 낮음)

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

6. **최종 배포 위치 이전**: 지금은 맥에서 개발 중이지만, 개발계획서 기준 최종 중앙 허브는 Raspberry Pi 4입니다. 나중에는 이 프로젝트 폴더를 라즈베리파이로 옮겨 `pip install -r requirements.txt` → `uvicorn` 실행 → 고정 IP(또는 mDNS 호스트네임)로 하드웨어가 항상 같은 주소에 접속하게 만드는 작업이 필요합니다.

7. **보안**: 지금 Mosquitto는 `allow_anonymous true`로 인증 없이 열려 있습니다. 발표/시연 시 공유 와이파이에서는 같은 네트워크에 있는 아무나 명령을 위조해서 보낼 수 있으니, 최소한 사용자명/비밀번호 인증(`.env`의 `MQTT_USERNAME`/`MQTT_PASSWORD`, `mosquitto_passwd`로 설정) 정도는 시연 전에 추가하는 걸 권장합니다.

---

## 막히면

설치/실행 중 에러 메시지가 나오면 그 메시지를 그대로 붙여넣어 주세요. 어느 단계(설치/브로커/서버/시뮬레이터)에서
막혔는지만 알려주시면 바로 원인을 찾아드릴 수 있습니다.
