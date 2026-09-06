import type { SafetyDataSource } from './types'

/**
 * 실제 백엔드 연동 자리.
 *
 * 아직 연동 대상이 없으므로 구현하지 않는다.
 * 붙일 때 지켜야 할 것:
 *  - 액세스 토큰을 localStorage / sessionStorage 에 저장하지 않는다.
 *    (httpOnly + SameSite=Strict 쿠키 사용, fetch 는 credentials: 'same-origin')
 *  - 서버 응답을 그대로 신뢰하지 말고 렌더링 전에 형태를 검증한다.
 *  - 실시간 갱신은 same-origin WebSocket(wss) 을 사용하고,
 *    vite.config.ts 의 CSP connect-src 에 해당 오리진을 추가한다.
 *  - 응답 문자열을 innerHTML 로 넣지 않는다. React 의 기본 이스케이프에 맡긴다.
 */
export function createHttpSource(_baseUrl: string): SafetyDataSource {
  throw new Error(
    'httpSource 는 아직 구현되지 않았습니다. 백엔드 API 명세가 확정되면 이 파일을 채우세요.',
  )
}
