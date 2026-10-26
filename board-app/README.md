# HomeVIS 보드 화면 (Flutter)

LG ATLAS OS 보드(Raspberry Pi 5)에 설치하는 HomeVIS 대시보드입니다.
보드에는 브라우저가 없어서, 웹 대시보드(React v5, 저장소 루트의 `src/`)를 Flutter 로 그대로 옮겼습니다.
같은 백엔드(HomeVIS-Backend v0.7.x) API · WebSocket 을 쓰고, 화면 구성 · 문구 · 색도 웹과 같습니다.

- 앱 이름 `homevis_gui`, 앱 ID `com.atlas.app.homevis_gui`, 설명 "HomeVIS dashboard"
- Flutter **3.27.4** 고정 (보드 엔진 버전). `pubspec.yaml` 이 다른 버전을 막습니다
- 순수 Dart 패키지만 사용: `http`, `web_socket_channel`, `provider`, `lucide_icons` (네이티브 코드가 있는 패키지 없음)
- 글꼴 Pretendard 를 앱에 넣었습니다 (`assets/fonts`, SIL OFL 1.1 — `assets/fonts/OFL.txt`). 실행 중 내려받는 것 없음
- 터치 · 마우스만 가정합니다 (키보드 입력 화면 없음). 누르는 곳은 48×48 이상
- 보드 파일 시스템이 읽기 전용이라 설정(테마 · 모드 · 글자 크기)은 메모리에만 둡니다. 켤 때마다 처음 값으로 시작

## 화면

왼쪽 레일(홈 · 주방 · 욕실 · 기록 · 설정) + 상단(날짜 · 제목 · 날씨 · 시계) + 상태 배너. 탭 전환만 있고 라우팅은 없습니다.
기준 화면은 1280×720 이고, 더 작으면 배치를 유지한 채 비율대로 줄이고(예: 1024×600), 더 크면 칸이 넓어집니다.

| 화면 | 일반 모드 | 어르신 모드 |
| --- | --- | --- |
| 홈 | 집 상태 카드(주방 · 욕실 · 보호자) + 지금 위치 평면도(주방 \| 침실 \| 욕실, 위치 점 · 신뢰도 · 전구 켜고 끄기) + 기기 카드 5개 | 상태 한 줄 + 큰 타일 4개 |
| 위치 크게 보기 | 재실 감지: 공간별 신뢰도 · 행동 · 최근 1분 그래프 · 센서 노드 신호(2.5초마다) · 실시간/갱신 멈춤 + 조명 밝기 · 환풍기 풍량 · 공기청정기 | 공간별 큰 스위치 |
| 주방 | 인덕션(조회 전용, 큰 온도 · 최근 3분 그래프 · 과열선) · 재실 · 정수기 · 환풍기 · 이번 조리 \| 주방 기록 | 인덕션 · 재실 큰 타일 |
| 욕실 | 상태 패널 · 조명/환풍기/재실 타일 · 낙상 대응 단계 · 욕실 기록 | 큰 글씨 상태 · 타일 |
| 기록 | 날짜별 묶음 · 분류(전체/화재 예방/낙상/생활 자동화) · 공간 · 기간(오늘/7일/30일) · 쪽 넘김 · 상세 · 피드백 · 최근 7일 | 같은 화면, 큰 글씨 · 쪽당 3~4건 |
| 설정 | 테마(라이트/다크/시스템) · 화면 모드 · 비상 연락처(보기만) · 정보 | + 글자 크기 100~130% |

시트 · 알림: 기기 상세(전등 밝기 단계 0/20/100, 환풍기 약/중/강, 공기청정기 전원 · 자동/수동 · PM2.5/PM10/등급, 인덕션 · 정수기 정보, 끊긴 기기 다시 연결),
날씨(비 소식 한 줄 · 시간대별 · 체감/습도/강수), 낙상 경보(서버가 실제로 한 일만: 문자 보냄 / 본인 응답 대기 카운트다운 / 못 보냄),
안전 조치 안내(피드백), AI 안내 토스트, 기기 제어 실패 토스트, 음성 명령 패널.

## 폴더 구조

```
lib/
  main.dart              앱 시작 (전체화면)
  main_health.dart       연결 확인용 작은 앱 (GET ${API_BASE}/health)
  config.dart            --dart-define 값 (API_BASE · DEFAULT_MODE · CANVAS_SCALE)
  app/                   앱 틀 · 레일 · 상단 · 화면 맞춤(1280×720 기준)
  data/                  백엔드 연동: home_source(REST · WS · 폴링) · parse(응답 검사) · translator(기기 · 실시간 메시지 변환)
  models/types.dart      화면 도메인 타입
  store/                 화면 상태(리듀서) · 설정 · 토스트 · TTS 연결 지점(Speaker)
  features/              home · devices · kitchen · bathroom · history · settings · alerts · weather · voice
  ui/                    공용 부품 (타일 · 목록 · 세그먼트 · 스위치 · 시트 · 밝기 슬라이더 · 그래프)
  theme/                 디자인 토큰 (웹 index.css 와 같은 값, 라이트 기본 · 다크)
  util/                  문구 · 시간 형식
test/                    단위 · 위젯 테스트 (백엔드 없이)
```

