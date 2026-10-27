import type {
  CookingSession, Device, FallPolicy, KitchenPolicy, Presence, SafetyEvent, SafetyEventType, SensingSample, Severity,
} from '@/types'

/**
 * 시연용 초기 데이터.
 * 개인정보를 만들지 않기 위해 연락처는 비워 둔다 (등록 흐름을 시연할 수 있도록).
 * 날짜는 앱을 연 시점 기준으로 생성해 날짜 필터가 항상 의미 있게 동작하게 한다.
 */

export const DEFAULT_POLICY: KitchenPolicy = {
  watchAfterSec: 60,
  reduceAfterSec: 180,
  offAfterSec: 600,
  reduceToLevel: 1,
  minConfidence: 0.7,
  nearZoneMultiplier: 2,
  overheatEnterC: 150,
  overheatExitC: 60,
  heartbeatTimeoutSec: 15,
}

export const DEFAULT_FALL_POLICY: FallPolicy = { autoReportSec: 60 }

export function isoAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString()
}

function isoAt(daysAgo: number, h: number, m: number, s = 0): string {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  d.setHours(h, m, s, 0)
  return d.toISOString()
}

const MIN = 60_000

export function seedDevices(): Device[] {
  const history: number[] = []
  for (let i = 0; i < 40; i++) history.push(Math.round((40 + i * 1.45) * 10) / 10)
  return [
    {
      id: 'induction-01', kind: 'induction', name: '인덕션', room: 'kitchen', online: true,
      burner: { burnerId: 'burner-1', deviceState: 'on', level: 4, temperature: 97.5, activeSec: 720 },
      lastControl: 'user', alarm: false, tempHistory: history,
    },
    // 백엔드 기본 구성(device_registry)과 같은 순서 · 배치: 침실·욕실 조명, 정수기, 주방·욕실 환풍기
    // 침실은 비어 있어 HomeVIS 가 절전 밝기로 낮춰 둔 상태
    { id: 'light-bed-01', kind: 'light', name: '침실 조명', room: 'bedroom', online: true, on: true, brightness: 20, auto: true, saving: true },
    { id: 'light-bath-01', kind: 'light', name: '욕실 조명', room: 'bathroom', online: true, on: false, brightness: 80, auto: true },
    {
      id: 'purifier-01', kind: 'purifier', name: '정수기', room: 'kitchen', online: true,
      dispensing: false, lastDispense: { at: isoAt(1, 7, 42), ml: 250, auto: true }, autoDispensedToday: false,
    },
    { id: 'fan-01', kind: 'fan', name: '주방 환풍기', room: 'kitchen', online: true, on: true, speed: 2, auto: true },
    { id: 'fan-bath-01', kind: 'fan', name: '욕실 환풍기', room: 'bathroom', online: true, on: false, speed: 1, auto: true },
    // 백엔드 v0.7 공기청정기(air-01, 방). 조리 중이라 HomeVIS 가 켜 둔 상태
    {
      id: 'air-01', kind: 'air', name: '공기청정기', room: 'bedroom', online: true, on: true, mode: 'auto',
      airQuality: { pm25: 24, pm10: 38, level: 'normal' }, auto: true, autoReason: 'induction',
    },
  ]
}

/** 최근 1분 재실 판단 (주방에 서 있음) — 1초 간격 */
export function seedSensing(): SensingSample[] {
  const now = Date.now()
  return Array.from({ length: 60 }, (_, i) => ({
    at: new Date(now - (60 - i) * 1000).toISOString(), room: 'kitchen' as const, present: true,
    confidence: Math.round((0.9 + Math.sin(i / 6) * 0.03 + (i % 7) * 0.003) * 100) / 100,
    activity: i > 20 && i < 26 ? 'walking' : 'standing', activityConfidence: 0.8, validSec: 5,
  }))
}

export function seedPresence(): { kitchen: Presence; bathroom: Presence } {
  return {
    kitchen: { room: 'kitchen', present: true, zone: 'kitchen', absentSec: 0, confidence: 0.94, observedAt: isoAgo(2000) },
    bathroom: { room: 'bathroom', present: false, zone: 'unknown', absentSec: 0, confidence: 0.9, observedAt: isoAgo(4000) },
  }
}

