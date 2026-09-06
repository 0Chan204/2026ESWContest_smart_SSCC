# HomeVIS 프론트엔드 개발 노트

주방 터치 태블릿 / 월패드용 스마트홈 안전 모니터링 웹 앱의 프론트엔드 구현 기록.

---

## 1. 프로젝트 개요

### 무엇을 만들었나

집 안 공간(주방·화장실)의 **사용자 재실 상태와 가전 상태를 모니터링**하고, 위험 상황을 감지하면 **자동으로 안전 조치를 수행**한 뒤 그 **처리 이력을 사용자가 확인**할 수 있게 하는 태블릿용 웹 앱.

핵심은 가전 원격 제어가 아니라 다음 4단계 파이프라인이다.

```
상태 모니터링 → 안전 판단 → 안전 처리 → 처리 이력
```

### 화면 구성

| 화면 | 경로 | 설명 |
| --- | --- | --- |
| 모드 선택 | (최초 1회) | 일반용 / 어르신용 선택. localStorage 저장 후 재노출 안 함 |
| 홈 | `/home` | 집 전체 상태 요약 + 연결된 가전 그리드 |
| 주방 | `/kitchen` | 재실 감지 · 환경 센서 · 가전 · 최근 이벤트 |
| 화장실 | `/bathroom` | 주방과 동일한 레이아웃 시스템 |
| 처리 이력 | `/history` | 안전 처리 감사 로그 + 필터 + 페이지네이션 |

모든 화면은 **일반 모드 / 어르신 모드** 두 가지 변형을 가진다.

### 기준 해상도

| 대상 | 해상도 |
| --- | --- |
| 태블릿 가로 | 1280 × 800 |
| 주방 월패드 | 1440 × 900 |

**두 해상도 모두, 어르신 모드 글자 크기를 최대(130%)로 올린 상태에서도 세로 스크롤이 발생하지 않는다.** 이게 이 프로젝트의 가장 강한 레이아웃 제약이었고, 설계 판단의 상당 부분이 여기서 나왔다.

---

## 2. 기술 스택

| 영역 | 선택 | 이유 |
| --- | --- | --- |
| 빌드 | Vite 6 | 정적 산출물, 빠른 HMR |
| 언어 | TypeScript (strict) | 센서·기기 상태 타입 안정성 |
| UI | React 18 | |
| 스타일 | Tailwind CSS v4 | 디자인 토큰을 CSS 변수로 다루기 좋음 |
| 라우팅 | react-router v7 | 새로고침·딥링크에도 탭 유지 |
| 아이콘 | lucide-react | |
| 토스트 | sonner | |
| 상태 | React Context + useReducer | 이 규모에 Redux/zustand 불필요 |
| 음성 | 브라우저 내장 Web Speech API | API 키·과금 없음 |

### 의존성을 5개로 줄인 이유

디자인 원본(Figma Make export)의 `package.json` 에는 MUI, Radix UI 30여 개, recharts, react-slick, react-dnd 등 **런타임 의존성 60개 이상**이 들어 있었다. 그런데 실제 화면 코드(`App.tsx`)가 import 하는 건 `lucide-react` 와 `sonner` 둘뿐이었다.

나머지는 전부 죽은 코드였고, 그대로 두면 **쓰지도 않는 패키지가 공급망 취약점 표면으로 남는다.** 그래서 신규 프로젝트를 만들 때 실제로 쓰는 것만 가져왔다.

```
런타임 의존성 5개: react, react-dom, react-router, lucide-react, sonner
npm audit → found 0 vulnerabilities
```

날짜 범위 선택도 Radix Popover + react-day-picker 대신 **네이티브 `<input type="date">`** 를 썼다. 의존성 0이고, 태블릿에서 OS 기본 날짜 피커가 떠서 터치 UX가 오히려 낫다.

---

## 3. 아키텍처

### 레이어

```
┌─────────────────────────────────────────────┐
│ features/  화면 (home, room, history, ...)   │  ← 데이터 출처를 모름
├─────────────────────────────────────────────┤
│ store/     Preferences / HomeState Context   │  ← 상태 소유
├─────────────────────────────────────────────┤
│ data/source/  SafetyDataSource (인터페이스)   │  ← 교체 지점
│               ├ mockSource   (현재)          │
│               └ httpSource   (백엔드 붙일 때)  │
└─────────────────────────────────────────────┘
```

### 디렉터리

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
├─ components/   재사용 프리미티브
├─ data/         목 데이터 + 데이터 소스 경계
├─ store/        전역 상태 2개
├─ hooks/        useClock, useDismissable
├─ i18n/         ko / en 사전
├─ lib/          포맷·저장소·한국어 조사·클래스 결합
└─ types/        도메인 타입
```

총 52개 파일 / 약 4,000줄.

---

## 4. 핵심 구현

### 4-1. 글자 크기만 키우고 레이아웃은 고정하기

**문제.** 어르신 모드에서 글자 크기를 100~130%로 조절해야 한다. 그런데 단순히 `html { font-size }` 를 키우면 Tailwind의 여백(`p-4`)·아이콘 크기(`w-6`)·모서리 반경이 전부 `rem` 기반이라 **화면 전체가 같이 확대되어 레이아웃이 깨진다.** 기획서에도 "아이콘·레이아웃이 무조건 같은 비율로 커져 화면이 깨지는 방식은 피한다"고 명시되어 있었다.

**해결.** Tailwind v4의 `--spacing` 토큰을 **px로 고정**했다. 이렇게 하면 여백/크기 계열 유틸리티는 루트 폰트 크기와 무관해지고, `--text-*` 기반인 글자 크기만 스케일된다.

```css
/* src/styles/index.css */
@theme {
  /* 여백·크기 단위를 px 로 고정 → 폰트 스케일과 분리 */
  --spacing: 4px;

  --radius-lg: 12px;
  --radius-2xl: 16px;

  --color-brand: #1b4fca;
  --color-canvas: #f5f7fb;
}

