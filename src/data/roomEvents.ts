import type { RoomId, TimelineEvent } from '@/types'

/**
 * 공간별 최근 이벤트 타임라인.
 * 여기에는 '상태 감지' 같은 중간 이벤트를 그대로 사용한다.
 * (처리 이력 화면과 달리 공간 화면은 원시 감지 흐름을 보여주는 것이 목적)
 */
export const ROOM_EVENTS: Record<RoomId, TimelineEvent[]> = {
  kitchen: [
    { time: '18:29', kind: 'danger', text: '사용자 미감지 시작' },
    { time: '18:25', kind: 'normal', text: '인덕션 작동 감지' },
    { time: '18:20', kind: 'normal', text: '사용자 움직임 감지' },
    { time: '18:12', kind: 'info', text: '사용자 미감지' },
  ],
  bathroom: [
    { time: '18:18', kind: 'normal', text: '사용자 감지 (입실)' },
    { time: '18:05', kind: 'info', text: '사용자 미감지 (이석)' },
    { time: '17:50', kind: 'normal', text: '사용자 감지 (입실)' },
    { time: '17:40', kind: 'warning', text: '습도 임계치 초과' },
  ],
}
