import type { DeviceControl } from '@/data/source'
import type { HouseRoom } from '@/types'

export type NavTarget = 'home' | 'kitchen' | 'bathroom' | 'history' | 'settings'

export type VoiceIntent =
  | { kind: 'navigate'; route: string; reply: NavTarget }
  /**
   * 기기 제어 (확인 후 실행). 기기 id 는 데이터 소스마다 달라(시연 light-bath-01 / 백엔드 light-00) 종류 · 공간으로 찾는다.
   * room 이 null 이면 지금 있는 공간 → 없으면 그 종류의 첫 기기
   */
  | { kind: 'control'; device: 'light' | 'fan' | 'air'; room: HouseRoom | null; control: DeviceControl }
  /** 상태 답변 (화면 안 정보로) */
  | { kind: 'answer'; topic: 'weather' | 'air' }
  /** 지원하지 않는 조작 (인덕션 등) — 이유를 안내한다 */
  | { kind: 'refuse'; reply: string }

interface Rule { test: (t: string) => boolean; intent: (t: string) => VoiceIntent }

const any = (t: string, ...w: string[]) => w.some((x) => t.includes(x))
const ON = (t: string) => any(t, '켜')
const OFF = (t: string) => any(t, '꺼', '끄', '끌')
const INDUCTION = (t: string) => any(t, '인덕션', '화구', '가스레인지', '레인지')
/** '불'은 인덕션 · 화구 말이 없을 때만 조명 */
const LIGHT = (t: string) => (any(t, '조명', '전등', '등불') || t.includes('불')) && !INDUCTION(t)
const FAN = (t: string) => any(t, '환풍기', '후드', '환기')
const AIR = (t: string) => any(t, '공기청정기', '청정기', '공기')
const WATER = (t: string) => any(t, '정수기', '물')
const WEATHER = (t: string) => any(t, '날씨', '기온', '우산', '비와', '비올', '비가', '덥', '춥')
/** 공백을 지운 문장에서 '주방'의 '방'을 침실로 오해하지 않도록 */
const BEDROOM = (t: string) => any(t, '침실', '안방') || t.replace(/주방/g, '').includes('방')
const BATH = (t: string) => any(t, '욕실', '화장실')
const KITCHEN = (t: string) => any(t, '주방', '부엌')
const roomOf = (t: string): HouseRoom | null => (BATH(t) ? 'bathroom' : BEDROOM(t) ? 'bedroom' : KITCHEN(t) ? 'kitchen' : null)

const SPEED_HIGH = (t: string) => any(t, '세게', '강하게', '강으로', '강풍', '최대', '세게')
const SPEED_MID = (t: string) => any(t, '중간', '보통', '중으로', '적당')
const SPEED_LOW = (t: string) => any(t, '약하게', '약으로', '살살', '약풍', '조금만')
const DIM = (t: string) => any(t, '어둡게', '절전', '낮춰', '줄여', '은은')
const BRIGHT = (t: string) => any(t, '밝게', '환하게', '최대로', '올려')
/** 기기를 바꾸는 말이 있는지 (화면 이동 명령과 구분) */
const CONTROL_WORD = (t: string) => ON(t) || OFF(t) || SPEED_HIGH(t) || SPEED_MID(t) || SPEED_LOW(t) || DIM(t) || BRIGHT(t)
const DEVICE_WORD = (t: string) => INDUCTION(t) || LIGHT(t) || FAN(t) || AIR(t) || WATER(t)

/**
 * 시연 모드(백엔드 없음)에서 쓰는 화면 안 규칙. 제어 → 답변 → 거절 → 이동 순서로 본다.
 * ("주방 환풍기 꺼줘" 가 주방 화면 이동으로 잘못 잡히지 않도록 제어 규칙을 먼저 본다)
 */