:root {
  --font-size-base: 16px;
  --nav-h: 64px;
}

html {
  font-size: var(--font-size-base);
}
```

기본값 `0.25rem` = 16px 기준 4px 이므로 **100%에서는 동작이 완전히 동일**하고, 확대할 때만 차이가 난다.

그 다음 모드/스케일에 따라 루트 변수만 갱신한다.

```tsx
// src/store/PreferencesContext.tsx
useEffect(() => {
  const root = document.documentElement
  root.style.setProperty(
    '--font-size-base',
    mode === 'elderly' ? `${(fontScale / 100) * 16}px` : '16px',
  )
  root.style.setProperty('--nav-h', mode === 'elderly' ? '88px' : '64px')
}, [mode, fontScale])
```

`max-w-*` 도 rem 기반이라 스케일되므로, 컨테이너 폭은 `max-w-[1400px]` 처럼 **명시적 px 임의값**을 썼다.

> **결과:** 130%로 올려도 카드 간격·아이콘·그리드는 그대로 유지되고 글자만 커진다. 1280×800에서 스크롤이 생기지 않는다.

---

### 4-2. 데이터 소스 경계 — 목에서 실제 API로 한 파일만 교체

**문제.** 백엔드가 아직 없다. 그렇다고 목 데이터를 화면 컴포넌트에 직접 박아두면 나중에 API 붙일 때 전 화면을 다 뜯어야 한다.

**해결.** 인터페이스로 경계를 그었다.

```ts
// src/data/source/types.ts
export interface SafetyDataSource {
  readonly kind: 'mock' | 'http'
  loadSnapshot(): Promise<HomeSnapshot>
  setPower(applianceId: string, power: PowerState): Promise<void>
  /** 실시간 갱신 구독. 해제 함수를 반환한다 */
  subscribe(listener: (patch: RealtimePatch) => void): () => void
  /** 데모용 위험 상황 트리거. 실제 소스에서는 서버 이벤트로 대체된다 */
  createIncident(room: RoomId): SafetyIncident | null
}

/** 실시간 갱신 패치. 소스가 데이터의 주인이고 UI 는 받아서 반영만 한다 */
export type RealtimePatch =
  | { kind: 'environment'; room: RoomId; environment: Environment }
  | { kind: 'presence'; room: RoomId; presence: Presence }
```

선택은 환경변수 하나로 갈린다.

```ts
// src/data/source/index.ts
export function createDataSource(): SafetyDataSource {
  const baseUrl = import.meta.env.VITE_API_BASE_URL
  if (typeof baseUrl === 'string' && baseUrl.length > 0) {
    return createHttpSource(baseUrl)
  }
  return createMockSource()
}
```

**목 소스는 정지 화면이 아니라 실시간 시뮬레이터다.** 6초마다 온도·습도·조도에 미세한 흔들림을 주고 재실 상태를 갱신해서, 화면이 "살아있는" 대시보드처럼 보이게 했다.

```ts
// src/data/source/mockSource.ts
/** 값이 살짝씩 움직여야 '살아있는' 화면으로 보인다. 과하면 산만하므로 미세하게만 */
function jitter(value: number, delta: number, min: number, max: number): number {
  const next = value + (Math.random() * 2 - 1) * delta
  return Math.min(max, Math.max(min, next))
}

// 습도는 60% 이상이면 자동으로 warning 상태가 된다
if (m.key === 'humidity') {
  const next = Math.round(jitter(Number(m.value), 1.5, 40, 78))
  return { ...m, value: String(next), status: next >= 60 ? 'warning' : 'normal' }
}
```

> **결과:** 실제 API가 준비되면 `httpSource.ts` 한 파일만 구현하면 되고, 화면 코드는 한 줄도 바뀌지 않는다.

---

### 4-3. 위험 감지 → 안전 조치 → 이력 자동 기록 파이프라인

이 프로젝트의 **핵심 도메인 로직**이다. 원본 프로토타입에서는 위험 알림과 처리 이력이 서로 연결되어 있지 않아서, 안전 조치를 수행해도 이력에 남지 않았다. 이걸 하나의 파이프라인으로 이었다.

```
[위험 상황 시뮬레이션] 클릭
        ↓  startIncident
WarningModal ─ 인덕션 상태를 warning 으로 전환 (홈/주방 카드가 즉시 주황으로)
             ─ 5초 카운트다운 + 프로그레스 바
             ─ "왜 이 알림이 표시되었나요?" 접이식 판단 근거
        ↓
   ┌────┴────────────────────────┐
   │                             │
[카운트다운 만료]            [직접 처리하겠습니다]
 resolveIncident              cancelIncident
   │                             │
   ├ 인덕션 화력 3단계 → 1단계     ├ 기기 상태 원복
   ├ 기기 상태 normal 원복        └ '사용자 직접 처리' 감사 로그 기록
   ├ 기기 이력 타임라인에 추가
   ├ ★ 처리 이력에 자동 append
   └ ResultModal 표시
