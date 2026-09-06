import { BASE_APPLIANCES } from '@/data/appliances'
import { BASE_ENVIRONMENT } from '@/data/environment'
import { ROOM_EVENTS } from '@/data/roomEvents'
import { createSafetyHistory } from '@/data/safetyHistory'
import type { Presence, PowerState, RoomId, SafetyIncident } from '@/types'
import type { HomeSnapshot, RealtimePatch, SafetyDataSource } from './types'

const TICK_MS = 6000

/** 값이 살짝씩 움직여야 '살아있는' 화면으로 보인다. 과하면 산만하므로 미세하게만. */
function jitter(value: number, delta: number, min: number, max: number): number {
  const next = value + (Math.random() * 2 - 1) * delta
  return Math.min(max, Math.max(min, next))
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export function createMockSource(): SafetyDataSource {
  const environment = clone(BASE_ENVIRONMENT)
  const presence: Record<RoomId, Presence> = {
    kitchen: { room: 'kitchen', detected: true, action: '움직임 감지', lastDetectedSec: 2, confidence: 91 },
    bathroom: { room: 'bathroom', detected: true, action: '재실 감지', lastDetectedSec: 4, confidence: 88 },
  }

  const listeners = new Set<(patch: RealtimePatch) => void>()
  let timer: ReturnType<typeof setInterval> | null = null

  function tick() {
    for (const room of ['kitchen', 'bathroom'] as const) {
      const env = environment[room]
      env.metrics = env.metrics.map((m) => {
        if (m.key === 'temp') {
          return { ...m, value: jitter(Number(m.value), 0.3, 21, 27).toFixed(1) }
        }
        if (m.key === 'humidity') {
          const next = Math.round(jitter(Number(m.value), 1.5, 40, 78))
          return { ...m, value: String(next), status: next >= 60 ? 'warning' : 'normal' }
        }
        if (m.key === 'lux') {
          return { ...m, value: String(Math.round(jitter(Number(m.value), 15, 320, 520))) }
        }
        return m
      })
      listeners.forEach((l) => l({ kind: 'environment', room, environment: clone(env) }))

      const p = presence[room]
      p.lastDetectedSec = p.detected ? Math.max(1, Math.round(jitter(p.lastDetectedSec, 3, 1, 12))) : p.lastDetectedSec + 6
      p.confidence = Math.round(jitter(p.confidence, 2, 76, 97))
      listeners.forEach((l) => l({ kind: 'presence', room, presence: { ...p } }))
    }
  }

  return {
    kind: 'mock',

    async loadSnapshot(): Promise<HomeSnapshot> {
      return {
        appliances: clone(BASE_APPLIANCES) as HomeSnapshot['appliances'],
        presence: clone(presence),
        environment: clone(environment),
        roomEvents: clone(ROOM_EVENTS),
        safetyLogs: createSafetyHistory(),
        // 기획서 12번 화면: 연결 오류 배너를 기본 노출해 상태를 보여준다.
        connectionIssue: { room: 'kitchen', lastReceivedSec: 30 },
      }
    },

    async setPower(_applianceId: string, _power: PowerState) {
      /* 목 소스에서는 상태를 스토어가 직접 반영한다. 실제 소스에서는 여기서 API 를 호출한다. */
    },

    subscribe(listener) {
      listeners.add(listener)
      if (timer === null) timer = setInterval(tick, TICK_MS)
      return () => {
        listeners.delete(listener)
        if (listeners.size === 0 && timer !== null) {
          clearInterval(timer)
          timer = null
        }
      }
    },

    createIncident(room: RoomId): SafetyIncident | null {
      if (room !== 'kitchen') return null
      return {
        id: `incident-${Date.now()}`,
        room: 'kitchen',
        title: '주방 이탈이 감지되었습니다',
        description: '인덕션이 작동 중인 상태에서\n주방에서 20초간 사용자가 감지되지 않았습니다.',
        countdownSec: 5,
        facts: [
          { icon: 'flame', text: '인덕션 ON · 화력 3단계', emphasis: true },
          { icon: 'userX', text: '사용자 미감지 20초' },
        ],
        reasoning: ['인덕션 작동 중', '일정 시간 사용자 미감지', '사용자 이탈 가능성 감지'],
        relatedDevices: ['인덕션'],
        confidence: 93,
        action: {
          applianceId: 'induction',
          nextDetail: '화력 1단계',
          logContent: '인덕션 작동 중 이탈 감지 → 화력 자동 저감',
          deviceHistoryText: '자동 안전 판단: 화력 3단계 → 1단계',
        },
      }
    },
  }
}