const RULES: Rule[] = [
  { test: (t) => INDUCTION(t) && (CONTROL_WORD(t) || any(t, '세게', '약하게')),
    intent: () => ({ kind: 'refuse', reply: '인덕션은 안전을 위해 음성이나 화면으로 조작할 수 없어요. 위험하면 자동으로 꺼드려요.' }) },
  // 조명: 밝기 → 켜기/끄기
  { test: (t) => LIGHT(t) && DIM(t), intent: (t) => ({ kind: 'control', device: 'light', room: roomOf(t), control: { brightness: 20 } }) },
  { test: (t) => LIGHT(t) && BRIGHT(t) && !OFF(t), intent: (t) => ({ kind: 'control', device: 'light', room: roomOf(t), control: { brightness: 100 } }) },
  { test: (t) => LIGHT(t) && OFF(t), intent: (t) => ({ kind: 'control', device: 'light', room: roomOf(t), control: { on: false } }) },
  { test: (t) => LIGHT(t) && ON(t), intent: (t) => ({ kind: 'control', device: 'light', room: roomOf(t), control: { on: true } }) },
  // 환풍기: 끄기 → 풍량 → 켜기 (환풍기는 주방 · 욕실에만 있다)
  { test: (t) => FAN(t) && OFF(t), intent: (t) => ({ kind: 'control', device: 'fan', room: roomOf(t), control: { on: false } }) },
  { test: (t) => FAN(t) && SPEED_HIGH(t), intent: (t) => ({ kind: 'control', device: 'fan', room: roomOf(t), control: { speed: 3 } }) },
  { test: (t) => FAN(t) && SPEED_MID(t), intent: (t) => ({ kind: 'control', device: 'fan', room: roomOf(t), control: { speed: 2 } }) },
  { test: (t) => FAN(t) && SPEED_LOW(t), intent: (t) => ({ kind: 'control', device: 'fan', room: roomOf(t), control: { speed: 1 } }) },
  { test: (t) => FAN(t) && ON(t), intent: (t) => ({ kind: 'control', device: 'fan', room: roomOf(t), control: { on: true } }) },
  // 공기청정기
  { test: (t) => AIR(t) && OFF(t), intent: () => ({ kind: 'control', device: 'air', room: null, control: { on: false } }) },
  { test: (t) => AIR(t) && ON(t), intent: () => ({ kind: 'control', device: 'air', room: null, control: { on: true } }) },
  { test: (t) => AIR(t) && any(t, '자동'), intent: () => ({ kind: 'control', device: 'air', room: null, control: { mode: 'auto' } }) },
  { test: (t) => AIR(t) && any(t, '수동'), intent: () => ({ kind: 'control', device: 'air', room: null, control: { mode: 'manual' } }) },
  { test: (t) => AIR(t), intent: () => ({ kind: 'answer', topic: 'air' }) },
  { test: (t) => WEATHER(t), intent: () => ({ kind: 'answer', topic: 'weather' }) },
  { test: (t) => WATER(t) && any(t, '줘', '따라', '받'),
    intent: () => ({ kind: 'refuse', reply: '정수기는 아침 자동 출수만 지원해요. 물은 정수기에서 직접 받아 주세요.' }) },
]

/** 화면 이동 명령. 기기 이름이나 조작하는 말이 있으면 이동이 아니다 (백엔드 모드에서는 서버로 보낸다) */
export function matchNavigation(raw: string): Extract<VoiceIntent, { kind: 'navigate' }> | null {
  const t = raw.replace(/\s+/g, '')
  if (!t || DEVICE_WORD(t) || CONTROL_WORD(t) || WEATHER(t)) return null
  if (any(t, '기록', '이력')) return { kind: 'navigate', route: '/history', reply: 'history' }
  if (any(t, '설정', '연락처', '보호자')) return { kind: 'navigate', route: '/settings', reply: 'settings' }
  if (KITCHEN(t)) return { kind: 'navigate', route: '/kitchen', reply: 'kitchen' }
  if (BATH(t)) return { kind: 'navigate', route: '/bathroom', reply: 'bathroom' }
  if (any(t, '우리집', '집', '홈', '전체')) return { kind: 'navigate', route: '/home', reply: 'home' }
  return null
}

/** 시연 모드 규칙 전체 (이동 포함) */
export function matchCommand(raw: string): VoiceIntent | null {
  const t = raw.replace(/\s+/g, '')
  return RULES.find((r) => r.test(t))?.intent(t) ?? matchNavigation(raw)
}

const DEMO = ['주방 상태 알려줘', '침실 불 켜줘', '주방 환풍기 세게 해줘', '오늘 날씨 어때', '공기청정기 켜줘', '침실 불 어둡게 해줘', '기록 보여줘'] as const
let cursor = 0
/** 마이크를 쓰지 않을 때(설정 꺼짐·미지원) 순서대로 재생하는 예시 명령. 화면 안에서만 처리한다 */
export function nextDemoCommand(): string {
  const c = DEMO[cursor % DEMO.length] ?? DEMO[0]
  cursor += 1
  return c
}

export const EXAMPLE_COMMANDS = ['욕실 조명 켜줘', '환풍기 세게', '오늘 날씨 어때'] as const