```

리듀서 구현:

```ts
// src/store/HomeStateContext.tsx
case 'resolveIncident': {
  const incident = state.activeIncident
  if (!incident) return state
  return {
    ...state,
    activeIncident: null,
    lastResult: action.log,
    // 안전 조치를 실제 기기 상태에 반영한다.
    appliances: state.appliances.map((a) =>
      a.id !== incident.action.applianceId
        ? a
        : {
            ...a,
            status: 'normal',
            detail: incident.action.nextDetail,   // '화력 3단계' → '화력 1단계'
            lastUpdate: '방금 전',
            history: [
              { time: action.time, kind: 'warning' as const,
                text: incident.action.deviceHistoryText },
              ...a.history,
            ].slice(0, 5),
          },
    ),
    // 처리 이력에 자동 기록한다.
    safetyLogs: [action.log, ...state.safetyLogs],
  }
}
```

**설계 포인트 3가지**

1. **위험 상황이 기기 상태에 반영된다.** `startIncident` 시점에 해당 기기를 `warning` 으로 바꾸기 때문에, 모달 뒤의 가전 카드와 홈의 "현재 안전 알림" 카드가 동시에 주황으로 바뀐다. 알림이 모달 안에만 갇혀 있지 않다.

2. **취소도 로그를 남긴다.** 사용자가 "직접 처리하겠습니다"를 눌러도 감사 로그를 기록한다. 처리 이력은 감사 로그이므로 "시스템이 조치하려 했으나 사용자가 직접 처리함"도 기록될 가치가 있다고 판단했다.

3. **알림 건수는 파생값이다.** `activeIncident` 와 기기 상태를 각각 세면 중복 집계된다. 기기 상태 하나에서만 파생시켰다.

```ts
const alertCount = useMemo(
  () => state.appliances.filter((a) => a.status === 'warning' || a.status === 'danger').length,
  [state.appliances],
)
```

**카운트다운 초기값 버그와 해결.** 처음엔 `useState(0)` 으로 두고 `useEffect` 에서 incident 값을 넣었더니, 첫 프레임에서 진행률이 100%로 그려졌다가 0%로 역주행하는 현상이 있었다. 위험 상황마다 컴포넌트를 새로 마운트해서 초기값을 정확히 잡는 방식으로 해결했다.

```tsx
export function WarningModal() {
  const { activeIncident } = useHomeState()
  if (!activeIncident) return null
  // key 를 주어 위험 상황마다 새로 마운트 → 카운트다운이 항상 정확한 값에서 시작
  return <WarningDialog key={activeIncident.id} incident={activeIncident} />
}

function WarningDialog({ incident }: { incident: SafetyIncident }) {
  const [remaining, setRemaining] = useState(incident.countdownSec)   // ← 정확한 초기값
  ...
}
```

---

### 4-4. supportsControl — 지원하지 않는 기능은 UI에 만들지 않는다

기획서의 강한 원칙이었다. "지원하지 않는 가전 제어 기능을 억지로 UI에 추가하지 않는다."

기기 모델에 플래그를 두고, **버튼 경로와 음성 경로 양쪽에서 동일하게 차단**한다.

```ts
// src/types/index.ts
export interface Appliance {
  ...
  /**
   * 실제로 제어 API 가 존재하는 기기만 true.
   * false 인 기기는 버튼도 음성도 제어 UI 를 렌더링하지 않는다.
   */
  supportsControl: boolean
}
```

| 기기 | supportsControl | 이유 |
| --- | --- | --- |
| 인덕션 | `false` | 안전상 사용자 임의 원격 제어를 제공하지 않음. 시스템의 자동 안전 조치만 수행 |
| 정수기 | `false` | 제어 API 없음 |
| 환풍기 | `true` | on/off 지원 |
| 조명 | `true` | on/off 지원 |

**게이트는 UI가 아니라 상태 레이어에 둔다.** 버튼을 숨기는 것만으로는 음성 경로를 못 막기 때문에, 상태를 바꾸는 함수 자체에서 검사한다.

```ts
// src/store/HomeStateContext.tsx
const setPower = useCallback((applianceId: string, power: PowerState) => {
  const appliance = sourceRefCurrentAppliance(state.appliances, applianceId)
  // 제어를 지원하지 않는 기기는 어떤 경로(버튼/음성)로도 상태를 바꿀 수 없다.
  if (!appliance || !appliance.supportsControl) return
  ...
}, [state.appliances])
```

UI는 이 플래그에 따라 제어 영역 자체를 다르게 그린다.

```tsx
{appliance.supportsControl ? (
  <div className="mb-4 rounded-xl bg-gray-50 p-3">
    <p className="mb-2 text-xs font-semibold text-gray-500">{t('appliance.control')}</p>
    {/* 켜기 / 끄기 버튼 */}
  </div>
) : (
  <p className="mb-4 rounded-xl bg-gray-50 px-3 py-2.5 text-xs text-gray-500">
    {t('appliance.noControl')}   {/* "이 기기는 상태 확인만 지원합니다." */}
  </p>
)}
```

---

### 4-5. 음성 — 상태 머신 + 확인 단계

**원칙 2가지를 코드로 강제했다.**

1. **음성으로 되는 것은 버튼으로도 된다.** Voice-only 기능을 만들지 않는다.
2. **상태를 바꾸는 명령은 즉시 실행하지 않고 확인을 받는다.** 조회·이동만 즉시 실행한다.

명령 매칭 규칙은 선언적으로 분리했다.

```ts
// src/features/voice/commands.ts
export type VoiceIntent =
  | { kind: 'navigate'; route: string; replyKey: TKey }
  | { kind: 'control'; applianceId: string; power: PowerState;
      confirmKey: TKey; replyKey: TKey }

