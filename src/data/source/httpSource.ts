import type { DataSource } from './types'

/**
 * 실제 백엔드 연동 자리 (HomeVIS-Backend v0.2.1).
 *
 * 대응 관계 — 화면 코드는 바뀌지 않고 이 파일만 채우면 된다.
 *   loadSnapshot      GET  /api/v1/snapshot + /safety-events + /user + /guardian + /policies/*
 *   subscribe         WSS  /api/v1/stream  (재연결 시 ?since={lastEventId})
 *   submitFeedback    POST /api/v1/safety-events/{id}/feedback
 *   saveContact       PUT  /api/v1/user | /api/v1/guardian
 *   savePolicy        PUT  /api/v1/policies/kitchen-absence
 *   saveFallPolicy    PUT  /api/v1/policies/fall-safety
 *   controlDevice     (환풍기·욕실 조명 API 는 백엔드에 아직 없음)
 *
 * 연동 전 백엔드에 필요한 것: CORS 허용 목록, 인증, 정수기·환풍기·조명·위치 이벤트.
 * 원칙: 토큰은 localStorage 에 두지 않는다(httpOnly 쿠키), 응답은 렌더링 전에 형태를 검증한다.
 */
export function createHttpSource(_baseUrl: string): DataSource {
  throw new Error('httpSource 는 백엔드 CORS·인증 준비 후 구현합니다. 현재는 VITE_API_BASE_URL 을 비워 두세요.')
}
