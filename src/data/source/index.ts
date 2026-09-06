import { createMockSource } from './mockSource'
import { createHttpSource } from './httpSource'
import type { SafetyDataSource } from './types'

/**
 * 데이터 소스 선택.
 * 기본은 mock 이며, VITE_API_BASE_URL 이 설정된 경우에만 http 소스를 사용한다.
 * 환경변수에는 절대 시크릿을 넣지 않는다. Vite 는 VITE_ 접두사 값을 번들에 그대로 포함한다.
 */
export function createDataSource(): SafetyDataSource {
  const baseUrl = import.meta.env.VITE_API_BASE_URL
  if (typeof baseUrl === 'string' && baseUrl.length > 0) {
    return createHttpSource(baseUrl)
  }
  return createMockSource()
}

export type { SafetyDataSource, HomeSnapshot, RealtimePatch } from './types'