const RULES: Rule[] = [
  // 제어 명령을 먼저 검사한다.
  // "주방 조명 꺼줘" 가 공간 이동 명령으로 잘못 매칭되는 것을 막기 위해서다.
  { test: (t) => hasAny(t, '조명', '불') && hasAny(t, '꺼', '끄'),
    intent: { kind: 'control', applianceId: 'light', power: 'OFF',
              confirmKey: 'voice.confirmLight.off', replyKey: 'voice.reply.done' } },
  { test: (t) => has(t, '환풍기') && hasAny(t, '켜'),
    intent: { kind: 'control', applianceId: 'fan', power: 'ON', ... } },
  // 그 다음 이동/조회
  { test: (t) => hasAny(t, '이력', '기록'),
    intent: { kind: 'navigate', route: '/history', replyKey: 'voice.reply.history' } },
  { test: (t) => has(t, '주방'),
    intent: { kind: 'navigate', route: '/kitchen', replyKey: 'voice.reply.kitchen' } },
  ...
]

export function matchCommand(rawText: string): VoiceIntent | null {
  const text = rawText.replace(/\s+/g, '')   // 공백 제거 후 매칭
  for (const rule of RULES) if (rule.test(text)) return rule.intent
  return null
}
```

의도 실행부에서 조회와 제어를 갈라놓는다.

```ts
// src/features/voice/useVoice.ts
const runIntent = useCallback((intent: VoiceIntent) => {
  if (intent.kind === 'navigate') {
    navigate(intent.route)          // 조회·이동은 즉시 실행
    setReply(t(intent.replyKey))
    setState('completed')
    later(close, REPLY_HIDE_MS)
    return
  }

  const appliance = applianceById(intent.applianceId)
  // 제어를 지원하지 않는 기기는 음성으로도 조작할 수 없다.
  if (!appliance || !appliance.supportsControl) {
    setState('error')
    later(close, REPLY_HIDE_MS)
    return
  }

  // 상태를 바꾸는 명령은 즉시 실행하지 않고 확인을 받는다.
  setState('recognized')
  setPending({
    message: t(intent.confirmKey, { room: t(ROOM_KEY[appliance.room]) }),  // "주방 조명을 끌까요?"
    run: () => {
      setPower(intent.applianceId, intent.power)
      ...
    },
  })
}, [...])
```

**상태 머신**

```
idle → listening → recognized → processing → completed
                        │                        ↑
                        └─ (제어) 확인 대기 ──[실행]┘
                                    └────────[취소]→ close
                   └─ error (매칭 실패 / 인식 실패)
```

**Web Speech API 폴백.** 브라우저 미지원이거나 사용자가 설정에서 음성을 꺼둔 경우, 동일한 상태 전이를 데모로 재생한다. 데모 문장은 무작위가 아니라 **순서대로 돌린다** — 무작위면 확인 단계 같은 흐름을 시연하기 어렵기 때문이다.

```ts
const DEMO_COMMANDS = [
  '주방 보여줘', '조명 꺼줘', '화장실 상태 알려줘', '이력 보여줘', '우리 집 상태 알려줘',
] as const

let demoCursor = 0
export function nextDemoCommand(): string {
  const command = DEMO_COMMANDS[demoCursor % DEMO_COMMANDS.length] ?? DEMO_COMMANDS[0]
  demoCursor += 1
  return command
}
```

**타입.** `SpeechRecognition` 은 `lib.dom` 에 표준 타입이 없다. `any` 를 쓰지 않기 위해 필요한 부분만 직접 선언했다.

```ts
// src/features/voice/speech.ts
export interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  start(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorLike) => void) | null
}

