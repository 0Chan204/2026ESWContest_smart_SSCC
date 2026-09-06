# HomeVIS Frontend

주방에 설치된 **터치 태블릿 / 월패드**용 스마트홈 안전 모니터링 웹 앱.
집 안 공간의 사용자 상태와 가전 상태를 모니터링하고, 위험 상황을 감지해 안전 조치를 수행한 뒤
그 이력을 사용자가 확인할 수 있게 한다.

핵심은 가전 원격 제어가 아니라 **상태 모니터링 → 안전 판단 → 안전 처리 → 처리 이력** 이다.

---

## 실행

```bash
npm install
npm run dev        # http://127.0.0.1:5173
```

```bash
npm run build      # 타입체크 + 정적 빌드 → dist/
npm run preview    # 빌드 결과 미리보기
npm run lint       # ESLint (보안 규칙 포함)
npm run typecheck  # 타입 검사만
npm run audit      # 런타임 의존성 취약점 점검
```

## 기준 해상도

| 대상 | 해상도 | 비고 |
| --- | --- | --- |
| 태블릿 가로 | 1280 × 800 | |
| 주방 월패드 | 1440 × 900 | |

두 해상도 모두 **모든 화면에서 세로 스크롤이 생기지 않는다.**
어르신 모드에서 글자 크기를 최대(130%)로 올려도 마찬가지다.
내용이 넘칠 때는 스크롤 대신 카드 높이 조절 / 표시 건수 제한 / 페이지네이션으로 해결한다.

---

## 기술 스택

| 영역 | 선택 |
| --- | --- |
| 빌드 | Vite 6 |
| 언어 | TypeScript (strict) |
| UI | React 18 |
| 스타일 | Tailwind CSS v4 |
| 라우팅 | react-router v7 |
| 아이콘 | lucide-react |
| 토스트 | sonner |
| 상태 | React Context + useReducer (외부 상태관리 라이브러리 없음) |
| 음성 | 브라우저 내장 Web Speech API |

**런타임 의존성 5개.** 유료 SDK·CDN·분석 도구·클라우드 STT를 사용하지 않는다.

### 폰트

외부 폰트 CDN을 사용하지 않는다. 요청 0건 / 추적 0건 / 오프라인 동작을 위해
시스템 한글 폰트 스택(Apple SD Gothic Neo, Noto Sans KR, Malgun Gothic 등)을 사용한다.

Pretendard를 쓰려면 `public/fonts/` 에 woff2 서브셋을 넣고
`src/styles/index.css` 의 `@font-face` 주석을 해제하면 된다. CSP는 이미 `font-src 'self'` 로 허용되어 있다.

---

## 디렉터리 구조

```
src/
├─ app/          App, AppShell, NavBar, ConnectionBanner
├─ features/
│  ├─ onboarding/  최초 1회 모드 선택
│  ├─ home/        홈 (일반/어르신)
│  ├─ room/        주방·화장실 공통 화면
│  ├─ appliance/   가전 상세 팝업
│  ├─ safety/      위험 알림 / 안전 조치 결과
│  ├─ history/     처리 이력 + 상세
│  ├─ settings/    설정 드로어 + 글자 크기
│  └─ voice/       음성 버튼·패널·명령 매칭
├─ components/   재사용 프리미티브 (카드, 배지, 타임라인, 모달, 드로어, 페이지네이션)
├─ data/         목 데이터 + 데이터 소스 경계
├─ store/        PreferencesContext, HomeStateContext
├─ hooks/        useClock, useDismissable
├─ i18n/         ko / en 사전
├─ lib/          포맷·저장소·한국어 조사·클래스 결합
└─ types/        도메인 타입
```

---

## 데이터 소스 교체

현재는 목 데이터로 동작한다. 실시간 시뮬레이터가 환경값과 재실 상태를 주기적으로 갱신한다.

실제 백엔드를 붙일 때는 **`src/data/source/httpSource.ts` 한 파일만** 구현하면 되고,
화면 코드는 바뀌지 않는다. `SafetyDataSource` 인터페이스가 경계다.

```
VITE_API_BASE_URL=https://api.example.com   # 설정하면 httpSource 사용
```

