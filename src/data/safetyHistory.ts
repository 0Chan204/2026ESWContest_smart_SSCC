import type { SafetyLog } from '@/types'

/**
 * 처리 이력 목 데이터.
 *
 * 기획서에 따라 '상태 감지' / '상태 판단' 같은 중간 이벤트는 포함하지 않는다.
 * 실제로 시스템이 수행한 "안전 처리"만 담는다.
 *
 * 날짜는 앱을 여는 시점 기준 최근 6일로 생성한다.
 * 하드코딩된 과거 날짜를 쓰면 날짜 범위 필터가 항상 빈 결과를 내기 때문이다.
 */

interface Seed {
  dayAgo: number
  time: [number, number, number]
  room: SafetyLog['room']
  content: string
  result: SafetyLog['result']
  reasoning: string[]
  relatedDevices: string[]
  confidence: number
}

const SEEDS: Seed[] = [
  {
    dayAgo: 0, time: [18, 29, 20], room: 'kitchen',
    content: '인덕션 작동 중 이탈 감지 → 화력 자동 저감',
    result: 'success',
    reasoning: ['인덕션 작동 중', '주방에서 25초간 사용자 미감지', '사용자 이탈 가능성 감지'],
    relatedDevices: ['인덕션'], confidence: 93,
  },
  {
    dayAgo: 0, time: [17, 50, 11], room: 'bathroom',
    content: '습도 상승에 따른 환풍기 자동 작동',
    result: 'success',
    reasoning: ['습도 80% 초과 상태 지속', '환기 필요 판단'],
    relatedDevices: ['환풍기'], confidence: 88,
  },
  {
    dayAgo: 1, time: [21, 15, 32], room: 'kitchen',
    content: '야간 장시간 사용자 미감지 → 안전 확인 알림',
    result: 'success',
    reasoning: ['야간 시간대', '주방 1시간 이상 사용자 미감지'],
    relatedDevices: ['인덕션', '조명'], confidence: 84,
  },
  {
    dayAgo: 1, time: [9, 41, 5], room: 'kitchen',
    content: '인덕션 고온 지속 감지 → 경고 알림 발송',
    result: 'warning',
    reasoning: ['표면 온도 120°C 이상', '15분 이상 지속'],
    relatedDevices: ['인덕션'], confidence: 90,
  },
  {
    dayAgo: 2, time: [19, 3, 44], room: 'bathroom',
    content: '장시간 재실 감지 → 안전 확인 알림',
    result: 'success',
    reasoning: ['화장실 40분 이상 재실', '움직임 감소'],
    relatedDevices: ['환풍기'], confidence: 81,
  },
  {
    dayAgo: 2, time: [14, 22, 18], room: 'kitchen',
    content: '비정상 연기 감지 → 환기 자동 작동',
    result: 'success',
    reasoning: ['공기질 센서 이상 수치', '조리 중 상태'],
    relatedDevices: ['환풍기', '조명'], confidence: 87,
  },
  {
    dayAgo: 3, time: [22, 8, 55], room: 'bathroom',
    content: '심야 장시간 재실 → 보호자 알림 발송',
    result: 'success',
    reasoning: ['오후 10시 이후', '30분 이상 재실'],
    relatedDevices: ['환풍기'], confidence: 86,
  },
  {
    dayAgo: 3, time: [18, 45, 30], room: 'kitchen',
    content: '인덕션 작동 중 이탈 감지 → 화력 자동 저감',
    result: 'success',
    reasoning: ['인덕션 작동 중', '30초간 사용자 미감지'],
    relatedDevices: ['인덕션'], confidence: 92,
  },
  {
    dayAgo: 4, time: [16, 30, 12], room: 'kitchen',
    content: '조리 중 이상 온도 감지 → 경고 알림',
    result: 'warning',
    reasoning: ['예상 조리 온도 초과', '사용자 감지 상태'],
    relatedDevices: ['인덕션'], confidence: 79,
  },
  {
    dayAgo: 4, time: [11, 15, 40], room: 'bathroom',
    content: '습도 임계치 초과 → 환풍기 자동 작동',
    result: 'success',
    reasoning: ['습도 75% 초과 감지'],
    relatedDevices: ['환풍기'], confidence: 89,
  },
  {
    dayAgo: 5, time: [20, 22, 5], room: 'kitchen',
    content: '심야 인덕션 미감지 작동 → 전원 자동 차단',
    result: 'success',
    reasoning: ['오후 8시 이후', '사용자 미감지 상태에서 인덕션 작동'],
    relatedDevices: ['인덕션'], confidence: 94,
  },
  {
    dayAgo: 5, time: [15, 48, 33], room: 'bathroom',
    content: '장시간 재실 감지 → 안전 확인 알림',
    result: 'success',
    reasoning: ['화장실 35분 이상 재실'],
    relatedDevices: ['환풍기'], confidence: 82,
  },
  {
    dayAgo: 6, time: [19, 12, 47], room: 'kitchen',
    content: '가스레인지 주변 고온 감지 → 환기 자동 작동',
    result: 'success',
    reasoning: ['주방 온도 급상승', '조리 중 상태'],
    relatedDevices: ['환풍기'], confidence: 85,
  },
  {
    dayAgo: 6, time: [8, 5, 9], room: 'bathroom',
    content: '이른 시간 장시간 재실 → 안전 확인 알림',
    result: 'success',
    reasoning: ['오전 6시 이전', '25분 이상 재실'],
    relatedDevices: ['환풍기'], confidence: 80,
  },
]

function isoAt(dayAgo: number, [h, m, s]: [number, number, number]): string {
  const d = new Date()
  d.setDate(d.getDate() - dayAgo)
  d.setHours(h, m, s, 0)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(h)}:${p(m)}:${p(s)}`
}

export function createSafetyHistory(): SafetyLog[] {
  return SEEDS.map((seed, i) => ({
    id: `log-${i + 1}`,
    datetime: isoAt(seed.dayAgo, seed.time),
    room: seed.room,
    content: seed.content,
    result: seed.result,
    reasoning: seed.reasoning,
    relatedDevices: seed.relatedDevices,
    confidence: seed.confidence,
  })).sort((a, b) => b.datetime.localeCompare(a.datetime))
}

/** 목 데이터가 커버하는 기간 (기본 날짜 범위 필터 값) */
export const HISTORY_DAY_SPAN = 6
