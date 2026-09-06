import type { TKey } from '@/i18n'
import type { PowerState } from '@/types'

export type VoiceIntent =
  | { kind: 'navigate'; route: string; replyKey: TKey }
  | {
      kind: 'control'
      applianceId: string
      power: PowerState
      confirmKey: TKey
      replyKey: TKey
    }

interface Rule {
  test: (text: string) => boolean
  intent: VoiceIntent
}

const has = (text: string, ...words: string[]) => words.every((w) => text.includes(w))
const hasAny = (text: string, ...words: string[]) => words.some((w) => text.includes(w))

/**
 * 명령 규칙.
 *
 * 제어 명령을 먼저 검사한다. "주방 조명 꺼줘" 같은 문장이
 * 공간 이동 명령으로 잘못 매칭되는 것을 막기 위해서다.
 *
 * 여기에 없는 기능은 음성으로도 제공하지 않는다.
 * (지원되지 않는 가전 기능을 임의로 추가하지 않는다는 원칙)
 */
const RULES: Rule[] = [
  {
    test: (t) => hasAny(t, '조명', '불') && hasAny(t, '켜', '켣'),
    intent: { kind: 'control', applianceId: 'light', power: 'ON', confirmKey: 'voice.confirmLight.on', replyKey: 'voice.reply.done' },
  },
  {
    test: (t) => hasAny(t, '조명', '불') && hasAny(t, '꺼', '끄'),
    intent: { kind: 'control', applianceId: 'light', power: 'OFF', confirmKey: 'voice.confirmLight.off', replyKey: 'voice.reply.done' },
  },
  {
    test: (t) => has(t, '환풍기') && hasAny(t, '켜'),
    intent: { kind: 'control', applianceId: 'fan', power: 'ON', confirmKey: 'voice.confirmFan.on', replyKey: 'voice.reply.done' },
  },
  {
    test: (t) => has(t, '환풍기') && hasAny(t, '꺼', '끄'),
    intent: { kind: 'control', applianceId: 'fan', power: 'OFF', confirmKey: 'voice.confirmFan.off', replyKey: 'voice.reply.done' },
  },
  {
    test: (t) => hasAny(t, '이력', '기록'),
    intent: { kind: 'navigate', route: '/history', replyKey: 'voice.reply.history' },
  },
  {
    test: (t) => has(t, '주방'),
    intent: { kind: 'navigate', route: '/kitchen', replyKey: 'voice.reply.kitchen' },
  },
  {
    test: (t) => hasAny(t, '화장실', '욕실'),
    intent: { kind: 'navigate', route: '/bathroom', replyKey: 'voice.reply.bathroom' },
  },
  {
    test: (t) => hasAny(t, '집', '홈', '전체'),
    intent: { kind: 'navigate', route: '/home', replyKey: 'voice.reply.home' },
  },
]

export function matchCommand(rawText: string): VoiceIntent | null {
  const text = rawText.replace(/\s+/g, '')
  for (const rule of RULES) {
    if (rule.test(text)) return rule.intent
  }
  return null
}

/**
 * Web Speech API 를 쓸 수 없을 때(또는 음성 기능이 꺼져 있을 때) 사용하는 데모 문장.
 * 매번 무작위로 고르면 확인 단계 같은 흐름을 보여주기 어려워 순서대로 돌린다.
 */
const DEMO_COMMANDS = [
  '주방 보여줘',
  '조명 꺼줘',
  '화장실 상태 알려줘',
  '이력 보여줘',
  '우리 집 상태 알려줘',
] as const

let demoCursor = 0

export function nextDemoCommand(): string {
  const command = DEMO_COMMANDS[demoCursor % DEMO_COMMANDS.length] ?? DEMO_COMMANDS[0]
  demoCursor += 1
  return command
}

/** 패널 하단에 노출할 예시 명령어 */
export const EXAMPLE_COMMANDS = ['주방 보여줘', '우리 집 상태 알려줘', '조명 꺼줘'] as const
