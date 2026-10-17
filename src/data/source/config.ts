/**
 * 데이터 소스 설정 (빌드 시 .env* 에서 읽는다).
 *
 *   VITE_DATA_SOURCE=http   실제 백엔드에 연결. 비어 있으면 시연용 목 데이터.
 *   VITE_API_BASE_URL       백엔드 오리진. 비우면 '같은 주소' — 로컬 개발에서는 Vite 가
 *                           /api 요청을 HOMEVIS_API_TARGET(예: http://127.0.0.1:8000)으로 넘긴다.
 *
 * VITE_ 로 시작하는 값은 브라우저 번들에 그대로 들어가므로 키·토큰·비밀번호를 넣지 않는다.
 */
export interface ApiConfig {
  mode: 'mock' | 'http'
  /** 끝에 / 가 없는 오리진. '' 이면 현재 페이지와 같은 주소 */
  base: string
}

export function apiConfig(): ApiConfig {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
  const http = import.meta.env.VITE_DATA_SOURCE === 'http' || base.length > 0
  return { mode: http ? 'http' : 'mock', base }
}