export const GUIDANCE: Partial<Record<SafetyEventType, string>> = {
  absence_detected: '주방에 사람이 보이지 않아요. 조리 중이시면 주방으로 돌아와 주세요.',
  auto_power_reduced: '주방에 사람이 없어 인덕션 화력을 1단으로 낮췄어요. 조리 중이셨다면 돌아와서 확인해 주세요.',
  auto_power_off: '주방을 오래 비우셔서 인덕션을 껐어요. 다시 조리하시려면 인덕션에서 직접 켜 주세요.',
  overheat_detected: '인덕션이 너무 뜨거워요. 화구가 식을 때까지는 켤 수 없어요.',
  fall_detected: '욕실에서 넘어지신 것 같아요. 보호자에게 바로 알렸어요.',
  fall_auto_reported: '보호자 응답이 없어 자동으로 신고 처리했어요.',
  auto_dispense: '좋은 아침이에요. 물 한 컵(250mL)을 준비했어요.',
}

let seq = 0
function ev(
  type: SafetyEventType, severity: Severity, occurredAt: string, room: SafetyEvent['room'],
  extra: Partial<SafetyEvent> = {},
): SafetyEvent {
  seq += 1
  return { eventId: `evt-seed-${seq}`, type, severity, occurredAt, room, guidance: GUIDANCE[type], ...extra }
}

function session(id: string, start: string, minutes: number, peak: number, middle: CookingSession['timeline']): CookingSession {
  const end = new Date(new Date(start).getTime() + minutes * MIN).toISOString()
  return {
    sessionId: id, startedAt: start, endedAt: end, status: 'ended', peakTemperature: peak,
    timeline: [{ at: start, type: 'cooking_started', summary: '화구 켜짐' }, ...middle, { at: end, type: 'cooking_ended', summary: '화구 꺼짐' }],
  }
}