## 설정 값 (`--dart-define`)

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `API_BASE` | `http://127.0.0.1:8000` | 백엔드 주소. REST 는 `/api/v1`, 실시간은 `ws://…/api/v1/stream` |
| `DEFAULT_MODE` | `normal` | `normal` 또는 `elderly`. 켤 때의 화면 모드 |
| `CANVAS_SCALE` | `0` (자동) | 1920×1080 모니터에서 1280×720 배치를 크게 보이려면 `1.5` |

키 · 토큰 · 비밀번호는 넣지 않습니다. 보드 IP 같은 주소도 코드에 적지 않습니다.

## Mac 에서 실행

Flutter 3.27.4 를 설치한 뒤 (`flutter --version` 으로 확인):

```bash
cd board-app
flutter pub get
flutter analyze
flutter test
```

**macOS 앱** (Xcode 필요): 백엔드를 같은 Mac 에서 띄우고

```bash
flutter run -d macos --dart-define=API_BASE=http://127.0.0.1:8000
```

**Chrome**: 백엔드에 CORS 설정이 없어 브라우저가 다른 출처 요청을 막습니다.
웹 빌드를 백엔드와 같은 출처로 띄우는 프록시가 필요합니다 (예: 정적 파일은 `build/web`, `/api` 는 `http://127.0.0.1:8000` 으로 넘기고 WebSocket 도 허용).

```bash
flutter build web --release --no-web-resources-cdn --dart-define=API_BASE=http://127.0.0.1:<프록시 포트>
# build/web 을 프록시로 띄운 뒤 http://127.0.0.1:<프록시 포트>/ 접속
```

## 보드에 올리기 (LG 개발 컨테이너에서)

LG 가 배포한 Docker 개발 컨테이너 안의 `flutter-atlas` CLI 로 진행합니다. 자세한 옵션은 LG 의 Flutter CLI 가이드를 따릅니다.

1. 컨테이너 안에서 이 폴더로 이동해 ATLAS 플랫폼 폴더를 만듭니다 (`atlas/` 가 생깁니다)
   ```bash
   cd board-app
   flutter-atlas create --platforms atlas .
   ```
2. 생성된 `appinfo.json` 을 확인합니다: 앱 ID `com.atlas.app.homevis_gui`, 설명 `HomeVIS dashboard`, 전체화면 실행
3. 릴리스 IPK 빌드 (백엔드가 보드 안 Docker 에서 돌면 주소는 127.0.0.1)
   ```bash
   flutter-atlas build atlas --ipk --release --dart-define=API_BASE=http://127.0.0.1:8000
   # 어르신 모드로 시작: --dart-define=DEFAULT_MODE=elderly
   # 1920×1080 모니터: --dart-define=CANVAS_SCALE=1.5
   ```
   결과물은 `build/atlas/arm64/release/ipk/` 아래에 생깁니다
4. 연결만 먼저 확인하려면 건강 확인 앱을 같은 방법으로 빌드합니다 (앱 ID 가 같으니 하나씩 설치)
   ```bash
   flutter-atlas build atlas --ipk --release -t lib/main_health.dart --dart-define=API_BASE=http://127.0.0.1:8000
   ```
5. 보드(`<보드 IP>`)를 기기로 등록한 뒤 `flutter-atlas install -d <기기 ID>` 로 설치하거나,
   가이드의 직접 설치 절차(IPK 를 `<보드 IP>` 로 복사 → `opkg` 설치 → `appinfo.json` 의 실행 명령)로 설치합니다

`atlas/` 폴더는 컨테이너에서 만들어지므로 이 저장소에는 아직 없습니다. 만든 뒤 커밋할지는 팀에서 정합니다.

## 동작 메모

- 처음 불러오기에 실패하면 "서버에 연결하지 못했어요 + 다시 시도" (보드 부팅 직후 백엔드가 늦게 뜨는 경우)
- WebSocket 이 끊기면 1초부터 10초까지 늘려 가며 다시 연결하고, 놓친 안전 이벤트는 `?since=<마지막 이벤트 id>` 로 받습니다
- 기기 온라인 상태는 `GET /devices` 를 15초마다 확인합니다
- 기기 제어 결과는 WebSocket `device.state` 로만 반영합니다. 밝기 슬라이더만 보낸 값을 최대 5초 먼저 보여줍니다 (웹과 같음)
- 서버 응답은 그대로 믿지 않습니다. 빠지거나 모르는 값은 기본값으로 두고, 이상한 메시지는 버립니다 (테스트 포함)

## 아직 없는 것

- **음성 인식(STT)** 미정: 마이크 입력이 없습니다. 다른 장치가 `POST /voice/commands` 로 보낸 명령의 진행 상황(`voice.status`)을 패널에 보여주고, 확인 창에서 실행/취소를 보냅니다. 인식기가 정해지면 `VoiceService.send(text)` 로 문장을 보내면 됩니다
- **음성 안내(TTS)** 미정: 글자로만 보여줍니다. `store/speaker.dart` 의 `Speaker` 를 구현해 `main.dart` 에서 넘기면 안내 · 낙상 경보 · 음성 답변이 읽힙니다
- 연락처 등록 · 안전 정책 수정은 키보드가 필요해 웹 대시보드에서 합니다 (보드는 보기만)
- 인덕션은 안전을 위해 화면에서 제어하지 않습니다 (조회 전용, 웹과 같음)