export function createRecognition(): SpeechRecognitionLike | null {
  // 보안 컨텍스트(HTTPS/localhost)가 아니면 마이크를 못 쓰므로 만들지 않는다
  if (!window.isSecureContext) return null
  const w = window as unknown as SpeechWindow
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) return null
  ...
}
```

---

### 4-6. ApplianceCard — 6가지 상태 변형

기획서 요구는 5종(active/off/warning/danger/offline)이었는데, 구현하면서 **standby 를 추가**했다.

정수기의 "대기"를 `power !== 'ON'` 이라는 이유로 `off` 로 처리하니 카드 전체가 무채색이 되면서 "OFF" 뱃지가 붙었다. 그런데 화면의 전원 텍스트는 "대기"라 **뱃지와 본문이 서로 다른 말**을 하고 있었다. 대기는 고장도 꺼짐도 아니므로 별도 변형으로 분리했다.

```ts
// src/lib/appliance.ts
export function getVariant(appliance: Appliance): ApplianceVariant {
  if (appliance.status === 'offline') return 'offline'
  if (appliance.status === 'danger') return 'danger'
  if (appliance.status === 'warning') return 'warning'
  if (appliance.power === 'ON') return 'active'
  // '대기'는 고장도 꺼짐도 아니다. 색을 완전히 빼지 않고 낮은 강조로만 표현한다.
  if (appliance.power === 'STANDBY') return 'standby'
  return 'off'
}
```

| 변형 | 카드 | 표시 |
| --- | --- | --- |
| `active` | 흰 배경 · 컬러 아이콘 | 초록 점 + "정상" |
| `standby` | 흰 배경 · 컬러 아이콘 · 낮은 강조 | 초록 점 + "정상" |
| `off` | **회색 배경 + `grayscale`** | 회색 점 + "OFF" |
| `warning` | 연주황 배경 + 주황 테두리 | ⚠ 아이콘 + "주의" |
| `danger` | 연빨강 배경 + 빨강 테두리 | ⚠ 아이콘 + "위험" |
| `offline` | 회색 + `grayscale` | WifiOff 아이콘 + "연결 끊김" |

**OFF를 `grayscale` 필터로 처리한 이유.** 기획서에서 "OFF Card 전체가 명확한 Grayscale UI가 되도록" 요구했다. 개별 색상 클래스를 일일이 회색으로 바꾸는 대신 CSS 필터를 카드에 걸면, 안에 어떤 아이콘이 들어와도 색이 확실히 빠진다. 단 `opacity` 는 쓰지 않았다 — "비활성화처럼 지나치게 투명하게 만들어 읽기 어렵게 하지 않는다"는 요구 때문.

**상태를 색상만으로 표현하지 않는다.** 색각 이상 사용자와 어르신 가독성을 위해 모든 상태 표시는 **아이콘 + 텍스트**를 함께 쓴다.

```tsx
{variant === 'offline' && (
  <span className="flex items-center gap-1 text-xs font-semibold text-gray-500">
    <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />
    {t('appliance.disconnected')}
  </span>
)}
```

---

### 4-7. 처리 이력 — 목록은 단순하게, 상세는 상세하게

**데이터 정의를 바꿨다.** 이력 화면은 더 이상 센서가 감지한 모든 원시 이벤트를 보여주지 않는다. `상태 감지` · `상태 판단` 같은 중간 이벤트는 **애초에 이력 데이터에 넣지 않았고**, 공간 화면(주방/화장실)의 타임라인에만 남겼다.

```ts
/**
 * 처리 이력. 기획서에 따라 '상태 감지' / '상태 판단' 같은 중간 이벤트는
 * 여기에 담지 않는다. 실제로 시스템이 수행한 안전 처리만 기록한다.
 */
export interface SafetyLog {
  id: string
  datetime: string          // ISO8601
  room: RoomId
  content: string
  result: SafetyResult      // 'success' | 'warning' | 'canceled'
  reasoning: string[]       // 판단 근거
  relatedDevices: string[]
  confidence: number
}
```

테이블 컬럼은 `시간 | 구분 | 장소 | 내용` 4개. **`결과` 컬럼은 제거**하고 상세 모달에서만 확인하게 했다.

**목 데이터를 상대 날짜로 생성했다.** 원본은 `2026-08-13` 같은 고정 날짜였는데, 그러면 시간이 지나면 날짜 범위 필터가 항상 빈 결과를 낸다. 앱을 여는 시점 기준 최근 6일로 생성하도록 바꿨다.

```ts
// src/data/safetyHistory.ts
function isoAt(dayAgo: number, [h, m, s]: [number, number, number]): string {
  const d = new Date()
  d.setDate(d.getDate() - dayAgo)
  ...
}

export function createSafetyHistory(): SafetyLog[] {
  return SEEDS.map((seed, i) => ({ ... }))
    .sort((a, b) => b.datetime.localeCompare(a.datetime))
}
```

**필터링.** 공간 · 날짜 범위 · 검색어를 하나의 `useMemo` 에서 순차 적용한다.

```tsx
const filtered = useMemo(() => {
  const keyword = search.trim()
  return safetyLogs.filter((log) => {
    if (room !== 'all' && log.room !== room) return false
    if (from && log.datetime < from) return false
    if (to && log.datetime > `${to}T23:59:59`) return false   // 종료일 포함
    if (keyword && !log.content.includes(keyword)) return false
    return true
  })
}, [safetyLogs, room, from, to, search])
```

ISO8601 문자열은 사전순 비교 = 시간순 비교라 `Date` 객체 변환 없이 문자열 비교로 처리했다.

**필터가 바뀌면 항상 1페이지로.** 3페이지를 보다가 필터를 좁히면 빈 페이지가 뜨는 문제를 막는다.

```tsx
function update(apply: () => void) {
  apply()
  setPage(1)
}
// 사용: onChange={(e) => update(() => setRoom(e.target.value as RoomFilter))}
```

**스크롤 대신 페이지네이션.** 일반 모드 5건, 어르신 모드는 글자가 크므로 4건.

```tsx
const perPage = elderly ? 4 : 5
const totalPages = Math.max(1, Math.ceil(filtered.length / perPage))
const safePage = Math.min(page, totalPages)   // 필터 변화로 페이지 범위를 벗어나도 안전
```

---

### 4-8. 설정 영속화 — 저장된 값을 신뢰하지 않는다

localStorage 값은 사용자가 devtools로 얼마든지 바꿀 수 있다. 그대로 읽어서 상태에 넣으면 앱이 깨진다.

**읽을 때 반드시 검증**하는 레이어를 뒀다.

```ts
// src/lib/storage.ts
/** 허용된 문자열 집합 안의 값만 통과시킨다. */
export function readEnum<T extends string>(
  key: string, allowed: readonly T[], fallback: T,
): T {
  const raw = safeGet(key)
  return allowed.includes(raw as T) ? (raw as T) : fallback
}

