import type { RoomId } from '@/types'

export type VoiceIntent =
  | { kind: 'navigate'; route: string; reply: 'home' | 'kitchen' | 'bathroom' | 'history' | 'settings' }
  /** 기기 id 는 데이터 소스마다 달라(시연 light-bath-01 / 백엔드 light-00) 종류 · 공간으로 찾는다 */
  | { kind: 'control'; device: 'light' | 'fan'; room: RoomId; on: boolean; confirm: string }
  /** 지원하지 않는 조작 (인덕션 등) — 이유를 안내한다 */
  | { kind: 'refuse'; reply: string }

interface Rule { test: (t: string) => boolean; intent: VoiceIntent }

const has = (t: string, ...w: string[]) => w.every((x) => t.includes(x))
const any = (t: string, ...w: string[]) => w.some((x) => t.includes(x))
const ON = (t: string) => any(t, '켜')
const OFF = (t: string) => any(t, '꺼', '끄')
const LIGHT = (t: string) => any(t, '조명', '전등')
const FAN = (t: string) => any(t, '환풍기', '후드')
const BEDROOM = (t: string) => any(t, '침실', '안방')
const BATH = (t: string) => any(t, '욕실', '화장실')

/**
 * 명령 규칙. 제어 → 거절 → 이동 순서로 검사한다.
 * ("주방 환풍기 꺼줘" 가 주방 화면 이동으로 잘못 잡히지 않도록 제어 규칙을 먼저 본다)
 */
const RULES: Rule[] = [
  { test: (t) => any(t, '인덕션', '화구', '불') && (ON(t) || OFF(t) || any(t, '올려', '낮춰', '세게', '약하게')),
    intent: { kind: 'refuse', reply: '인덕션은 안전을 위해 음성이나 화면으로 조작할 수 없어요. 위험하면 자동으로 꺼드려요.' } },
  { test: (t) => LIGHT(t) && BEDROOM(t) && ON(t), intent: { kind: 'control', device: 'light', room: 'bedroom', on: true, confirm: '침실 조명을 켤까요?' } },
  { test: (t) => LIGHT(t) && BEDROOM(t) && OFF(t), intent: { kind: 'control', device: 'light', room: 'bedroom', on: false, confirm: '침실 조명을 끌까요?' } },
  { test: (t) => LIGHT(t) && ON(t), intent: { kind: 'control', device: 'light', room: 'bathroom', on: true, confirm: '욕실 조명을 켤까요?' } },
  { test: (t) => LIGHT(t) && OFF(t), intent: { kind: 'control', device: 'light', room: 'bathroom', on: false, confirm: '욕실 조명을 끌까요?' } },
  { test: (t) => FAN(t) && BATH(t) && ON(t), intent: { kind: 'control', device: 'fan', room: 'bathroom', on: true, confirm: '욕실 환풍기를 켤까요?' } },
  { test: (t) => FAN(t) && BATH(t) && OFF(t), intent: { kind: 'control', device: 'fan', room: 'bathroom', on: false, confirm: '욕실 환풍기를 끌까요?' } },
  { test: (t) => FAN(t) && ON(t), intent: { kind: 'control', device: 'fan', room: 'kitchen', on: true, confirm: '주방 환풍기를 켤까요?' } },
  { test: (t) => FAN(t) && OFF(t), intent: { kind: 'control', device: 'fan', room: 'kitchen', on: false, confirm: '주방 환풍기를 끌까요?' } },
  { test: (t) => any(t, '정수기', '물') && any(t, '줘', '따라', '받'),
    intent: { kind: 'refuse', reply: '정수기는 아침 자동 출수만 지원해요. 물은 정수기에서 직접 받아 주세요.' } },
  { test: (t) => any(t, '기록', '이력'), intent: { kind: 'navigate', route: '/history', reply: 'history' } },
  { test: (t) => any(t, '설정', '연락처', '보호자'), intent: { kind: 'navigate', route: '/settings', reply: 'settings' } },
  { test: (t) => has(t, '주방') || any(t, '인덕션'), intent: { kind: 'navigate', route: '/kitchen', reply: 'kitchen' } },
  { test: (t) => any(t, '욕실', '화장실'), intent: { kind: 'navigate', route: '/bathroom', reply: 'bathroom' } },
  { test: (t) => any(t, '집', '홈', '전체'), intent: { kind: 'navigate', route: '/home', reply: 'home' } },
]

export function matchCommand(raw: string): VoiceIntent | null {
  const t = raw.replace(/\s+/g, '')
  return RULES.find((r) => r.test(t))?.intent ?? null
}

const DEMO = ['주방 상태 알려줘', '욕실 조명 켜줘', '인덕션 꺼줘', '기록 보여줘', '우리 집 상태 알려줘'] as const
let cursor = 0
/** 마이크를 쓰지 않을 때(설정 꺼짐·미지원) 순서대로 재생하는 예시 명령 */
export function nextDemoCommand(): string {
  const c = DEMO[cursor % DEMO.length] ?? DEMO[0]
  cursor += 1
  return c
}

export const EXAMPLE_COMMANDS = ['주방 상태 알려줘', '욕실 조명 켜줘', '기록 보여줘'] as const