> `VITE_` 로 시작하는 환경변수는 브라우저 번들에 **그대로 포함된다.**
> API 키·토큰·비밀번호를 절대 넣지 말 것.

---

## 보안

빌드 산출물에 적용된 것:

- **CSP** — `default-src 'self'` 기반. 외부 스크립트/폰트/이미지/통신을 전부 차단한다.
  (`vite.config.ts` 에서 프로덕션 빌드에만 주입. dev 서버는 HMR 때문에 제외)
- **XSS 차단** — `dangerouslySetInnerHTML`, `innerHTML` 직접 대입, `eval`, `new Function`,
  `document.write` 를 ESLint 규칙으로 금지한다. 모든 텍스트는 React 기본 이스케이프를 거친다.
- **localStorage** — UI 설정값(mode / fontScale / language / voice)만 저장한다.
  읽을 때 화이트리스트·범위 검증을 하므로 값이 조작되어도 기본값으로 안전하게 폴백한다.
  인증정보를 저장하는 코드는 ESLint 규칙으로 막혀 있다.
- **시크릿 없음** — 프론트엔드에 키·토큰이 존재하지 않는다.
- **외부 통신 없음** — 목 데이터 상태에서는 어떤 네트워크 요청도 발생하지 않는다.

### 배포 서버에서 추가로 설정할 것

CSP의 `frame-ancestors` 는 meta 태그로 적용되지 않으므로 **HTTP 헤더로** 넣어야 한다.
SPA 라우팅을 위한 fallback도 함께 필요하다.

```nginx
server {
    root /var/www/homevis/dist;

    # SPA 딥링크(/kitchen, /history 등) 처리
    location / {
        try_files $uri $uri/ /index.html;
    }

    add_header Content-Security-Policy "frame-ancestors 'none'" always;
    add_header X-Frame-Options            "DENY"          always;
    add_header X-Content-Type-Options     "nosniff"       always;
    add_header Referrer-Policy            "no-referrer"   always;
    add_header Permissions-Policy         "geolocation=(), camera=(), microphone=(self)" always;
}
```

마이크(음성 인식)는 **HTTPS 또는 localhost** 에서만 동작한다.

### 음성 인식과 개인정보

브라우저의 Web Speech API는 인식 처리를 위해 **음성이 브라우저 제공사 서버로 전송될 수 있다.**
그래서 이 기능은 **설정에서 기본 꺼짐**이며, 사용자가 명시적으로 켜야 마이크를 요청한다.
꺼져 있거나 미지원 브라우저에서는 데모 시뮬레이션으로 동일한 상태 전이를 보여준다.
(설정 화면에 이 내용이 고지되어 있다.)

완전 오프라인이 필요하면 `src/features/voice/speech.ts` 만 온디바이스 STT로 교체하면 된다.

---

## 비용

발생하는 과금이 **없다.**

- 모든 의존성이 MIT 계열 오픈소스
- 지도·AI·STT 등 유료 API 미사용 (음성은 브라우저 내장 기능)
- 외부 CDN·폰트·분석 도구 미사용
- 산출물이 정적 파일이라 백엔드가 함께 서빙하거나 기기 로컬 웹서버로 충분

---

## 설계 원칙

1. **음성으로 되는 것은 버튼으로도 된다.** Voice-only 기능을 만들지 않는다.
2. **상태를 바꾸는 음성 명령은 확인을 거친다.** 조회·이동만 즉시 실행한다.
3. **지원하지 않는 기능은 UI에 만들지 않는다.** `supportsControl: false` 인 기기는
   버튼도 음성도 제어를 제공하지 않는다. (인덕션은 안전상 자동 안전 조치만 수행)
4. **상태를 색상만으로 표현하지 않는다.** 항상 아이콘 + 텍스트를 함께 쓴다.
5. **어르신 화면에 전문 용어를 쓰지 않는다.** AI 신뢰도·센서·API 같은 용어를 노출하지 않는다.
6. **처리 이력은 안전 처리만 담는다.** 중간 감지·판단 이벤트는 공간 화면의 타임라인에만 있다.