/** 지정 범위 안의 정수만 통과시킨다. */
export function readInt(key: string, min: number, max: number, fallback: number): number {
  const raw = safeGet(key)
  if (raw === null) return fallback
  const n = Number.parseInt(raw, 10)
  if (!Number.isFinite(n) || n < min || n > max) return fallback
  return n
}
```

접근 자체도 `try/catch` 로 감쌌다. 시크릿 모드처럼 localStorage 접근이 막힌 환경에서 **예외로 앱이 죽지 않게** 한다.

```ts
function safeGet(key: string): string | null {
  try { return window.localStorage.getItem(PREFIX + key) }
  catch { return null }
}
```

사용부:

```tsx
const [fontScale, setFontScaleState] = useState(() =>
  readInt('fontscale', FONT_SCALE_MIN, FONT_SCALE_MAX, FONT_SCALE_DEFAULT),
)
const [language, setLanguageState] = useState<Language>(() =>
  readEnum<Language>('language', LANGS, 'ko'),
)
// 음성 인식은 개인정보 관점에서 기본 꺼짐. 사용자가 명시적으로 켜야 한다.
const [voiceEnabled, setVoiceEnabledState] = useState(() => readBool('voice', false))
```

**모드는 "없음"과 "잘못된 값"을 구분해야 한다.** 저장된 모드가 없으면 최초 모드 선택 화면을 띄워야 하는데, 값이 손상된 경우에도 선택 화면으로 보내야 안전하다. 센티널을 써서 한 번의 호출로 처리했다.

```tsx
const [mode, setModeState] = useState<Mode | null>(() => {
  const stored = readEnum<Mode | 'none'>('mode', [...MODES, 'none'] as const, 'none')
  return stored === 'none' ? null : stored
})
```

**저장되는 값은 UI 설정 4개뿐이다.**

```
homevis_mode, homevis_fontscale, homevis_language, homevis_voice
homevis_onboarding_complete
```

인증정보·개인정보·센서 원본은 저장하지 않는다.

---

### 4-9. i18n — 라이브러리 없이

i18next 같은 라이브러리 없이 **평면 점(.) 키 사전**으로 구현했다. 병합이 단순하고 타입이 안전하다.

```ts
// src/i18n/ko.ts
export const ko = {
  'nav.home': '홈',
  'presence.meta': '현재 행동: {action} · 마지막 감지: {sec}초 전',
  'home.summary.count': '{n}개 중 {m}개',
  ...
} as const

export type TKey = keyof typeof ko
```

영어는 **부분 사전**이고, 없는 키는 자동으로 한국어로 폴백한다.

```ts
export function createTranslate(lang: Language): Translate {
  const dict = DICTS[lang]
  return (key, vars) => {
    const template = dict[key] ?? ko[key] ?? key
    if (!vars) return template
    return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
      Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole,
    )
  }
}
```

`TKey` 가 `ko` 사전에서 파생되므로, **존재하지 않는 키를 쓰면 컴파일 에러**가 난다.

**한국어 조사 처리.** 토스트에 "환풍기을(를) 켰습니다" 같은 표기가 나와서 받침 유무로 조사를 고르는 헬퍼를 만들었다.

```ts
// src/lib/korean.ts
/** 마지막 글자의 받침 유무에 따라 조사를 고른다. (예: 조명을 / 환풍기를) */
export function withObjectParticle(word: string): string {
  const last = word.trim().slice(-1)
  const code = last.charCodeAt(0)
  if (Number.isNaN(code) || code < 0xac00 || code > 0xd7a3) return `${word}를`
  const hasFinal = (code - 0xac00) % 28 !== 0
  return `${word}${hasFinal ? '을' : '를'}`
}
```

한글 유니코드는 `0xAC00` 부터 초성×중성×종성 순서로 배열되어 있고, 종성이 28종(없음 포함)이라 `(code - 0xAC00) % 28 !== 0` 이면 받침이 있다.

---

## 5. 세로 스크롤 0 만들기

기획서에서 가장 강하게 요구한 항목이었다. 전략은 **"스크롤을 숨기는 것"이 아니라 "넘치지 않게 만드는 것"**이다.

### 5-1. 전체 높이를 flex로 분배

```css
#root { height: 100dvh; overflow: hidden; }
```

```tsx
// src/app/AppShell.tsx
<div className="flex h-dvh flex-col overflow-hidden">
  <NavBar />                                    {/* shrink-0, 고정 높이 */}
  <ConnectionBanner />                          {/* shrink-0 */}
  <main className="min-h-0 flex-1 overflow-hidden pb-20">
    <Outlet />                                  {/* 남는 높이 전부 */}
  </main>
