import type {
  AirLevel, BurnerState, FallStatus, HouseRoom, KitchenPhase, Location, Publisher, Risk, RoomId, SafetyEvent, SafetyEventType,
} from '@/types'

/** 평면도 순서: 주방 | 침실 | 욕실 (부스에서 서로 붙어 있는 순서) */
export const HOUSE_ROOMS: readonly HouseRoom[] = ['kitchen', 'bedroom', 'bathroom']

export const ROOM_LABEL: Record<RoomId, string> = {
  kitchen: '주방', bedroom: '침실', bathroom: '욕실', home: '집',
}

export const LOCATION_LABEL: Record<Location, string> = {
  kitchen: '주방', bedroom: '침실', bathroom: '욕실', outside: '외출 중', unknown: '확인 중',
}

export const AIR_LEVEL_LABEL: Record<AirLevel, string> = { good: '좋음', normal: '보통', bad: '나쁨' }

export const BURNER_LABEL: Record<BurnerState, string> = {
  off: '꺼짐', on: '켜짐', overheated: '과열', cooling: '식는 중',
}

export const PUBLISHER_LABEL: Record<Publisher, string> = {
  user: '본체에서 조작', system: '안전 자동 조치', api: '앱에서 조작',
}

export const FALL_STATUS_LABEL: Record<FallStatus, string> = {
  pending: '보호자 확인 대기 중', resolved: '보호자가 괜찮다고 확인했어요',
  reported: '보호자가 신고를 요청했어요', auto_reported: '응답이 없어 자동으로 신고했어요',
}

export const EVENT_TITLE: Record<SafetyEventType, string> = {
  cooking_started: '조리 시작',
  absence_detected: '주방 이탈 감지',
  auto_power_reduced: '인덕션 화력 자동 저감',
  auto_power_off: '인덕션 전원 자동 차단',
  overheat_detected: '인덕션 과열 감지',
  command_blocked: '과열로 켜기 차단',
  overheat_cleared: '과열 해제',
  user_returned: '주방 복귀',
  cooking_ended: '조리 종료',
  fall_detected: '욕실 낙상 감지',
  fall_resolved: '낙상 — 보호자 확인 완료',
  fall_reported: '낙상 — 보호자 신고 요청',
  fall_auto_reported: '낙상 — 자동 신고',
  fall_escalated: '낙상 — 보호자에게 알림',
  ai_control: 'AI 자동 제어',
  auto_dispense: '아침 자동 출수',
}

export type EventCategory = 'fire' | 'fall' | 'routine'

export function eventCategory(type: SafetyEventType): EventCategory {
  if (type.startsWith('fall_')) return 'fall'
  if (type === 'auto_dispense' || type === 'ai_control') return 'routine'
  return 'fire'
}

export const CATEGORY_LABEL: Record<EventCategory, string> = {
  fire: '화재 예방', fall: '낙상', routine: '생활 자동화',
}

/**
 * "안전 기록" 에 보여줄 이벤트: 시스템이 실제로 무언가를 한 것만.
 * 조리 시작/종료·관찰 시작·복귀 같은 흐름 이벤트는 조리 타임라인에서만 보여준다.
 */
export const RECORD_TYPES: ReadonlySet<SafetyEventType> = new Set<SafetyEventType>([
  'auto_power_reduced', 'auto_power_off', 'overheat_detected', 'fall_detected',
  'fall_resolved', 'fall_reported', 'fall_auto_reported', 'fall_escalated', 'auto_dispense', 'ai_control',
])

/** 사용자가 적절성 피드백을 남길 수 있는 자동 조치 */
export const FEEDBACK_TYPES: ReadonlySet<SafetyEventType> = new Set<SafetyEventType>([
  'auto_power_reduced', 'auto_power_off', 'fall_detected', 'ai_control',
])

export function isRecord(e: SafetyEvent): boolean {
  return RECORD_TYPES.has(e.type)
}

/** BE safetyPhase → 화면 위험 단계 (중앙제어 CAUTION/WARNING/DANGER 에 대응) */
export function phaseRisk(phase: KitchenPhase): Risk {
  switch (phase) {
    case 'absence_watch': return 'caution'
    case 'auto_reduced': return 'warning'
    case 'auto_off':
    case 'overheat': return 'danger'
    default: return 'normal'
  }
}

const RISK_ORDER: Risk[] = ['normal', 'uncertain', 'caution', 'warning', 'danger']
export function maxRisk(...risks: Risk[]): Risk {
  return risks.reduce((a, b) => (RISK_ORDER.indexOf(b) > RISK_ORDER.indexOf(a) ? b : a), 'normal')
}

export const RISK_LABEL: Record<Risk, string> = {
  normal: '안전', caution: '주의', warning: '경고', danger: '위험', uncertain: '확인 필요',
}

/** 상태 색 토큰 (배경 soft / 글자·아이콘 strong) */
export const RISK_TONE: Record<Risk, { soft: string; strong: string; text: string }> = {
  normal: { soft: 'bg-ok-soft', strong: 'bg-ok', text: 'text-ok' },
  caution: { soft: 'bg-caution-soft', strong: 'bg-caution', text: 'text-caution' },
  warning: { soft: 'bg-warn-soft', strong: 'bg-warn', text: 'text-warn' },
  danger: { soft: 'bg-danger-soft', strong: 'bg-danger', text: 'text-danger' },
  uncertain: { soft: 'bg-muted-soft', strong: 'bg-ink-3', text: 'text-ink-2' },
}
