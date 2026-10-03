# HomeVIS Frontend

가정용 **태블릿·월패드 안전 대시보드**와, 낙상 시 보호자가 문자 링크로 여는 **모바일 확인 페이지**.

핵심 흐름은 가전 원격 제어가 아니라 **상태 모니터링 → 안전 판단 → 자동 조치 → 기록·피드백** 이다.
인덕션은 안전을 위해 **조회 전용**이며, 위험할 때 서버가 자동으로 화력을 낮추거나 전원을 끈다.

## 실행

```bash
npm install
npm run dev        # http://127.0.0.1:5173
npm run build      # 타입검사 + 정적 빌드 → dist/
npm run lint
npm audit
```

처음 열면 화면 모드(크게 보기 / 기본 보기)를 고른다. 레일 아래 **시연** 버튼으로 주방 이탈·과열·낙상·아침 자동 출수·기기 연결 끊김을 재현할 수 있다(목 데이터일 때만 표시).

## 화면

| 경로 | 기기 | 내용 |
| --- | --- | --- |
| `/home` | 태블릿 | 집 전체 상태 · 지금 위치(평면 약도) · 기기 · 최근 안전 기록 · 보호자 알림 |
| `/kitchen` | 태블릿 | 인덕션 온도 추이(과열 기준선) · 재실 감지 · 정수기 · 환풍기 · 이번 조리 흐름 |
| `/bathroom` | 태블릿 | 낙상 상태 · 욕실 조명 · 낙상 판단 단계 · 욕실 기록 |
| `/history` | 태블릿 | 안전 기록 필터·페이지 · 상세(판단 근거 · 자동 조치 피드백 · 조리 흐름) |
| `/settings` | 태블릿 | 화면 모드·글자 크기 · 비상 연락처 · 음성 · 안전 정책(관리자) · 언어 · 정보 |
| `/fall/:id?token=` | **보호자 휴대폰** | 낙상 확인 · 자동 신고 카운트다운 · 괜찮아요 / 신고 요청 · 119 전화 |

태블릿 화면 기준: **1280×800 · 1440×900 가로, 세로 스크롤 없음** (어르신 모드 글자 130% 포함).

## 디자인 원칙

- 연회색 바탕 + 흰 카드, 테두리 대신 면 대비. 색은 **상태를 알릴 때만** 쓴다.
- 상태는 색만으로 표현하지 않는다 — 항상 점·아이콘 + 글자.
- 왼쪽 내비게이션 레일(태블릿 설정 앱·월패드 방식)로 가로 화면의 세로 공간을 확보하고, 마이크 버튼을 레일에 고정해 콘텐츠를 가리지 않는다.
- 어르신 모드는 정보를 줄이고 크게. 글자 크기는 rem 기준이라 설정값이 모든 글자에 적용되고, 여백·아이콘은 px 로 고정해 레이아웃이 흔들리지 않는다.

## 백엔드(HomeVIS-Backend v0.2.1)와의 정합

`src/data/source/types.ts` 의 실시간 메시지 이름과 필드는 백엔드 WebSocket(`/api/v1/stream`)과 같다.
목 데이터 소스(`mockSource.ts`)는 백엔드 서버 규칙(과열 150°C/60°C, 부재 60/180/600초, near 2배, 낙상 자동 신고)을 축소 재현한다.

| 화면 | 백엔드 API |
| --- | --- |
| 인덕션 상태 | WS `burner.telemetry` · `session.updated` · `safety.event` |
| 자동 조치 피드백 | `POST /safety-events/{id}/feedback` |
| 비상 연락처 | `GET/PUT /user` · `/guardian` |
| 안전 정책 | `GET/PUT /policies/kitchen-absence` · `/policies/fall-safety` |
| 낙상 경보 | WS `fall.incident` |
| 보호자 페이지 | `GET /fall-incidents/{id}` · `POST .../resolve?token=` · `.../report?token=` |

`(FE 확장)` 으로 표시한 메시지(정수기·환풍기·욕실 조명 상태, 사용자 위치, 연결 상태, 안내 문장)는 백엔드에 아직 없어 프론트가 먼저 정의했다.

### 연동 전 백엔드에 필요한 것

- **CORS** 허용 목록 (프론트·백엔드 출처가 다를 경우)
- **인증** — 현재 누구나 정책 변경·제어 API 호출 가능. 사용자용 인덕션 제어 엔드포인트는 막아 둘 것
- `FRONTEND_BASE_URL` 을 **외부에서 접근 가능한 HTTPS 주소**로 (보호자 휴대폰에서 열려야 함)
- `GET /fall-incidents/{id}` 에도 token 검사
- 정수기·환풍기·조명·위치 이벤트, 안전 이벤트 목록의 날짜·검색 필터

`.env` 에 `VITE_API_BASE_URL` 을 넣으면 그 출처만 CSP `connect-src` 에 자동 추가된다. (`VITE_` 값은 번들에 그대로 들어가므로 시크릿 금지)

## 보안·개인정보

- 프로덕션 빌드에 CSP 자동 주입 (`default-src 'self'`), 외부 CDN·분석 도구·유료 API 없음
- `dangerouslySetInnerHTML` · `innerHTML` · `eval` · 인증정보 localStorage 저장을 ESLint 로 차단
- localStorage 에는 화면 설정만 저장(읽을 때 검증). **연락처는 브라우저에 저장하지 않는다**
- 연락처는 화면에 가운데를 가려 표시(`010-****-5678`), 입력란 자동완성 끔
- 보호자 링크의 token 은 읽은 즉시 주소창에서 제거, 메모리에만 보관
- 음성 인식(외부 전송 가능)은 기본 꺼짐 + 고지. 위험 알림 읽어주기(TTS)는 **기기 내장 음성만** 사용

배포 서버에서 추가로 `frame-ancestors 'none'` 헤더와 SPA fallback(`try_files $uri /index.html`)이 필요하다.

## 구조

```
src/
├─ app/            App(라우트) · AppShell · NavRail · PageHeader
├─ features/
│  ├─ home/        홈 · 평면 약도
│  ├─ kitchen/     주방
│  ├─ bathroom/    욕실
│  ├─ history/     안전 기록 · 상세 · 조리 흐름
│  ├─ settings/    설정 · 연락처 · 안전 정책
│  ├─ devices/     기기 타일 · 기기 상세
│  ├─ alerts/      상태 배너 · 자동 조치 안내 · 낙상 경보 · 시연 도구
│  ├─ fall/        보호자 모바일 확인 페이지
│  ├─ voice/       음성 명령
│  └─ onboarding/  최초 모드 선택
├─ components/     DeviceIcon · ui/(Card · Button · Sheet · Toggle · Segmented · Sparkline · Pagination …)
├─ data/           seed · source/(types · mockSource · httpSource) · fallApi · demoChannel
├─ store/          HomeStore · PreferencesContext
├─ hooks/  lib/  i18n/  types/
```