export function seedHistory(): { events: SafetyEvent[]; sessions: CookingSession[] } {
  seq = 0
  const s1Start = isoAt(1, 18, 10)
  const s2Start = isoAt(2, 18, 40)
  const s3Start = isoAt(3, 17, 20)
  const s4Start = isoAt(4, 11, 50)
  const s5Start = isoAt(6, 20, 0)

  const sessions: CookingSession[] = [
    session('ses-seed-1', s1Start, 34, 132, [
      { at: isoAt(1, 18, 25), type: 'absence_detected', summary: '사용자 이탈 감지 (관찰 시작)' },
      { at: isoAt(1, 18, 29), type: 'auto_power_reduced', summary: '화력 5 → 1단 자동 저감' },
      { at: isoAt(1, 18, 33), type: 'user_returned', summary: '사용자 복귀' },
    ]),
    session('ses-seed-2', s2Start, 33, 118, [
      { at: isoAt(2, 18, 50), type: 'absence_detected', summary: '사용자 이탈 감지 (관찰 시작)' },
      { at: isoAt(2, 18, 53), type: 'auto_power_reduced', summary: '화력 4 → 1단 자동 저감' },
      { at: isoAt(2, 19, 3), type: 'auto_power_off', summary: '장시간 부재로 자동 전원 차단' },
    ]),
    session('ses-seed-3', s3Start, 40, 151, [
      { at: isoAt(3, 17, 40), type: 'overheat_detected', summary: '표면 온도 151°C 과열 잠금' },
      { at: isoAt(3, 17, 52), type: 'overheat_cleared', summary: '냉각 완료 · 잠금 해제' },
    ]),
    session('ses-seed-4', s4Start, 30, 104, [
      { at: isoAt(4, 12, 6), type: 'absence_detected', summary: '사용자 이탈 감지 (관찰 시작)' },
      { at: isoAt(4, 12, 10), type: 'auto_power_reduced', summary: '화력 3 → 1단 자동 저감' },
    ]),
    session('ses-seed-5', s5Start, 35, 126, [
      { at: isoAt(6, 20, 18), type: 'absence_detected', summary: '사용자 이탈 감지 (관찰 시작)' },
      { at: isoAt(6, 20, 22), type: 'auto_power_reduced', summary: '화력 6 → 1단 자동 저감' },
    ]),
  ]

  const events: SafetyEvent[] = [
    ev('auto_power_reduced', 'warning', isoAt(1, 18, 29), 'kitchen', {
      sessionId: 'ses-seed-1', temperature: 132, trigger: '주방 부재 3분 경과 · 감지 정확도 92%',
      action: '화력 5단 → 1단 자동 저감', reasoning: '인덕션 작동 중 사용자 이탈이 기준 시간을 넘음',
      feedback: { verdict: 'approved', submittedAt: isoAt(1, 18, 34) },
    }),
    ev('auto_dispense', 'info', isoAt(1, 7, 42), 'kitchen', {
      trigger: '기상 후 18분 만에 주방 이동 · 5초 이상 머무름', action: '정수기 250mL 자동 출수',
      reasoning: '아침 6~10시 기상 감지 후 30분 이내 주방 이동',
    }),
    ev('fall_detected', 'danger', isoAt(2, 22, 8), 'bathroom', {
      trigger: '서 있다가 누운 자세로 바뀐 뒤 10초간 움직임 없음', action: '보호자 문자 발송 · 인덕션 상태 확인(꺼져 있음)',
      reasoning: '욕실 낙상 의심 (감지 정확도 89%)',
    }),
    ev('fall_resolved', 'info', isoAt(2, 22, 9), 'bathroom', { action: '보호자가 "괜찮음" 으로 확인', reasoning: '보호자 확인 링크 응답' }),
    ev('auto_power_off', 'danger', isoAt(2, 19, 3), 'kitchen', {
      sessionId: 'ses-seed-2', temperature: 108, trigger: '주방 부재 10분 경과', action: '인덕션 전원 자동 차단',
      reasoning: '화력 저감 후에도 사용자가 돌아오지 않음',
    }),
    ev('auto_power_reduced', 'warning', isoAt(2, 18, 53), 'kitchen', {
      sessionId: 'ses-seed-2', temperature: 118, trigger: '주방 부재 3분 경과 · 감지 정확도 90%',
      action: '화력 4단 → 1단 자동 저감', reasoning: '인덕션 작동 중 사용자 이탈이 기준 시간을 넘음',
    }),
    ev('overheat_detected', 'danger', isoAt(3, 17, 40), 'kitchen', {
      sessionId: 'ses-seed-3', temperature: 151, trigger: '표면 온도 151°C (기준 150°C)',
      action: '과열 잠금 — 식을 때까지 켜기 차단', reasoning: '인덕션 본체가 과열 상태를 보고',
    }),
    ev('auto_dispense', 'info', isoAt(3, 7, 35), 'kitchen', {
      trigger: '기상 후 12분 만에 주방 이동', action: '정수기 250mL 자동 출수', reasoning: '아침 자동 출수 (하루 1회)',
    }),
    ev('auto_power_reduced', 'warning', isoAt(4, 12, 10), 'kitchen', {
      sessionId: 'ses-seed-4', temperature: 104, trigger: '주방 부재 3분 경과 · 감지 정확도 88%',
      action: '화력 3단 → 1단 자동 저감', reasoning: '인덕션 작동 중 사용자 이탈이 기준 시간을 넘음',
      feedback: { verdict: 'rejected', submittedAt: isoAt(4, 12, 20) },
    }),
    ev('fall_detected', 'danger', isoAt(5, 6, 50), 'bathroom', {
      trigger: '걷다가 누운 자세로 바뀐 뒤 움직임 없음', action: '보호자 문자 발송',
      reasoning: '욕실 낙상 의심 (감지 정확도 86%)',
    }),
    ev('fall_auto_reported', 'danger', isoAt(5, 6, 51), 'bathroom', {
      action: '보호자 응답 없음 → 자동 신고 처리', reasoning: '확인 대기 시간 60초 초과',
    }),
    ev('auto_dispense', 'info', isoAt(5, 7, 50), 'kitchen', {
      trigger: '기상 후 21분 만에 주방 이동', action: '정수기 250mL 자동 출수', reasoning: '아침 자동 출수 (하루 1회)',
    }),
    ev('auto_power_reduced', 'warning', isoAt(6, 20, 22), 'kitchen', {
      sessionId: 'ses-seed-5', temperature: 126, trigger: '주방 부재 3분 경과 · 감지 정확도 91%',
      action: '화력 6단 → 1단 자동 저감', reasoning: '인덕션 작동 중 사용자 이탈이 기준 시간을 넘음',
    }),
  ]

  events.sort((a, b) => b.occurredAt.localeCompare(a.occurredAt))
  return { events, sessions }
}
