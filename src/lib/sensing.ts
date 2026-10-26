import type { HouseRoom, SensingNode, SensingSample } from '@/types'

/**
 * 최종 재실 판단(sensing.result) 해석.
 * 백엔드 결과에는 '사람이 있는 공간' 하나만 들어 있다. 공간별 상태는 여기서 이렇게 나눈다.
 *  - 결과의 room 인 공간: 사람 있음 + 그 결과의 신뢰도
 *  - 나머지 공간: 비어 있음 (신뢰도 숫자는 만들지 않는다)
 *  - validSec 이 지난 결과: 오래됨 — 모든 공간을 '확인 중'으로
 */

export const SENSING_WINDOW_MS = 60_000

const ACTIVITY: Record<string, string> = {
  standing: '서 있음', stand: '서 있음',
  sitting: '앉아 있음', sit: '앉아 있음',
  lying: '누워 있음', lie: '누워 있음', lying_down: '누워 있음',
  walking: '걷는 중', walk: '걷는 중', moving: '움직이는 중',
}
const NONE = new Set(['', 'none', 'unknown', 'empty', 'null', 'idle'])

/** 행동 원문 → 화면 글자. 모르는 값은 짧고 안전한 글자만 그대로, 없으면 null */
export function activityLabel(raw: string | null | undefined): string | null {
  if (!raw) return null
  const key = raw.trim().toLowerCase()
  if (NONE.has(key)) return null
  if (ACTIVITY[key]) return ACTIVITY[key]
  return /^[\p{L}\p{N} _-]{1,20}$/u.test(raw.trim()) ? raw.trim() : '동작 확인 중'
}

/** 결과가 아직 유효한지 (observedAt + validSec). 시계가 조금 어긋나도 2초는 봐준다 */
export function isFresh(s: SensingSample | null | undefined, now = Date.now()): boolean {
  if (!s) return false
  const t = new Date(s.at).getTime()
  if (Number.isNaN(t)) return false
  return now - t <= (Math.max(1, s.validSec) + 2) * 1000
}

export interface RoomPresenceView {
  /** live = 유효한 결과, stale = 오래된 결과, none = 결과 없음 */
  freshness: 'live' | 'stale' | 'none'
  present: boolean
  /** 0~100. 사람이 있는 공간이고 판단 담당이 신뢰도를 보냈을 때만 */
  percent: number | null
  activity: string | null
}

export function roomPresence(latest: SensingSample | null, room: HouseRoom, now = Date.now()): RoomPresenceView {
  if (!latest) return { freshness: 'none', present: false, percent: null, activity: null }
  const here = latest.present && latest.room === room
  return {
    freshness: isFresh(latest, now) ? 'live' : 'stale',
    present: here,
    percent: here && latest.confidence !== null ? Math.round(latest.confidence * 100) : null,
    activity: here ? activityLabel(latest.activity) : null,
  }
}

/** 최근 1분 동안 그 공간의 재실 신뢰도 (사람이 없던 순간은 0, 신뢰도가 없으면 있음=100) */
export function roomSeries(history: SensingSample[], room: HouseRoom, now = Date.now()): number[] {
  const from = now - SENSING_WINDOW_MS
  return history
    .filter((s) => new Date(s.at).getTime() >= from)
    .map((s) => (s.present && s.room === room ? Math.round((s.confidence ?? 1) * 100) : 0))
}

export const NODE_STATUS_LABEL: Record<SensingNode['status'], string> = {
  ok: '정상', stale: '응답 없음', missing: '연결 안 됨', other: '점검 필요',
}

/** 신호 세기 4단계 (dBm). -55 이상 아주 좋음 · -67 이상 좋음 · -75 이상 보통 · 그 아래 약함 */
export function rssiBars(rssi: number | undefined): 0 | 1 | 2 | 3 | 4 {
  if (rssi === undefined) return 0
  if (rssi >= -55) return 4
  if (rssi >= -67) return 3
  if (rssi >= -75) return 2
  return 1
}
