import type { FallIncident } from '@/types'

/**
 * 시연 전용: 같은 브라우저의 대시보드 탭 ↔ 보호자 확인 페이지 탭 사이 통신.
 * BroadcastChannel 은 같은 출처(origin) 탭끼리만 통신하며 네트워크를 쓰지 않는다.
 * 실제 서비스에서는 보호자 페이지가 백엔드 API 를 직접 호출하므로 쓰이지 않는다.
 */
export const DEMO_CHANNEL = 'homevis-demo'

export type DemoRequest =
  | { type: 'fall:get'; requestId: string; incidentId: string; token: string }
  | { type: 'fall:resolve'; requestId: string; incidentId: string; token: string }
  | { type: 'fall:report'; requestId: string; incidentId: string; token: string }

export type DemoResponse =
  | { type: 'fall:state'; requestId: string; incident: FallIncident }
  | { type: 'fall:invalid'; requestId: string }

export function openDemoChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null
  try {
    return new BroadcastChannel(DEMO_CHANNEL)
  } catch {
    return null
  }
}