</div>
```

`min-h-0` 이 핵심이다. flex 아이템의 기본 `min-height: auto` 는 내용보다 작아지지 않으려 하기 때문에, 이걸 풀어줘야 자식이 실제로 축소된다.

### 5-2. 좌하단 음성 버튼 safe area

플로팅 음성 버튼이 테이블 행이나 버튼을 가리는 문제가 있었다. `main` 에 `pb-20`(80px)을 줘서 안전 영역을 확보했다.

```tsx
{/* 좌하단 플로팅 음성 버튼이 콘텐츠(테이블 행·버튼)를 가리지 않도록 하단 여백을 확보한다 */}
<main className="min-h-0 flex-1 overflow-hidden pb-20">
```

### 5-3. 넘치면 스크롤 대신 재배치

실제로 부딪힌 문제와 해결:

| 문제 | 해결 |
| --- | --- |
| 주방 가전 3개가 2열 그리드에서 2행으로 넘침 | 개수에 따라 열 수를 바꿈 |
| 어르신 130%에서 주방 화면이 잘림 | 부제목 제거 · 카드 패딩/아이콘 축소 · 3열 배치 |
| 최근 이벤트가 길어지면 화면이 늘어남 | 타임라인 표시 건수를 `max` prop 으로 제한 |
| 이력이 많음 | 스크롤 대신 페이지네이션 |

```tsx
{/* 기기 수에 맞춰 한 줄에 담아 세로 스크롤이 생기지 않게 한다 */}
<div className={cn('grid gap-3', roomAppliances.length >= 3 ? 'grid-cols-3' : 'grid-cols-2')}>
```

```tsx
export function EventTimeline({ events, max = 4 }: {...}) {
  const visible = events.slice(0, max)   // 화면이 늘어나지 않도록 반드시 제한
  ...
}
```

### 5-4. 남는 공간을 채우기

반대로 1440×900에서는 아래쪽이 비어 보였다. 가전 섹션을 `flex-1` 로 늘리고 그리드 행을 균등 분배해서, 좌측 카드 하단이 우측 이벤트 카드와 정렬되게 했다.

```tsx
<section className="flex min-h-0 flex-1 flex-col">
  <h2 className="mb-2 shrink-0 ...">{t('section.appliances')}</h2>
  <div className="grid min-h-0 flex-1 gap-3 grid-cols-3"
       style={{ gridAutoRows: 'minmax(0, 1fr)' }}>
```

### 검증 결과

```js
// 1280×800 / 1440×900, 일반·어르신, 글자 100~130%, 전 화면
document.documentElement.scrollHeight - document.documentElement.clientHeight  // → 0
document.documentElement.scrollWidth  - document.documentElement.clientWidth   // → 0
```

---

## 6. 보안 설계

### 6-1. CSP 자동 주입

프로덕션 빌드 산출물에만 엄격한 CSP를 넣는다. dev 서버는 HMR용 인라인 스크립트를 쓰기 때문에 제외했다.

```ts
// vite.config.ts
const CSP = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "form-action 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  ...
].join('; ')

