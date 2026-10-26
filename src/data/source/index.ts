import { createMockSource } from './mockSource'
import { createHttpSource } from './httpSource'
import { apiConfig } from './config'
import type { DataSource } from './types'

/** VITE_DATA_SOURCE=http 면 백엔드, 아니면 시연용 목 데이터 소스. 시크릿을 넣지 말 것. */
export function createDataSource(): DataSource {
  const cfg = apiConfig()
  return cfg.mode === 'http' ? createHttpSource(cfg.base) : createMockSource()
}

export type { DataSource, Snapshot, StreamMessage, DeviceControl, DemoControls, VoiceRecord, VoiceService, VoiceStatus, VoiceMeta } from './types'
