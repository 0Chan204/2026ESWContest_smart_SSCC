# HomeVIS 인덕션 백엔드 — FastAPI + MQTT 처음부터 따라하기

ESWC 개발계획서 기준: 백엔드는 **Python FastAPI**, 가전과의 통신은 **MQTT(Mosquitto 브로커)**.
이 문서는 FastAPI/MQTT를 한 번도 안 써봤다는 가정으로, 개념 → 설치 → 실행 → 테스트 순서로 씁니다.

---

## 0. 먼저 개념만 짧게

- **FastAPI**: 파이썬으로 REST API(웹 서버)를 만드는 프레임워크. 대시보드(프론트)가 "지금 인덕션 상태 알려줘", "이렇게 제어해줘" 라고 호출하는 창구입니다.
- **MQTT**: 가전(인덕션)과 서버가 실제로 데이터를 주고받는 통신 방식. HTTP처럼 "요청하면 응답"이 아니라, 브로커(우체국)를 사이에 두고 서로 메시지를 던지고(publish) 받는(subscribe) 방식입니다.
- **Mosquitto**: MQTT 브로커 소프트웨어 이름. 이번 프로젝트에서는 이게 그 "우체국" 역할을 합니다.
- 이 프로젝트에서의 역할 분담:
  - 인덕션(가전) → MQTT publish → 우리 FastAPI 서버가 MQTT subscribe로 받아서 상태 저장
  - 대시보드 → FastAPI REST 호출(`POST /induction/{id}/control`) → 우리 서버가 MQTT publish → 인덕션이 subscribe해서 실행

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
│   ├── main.py                # FastAPI 앱 진입점
│   ├── config.py               # 설정값 (브로커 주소, 토픽 이름 등)
│   ├── schemas.py               # 인덕션 데이터 명세를 코드로 옮긴 것 (Pydantic 모델)
│   ├── rules.py                  # overheat 등 안전 규칙 검증 로직
│   ├── state_store.py             # 최신 상태를 잠깐 저장하는 메모리 저장소
│   ├── mqtt_client.py              # MQTT 연결/구독/발행 담당
│   └── routers/induction.py         # REST API 엔드포인트
└── tests/simulate_device.py          # 실제 하드웨어 없이 테스트할 수 있는 가짜 인덕션
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

`http://127.0.0.1:8000/docs` 로 들어가면 FastAPI가 자동으로 만들어주는 API 문서(Swagger UI)가 보입니다.
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

### 5-1. 상태 조회
```bash
curl http://127.0.0.1:8000/induction/induction-01/state
```
시뮬레이터가 publish한 최신 상태(JSON)가 그대로 보이면 성공입니다.

### 5-2. 제어 명령 보내기 (화구 1을 화력 5로 켜기)
```bash
curl -X POST http://127.0.0.1:8000/induction/induction-01/control \
  -H "Content-Type: application/json" \
  -d '{"element_1": {"state": "control_on", "level": 5}}'
```
- uvicorn 로그에 "제어 명령 발행" 이 찍히고
- 시뮬레이터 터미널에 "제어 명령 수신" + "명령 적용 완료" 가 찍히고
- 몇 초 후 시뮬레이터가 올리는 상태에서 element_1.state가 "on", level이 5로 바뀝니다.
- 다시 `GET /induction/induction-01/state`를 호출하면 `last_control.command_id`가
  방금 응답으로 받은 command_id와 같은 값인지 확인해보세요. (명령이 실제로 적용됐다는 증거)

### 5-3. 과열 상황 테스트
화력을 계속 높게 켜두면(level 8~9) 시뮬레이터가 온도를 계속 올려서 150도가 넘는 순간
자동으로 `overheat` 상태가 됩니다. 이 상태에서 다시 `control_on`을 보내보면:
```bash
curl -X POST http://127.0.0.1:8000/induction/induction-01/control \
  -H "Content-Type: application/json" \
  -d '{"element_1": {"state": "control_on"}}'
```
응답에 `"accepted": false` 와 함께 거부 사유가 나오는 걸 확인할 수 있습니다.
(MQTT까지 나가지도 않고 서버 단계에서 막힙니다 — 이게 명세서의 "overheat 상태에서는
control_on을 거부한다" 규칙입니다.)

---

## 6. 지금 이 코드가 아직 안 하는 것 (다음 단계)

- **DB 연동 없음**: 지금은 상태를 메모리에만 저장합니다. 서버를 재시작하면 사라집니다.
  개발계획서 기준으로는 제어 이력 → MariaDB, 센서 이벤트 로그 → MongoDB로 나눠 저장해야 합니다.
  (`state_store.py`의 함수들 내부만 DB 호출로 바꾸면 되도록 미리 구조를 잡아뒀습니다)
- **Context Fusion / Rule-based Decision Tree 없음**: 지금은 "요청받은 대로 제어"만 합니다.
  "조리 중 이탈 감지 시 자동으로 화력을 낮춘다" 같은 로직은, 다른 팀원이 만드는 Context Fusion
  결과를 받아서 이 서버의 `send_control`과 같은 방식으로 호출하는 코드를 추가하면 됩니다.
- **인증 없음**: 지금은 아무나 MQTT/REST에 접근할 수 있습니다. 대회 시연 단계에서 필요하면 추가합니다.

이 세 가지는 지금 당장 필요한 게 아니라면, 먼저 이 기본 골격이 잘 도는 것부터 확인하고
다음 단계로 넘어가는 걸 추천합니다.

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
