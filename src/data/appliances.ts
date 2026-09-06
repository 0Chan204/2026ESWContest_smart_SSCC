import type { Appliance } from '@/types'

/**
 * 목 가전 데이터.
 *
 * supportsControl 이 false 인 기기는 제어 UI 를 렌더링하지 않는다.
 * (기획서: "지원하지 않는 가전 제어 기능을 억지로 UI에 추가하지 않는다")
 * 인덕션은 안전상 사용자 임의 원격 제어를 제공하지 않고, 시스템의 자동 안전 조치만 수행한다.
 */
export const BASE_APPLIANCES: readonly Appliance[] = [
  {
    id: 'induction',
    name: '인덕션',
    room: 'kitchen',
    power: 'ON',
    status: 'normal',
    detail: '화력 3단계',
    sub: '표면 온도 62°C · 작동 12분',
    lastUpdate: '방금 전',
    supportsControl: false,
    history: [
      { time: '18:29', kind: 'warning', text: '자동 안전 판단: 화력 3단계 → 1단계' },
      { time: '18:25', kind: 'info', text: '상태 변경 감지' },
      { time: '18:20', kind: 'normal', text: '전원 ON' },
    ],
  },
  {
    id: 'purifier',
    name: '정수기',
    room: 'kitchen',
    power: 'STANDBY',
    status: 'normal',
    detail: '마지막 출수 10:15',
    sub: '필터 잔여 78%',
    lastUpdate: '10분 전',
    supportsControl: false,
    history: [
      { time: '10:15', kind: 'normal', text: '출수 완료 (250ml)' },
      { time: '09:42', kind: 'normal', text: '출수 완료 (180ml)' },
    ],
  },
  {
    id: 'fan',
    name: '환풍기',
    room: 'bathroom',
    power: 'OFF',
    status: 'normal',
    detail: '습도 62%',
    sub: '자동 모드',
    lastUpdate: '5분 전',
    supportsControl: true,
    history: [
      { time: '17:50', kind: 'normal', text: '자동 종료 (습도 정상)' },
      { time: '17:40', kind: 'warning', text: '자동 작동 (습도 80% 초과)' },
    ],
  },
  {
    id: 'light',
    name: '조명',
    room: 'kitchen',
    power: 'ON',
    status: 'normal',
    detail: '밝기 70%',
    sub: '백색 모드',
    lastUpdate: '방금 전',
    supportsControl: true,
    history: [
      { time: '17:05', kind: 'normal', text: '전원 ON' },
      { time: '17:04', kind: 'info', text: '밝기 70% 설정' },
    ],
  },
]