function cspPlugin() {
  return {
    name: 'homevis-csp',
    apply: 'build' as const,
    transformIndexHtml(html: string) {
      return html.replace('<head>',
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`)
    },
  }
}
```

> `frame-ancestors` 는 meta 태그로 적용되지 않으므로 **HTTP 헤더로 설정해야 한다.** nginx 설정 예시는 README에 있다.

### 6-2. XSS 벡터를 ESLint로 차단

리뷰에 의존하지 않고 **소스 레벨에서 막았다.**

```js
// eslint.config.js
'no-restricted-syntax': [
  'error',
  {
    selector: 'JSXAttribute[name.name="dangerouslySetInnerHTML"]',
    message: 'dangerouslySetInnerHTML 은 XSS 위험으로 금지한다.',
  },
  {
    selector: "AssignmentExpression > MemberExpression[property.name='innerHTML']",
    message: 'innerHTML 직접 대입은 XSS 위험으로 금지한다.',
  },
  {
    selector: "CallExpression[callee.object.name='localStorage'][callee.property.name='setItem'] > Literal:first-child[value=/token|password|secret|key|jwt|auth/i]",
    message: '인증정보를 localStorage 에 저장하지 않는다.',
  },
],
'no-eval': 'error',
'no-implied-eval': 'error',
'no-new-func': 'error',
'@typescript-eslint/no-explicit-any': 'error',
```

마지막 규칙은 **인증정보를 localStorage에 저장하는 코드를 이름 패턴으로 차단**한다. 나중에 백엔드를 붙이면서 무심코 토큰을 넣는 걸 막기 위한 장치다.

### 6-3. 외부 요청 0건

폰트 CDN을 쓰지 않고 시스템 한글 폰트 스택을 썼다.

```css
--font-sans:
  'Pretendard', 'Pretendard Variable', -apple-system, BlinkMacSystemFont,
  'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', 'Segoe UI', Roboto,
  'Helvetica Neue', Arial, sans-serif;
```

Google Fonts를 쓰면 매 로딩마다 외부 요청이 발생하고, 사용자 IP가 외부로 나가며, 오프라인에서 깨진다. 자체 호스팅이 필요하면 `public/fonts/` 에 woff2를 넣고 `@font-face` 주석을 해제하면 되도록 준비해뒀다.

### 6-4. 음성 인식 개인정보 처리

브라우저의 Web Speech API는 인식 처리를 위해 **음성이 브라우저 제공사 서버로 전송될 수 있다.** 이건 무료지만 개인정보 이슈다. 3단계로 처리했다.

1. **기본 꺼짐** — `readBool('voice', false)`
2. **설정 화면에 고지** — "브라우저 음성 인식은 인식 처리를 위해 음성이 브라우저 제공사 서버로 전송될 수 있습니다. 필요할 때만 켜서 사용하세요."
3. **꺼져 있으면 마이크를 아예 요청하지 않음** — 데모 시뮬레이션으로 폴백

```ts
// 설정에서 꺼져 있으면 마이크를 아예 요청하지 않는다.
const recognition = voiceEnabled ? createRecognition() : null
if (!recognition) { startDemo(); return }
```

교체가 필요하면 `src/features/voice/speech.ts` 한 파일만 온디바이스 STT로 바꾸면 된다.

### 6-5. 취약점 0건

초기 설치 시 `npm audit` 에서 high 6건이 나왔다.

| 패키지 | 문제 | 조치 |
| --- | --- | --- |
| react-router-dom | Open redirect, XSS, deserializeErrors 생성자 주입 | **v7으로 마이그레이션** (`react-router` 패키지로 변경) |
| vite | 경로 순회, dev 서버 임의 파일 읽기 등 | 6.4.3 |
| @eslint/plugin-kit | ReDoS | eslint 9.39.5 |

react-router는 major 업그레이드가 필요했지만, 사용하는 API(`BrowserRouter`, `Routes`, `Route`, `NavLink`, `Outlet`, `useNavigate`)가 v7에서 그대로라 import 경로만 바꾸면 됐다.

```
npm audit → found 0 vulnerabilities
```

---

## 7. 접근성

터치 월패드가 주 환경이지만 어르신 사용자가 주 대상이라 신경 썼다.

| 항목 | 구현 |
| --- | --- |
| 터치 타겟 | 최소 44px(`min-h-11`), 어르신 모드 56~64px |
| 상태 표현 | 색상 + 아이콘 + 텍스트 항상 병기 |
| 모달 | `role="dialog"`, 위험 알림은 `role="alertdialog"`, ESC 닫기, 포커스 트랩 |
| 포커스 | `:focus-visible` 로 키보드 사용자에게만 링 표시 |
| 음성 패널 | `aria-live="polite"` 로 상태 변화 낭독 |
| 모션 | `prefers-reduced-motion` 대응 |
| 터치 지연 | `touch-action: manipulation` 으로 300ms 더블탭 대기 제거 |
| hover 고착 | `@media (hover: none)` 에서 hover 효과 무력화 |

**포커스 트랩** 구현:

```ts
// src/hooks/useDismissable.ts
export function useDismissable(open: boolean, onClose: () => void) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<Element | null>(null)

  useEffect(() => {
    if (!open) return
    previousFocusRef.current = document.activeElement
    containerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)[0]?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') { onClose(); return }
      if (event.key !== 'Tab') return
      // Tab 순환을 컨테이너 안에 가둔다
      ...
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      const previous = previousFocusRef.current
      if (previous instanceof HTMLElement) previous.focus()   // 이전 포커스 복귀
    }
  }, [open, onClose])

  return containerRef
}
```

**어르신 모드에서는 전문 용어를 노출하지 않는다.**

```tsx
{/* 어르신 모드에서는 전문 용어인 'AI 신뢰도'를 표시하지 않는다 */}
{!elderly && <Row label={t('history.detail.confidence')} value={`${log.confidence}%`} mono />}
```

---

## 8. 검증

실제 브라우저에서 1280×800 / 1440×900 두 해상도, 일반·어르신 두 모드로 전 화면·전 플로우를 확인했다.

**동작 확인한 시나리오**

```
모드 선택 → 홈 → 가전 카드 클릭 → 상세 팝업 → 켜기/끄기 → 토스트 + 카드 상태 전환
주방 → 위험 상황 시뮬레이션 → 카운트다운 → 인덕션 화력 3단계→1단계 반영
     → 결과 모달 → 처리 이력에 자동 기록 확인 (14건 → 15건)
이력 → 날짜 범위 필터 (14건 → 3건) → 검색 (3건 → 1건) → 행 클릭 → 상세 모달
음성 버튼 → 듣는 중 → "조명 꺼줘" 인식 → "주방 조명을 끌까요?" 확인
     → 실행 → 조명 OFF + 카드 Grayscale + 토스트
설정 → 어르신 모드 전환 → 글자 크기 115%→130% → 새로고침 → 설정 유지 확인
```

**프로덕션 빌드 검증**

```
npm run build && npm run preview
→ 엄격한 CSP 적용 상태에서 콘솔 에러 0건
→ 딥링크(/history) 직접 접근 정상
→ 번들 309KB (gzip 93KB)
```

---

## 9. 남은 과제

| 항목 | 내용 |
| --- | --- |
| 백엔드 연동 | `src/data/source/httpSource.ts` 구현. 토큰은 httpOnly 쿠키 전제 |
| 실시간 통신 | same-origin WebSocket(wss). CSP `connect-src` 에 오리진 추가 필요 |
| danger / offline 변형 | 코드에는 있으나 목 데이터에 해당 기기가 없어 화면 시연 불가 |
| 배포 서버 설정 | `frame-ancestors` 헤더 + SPA fallback (`try_files`) |
| 영어 번역 | 현재 부분 사전(한국어 폴백). 우선순위 낮음 |
| 공간 확장 | `RoomId` 유니온과 `NavBar` 의 `TABS` 배열에 추가만 하면 침실/거실 확장 가능 |
| Service Worker | 캐시 꼬임 방지를 위해 1차에서는 제외. 완전 오프라인이 필요하면 추가 |

---

## 부록: 설계 원칙 요약

1. **음성으로 되는 것은 버튼으로도 된다.** Voice-only 기능을 만들지 않는다.
2. **상태를 바꾸는 명령은 확인을 거친다.** 조회·이동만 즉시 실행한다.
3. **지원하지 않는 기능은 UI에 만들지 않는다.** 게이트는 UI가 아니라 상태 레이어에 둔다.
4. **상태를 색상만으로 표현하지 않는다.** 항상 아이콘 + 텍스트를 함께 쓴다.
5. **어르신 화면에 전문 용어를 쓰지 않는다.**
6. **처리 이력은 안전 처리만 담는다.** 중간 감지·판단은 공간 화면 타임라인에만.
7. **저장된 값을 신뢰하지 않는다.** 읽을 때 항상 검증한다.
8. **스크롤을 숨기지 말고 넘치지 않게 만든다.**
