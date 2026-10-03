import { createMockSource } from './mockSource'
import { createHttpSource } from './httpSource'
import type { DataSource } from './types'

/** VITE_API_BASE_URL 이 비어 있으면 시연용 목 데이터 소스를 쓴다. 시크릿을 넣지 말 것. */
export function createDataSource(): DataSource {
  const baseUrl = import.meta.env.VITE_API_BASE_URL
  if (typeof baseUrl === 'string' && baseUrl.length > 0) return createHttpSource(baseUrl)
  return createMockSource()
}

export type { DataSource, Snapshot, StreamMessage, DeviceControl, DemoControls } from './types'
