import { openDemoChannel, type DemoRequest, type DemoResponse } from './demoChannel'
import { apiConfig } from './source/config'
import type { FallIncident, FallStatus } from '@/types'

/**
 * 보호자 낙상 확인 페이지용 API.
 *   GET  /api/v1/fall-incidents/{id}
 *   POST /api/v1/fall-incidents/{id}/resolve?token=
 *   POST /api/v1/fall-incidents/{id}/report?token=
 * VITE_DATA_SOURCE=http 가 아니면 시연 모드: 같은 브라우저의 대시보드 탭과 BroadcastChannel 로 통신한다.
 */
export interface FallApi {
  readonly demo: boolean
  get(id: string, token: string): Promise<FallIncident | null>
  resolve(id: string, token: string): Promise<FallIncident>
  report(id: string, token: string): Promise<FallIncident>
  /** 상태 변경 즉시 반영용 (시연 모드만). 해제 함수 반환 */
  watch(id: string, onChange: (i: FallIncident) => void): () => void
}

const STATUSES: FallStatus[] = ['pending', 'resolved', 'reported', 'auto_reported']

/** 서버 응답을 그대로 신뢰하지 않고 필요한 형태인지 확인한다 */
function parseIncident(raw: unknown): FallIncident | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (typeof r.incidentId !== 'string' || typeof r.detectedAt !== 'string' || typeof r.autoReportAt !== 'string') return null
  if (!STATUSES.includes(r.status as FallStatus)) return null
  return {
    incidentId: r.incidentId, room: r.room === 'kitchen' ? 'kitchen' : 'bathroom',   // 백엔드 'toilet' 등은 욕실로 본다
    status: r.status as FallStatus, detectedAt: r.detectedAt, autoReportAt: r.autoReportAt,
    confidence: typeof r.confidence === 'number' ? r.confidence : 0,
    confirmUrl: '', resolvedAt: typeof r.resolvedAt === 'string' ? r.resolvedAt : undefined,
    reportedAt: typeof r.reportedAt === 'string' ? r.reportedAt : undefined,
  }
}

function createHttpFallApi(base: string): FallApi {
  const root = base.replace(/\/+$/, '')
  const opts: RequestInit = { credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer' }
  const url = (id: string, tail = '') => `${root}/api/v1/fall-incidents/${encodeURIComponent(id)}${tail}`
  async function act(id: string, token: string, kind: 'resolve' | 'report') {
    const res = await fetch(url(id, `/${kind}?token=${encodeURIComponent(token)}`), { ...opts, method: 'POST' })
    if (!res.ok) throw new Error(res.status === 403 || res.status === 401 ? 'invalid' : 'network')
    const after = await fetch(url(id), opts)
    const parsed = after.ok ? parseIncident(await after.json()) : null
    if (!parsed) throw new Error('network')
    return parsed
  }
  return {
    demo: false,
    async get(id) {
      const res = await fetch(url(id), opts)
      if (res.status === 404) return null
      if (!res.ok) throw new Error('network')
      return parseIncident(await res.json())
    },
    resolve: (id, token) => act(id, token, 'resolve'),
    report: (id, token) => act(id, token, 'report'),
    watch: () => () => {},
  }
}

/** 대시보드 탭이 없을 때 쓰는 단독 시연 사건 (/fall/demo?token=demo) */
let standalone: FallIncident | null = null
function standaloneIncident(): FallIncident {
  if (!standalone) {
    standalone = {
      incidentId: 'demo', room: 'bathroom', status: 'pending', confidence: 0.91, confirmUrl: '',
      detectedAt: new Date(Date.now() - 12_000).toISOString(),
      autoReportAt: new Date(Date.now() + 60_000).toISOString(),
    }
  }
  if (standalone.status === 'pending' && Date.now() >= new Date(standalone.autoReportAt).getTime()) {
    standalone = { ...standalone, status: 'auto_reported', reportedAt: standalone.autoReportAt }
  }
  return { ...standalone }
}

function createDemoFallApi(): FallApi {
  const channel = openDemoChannel()
  const ask = (msg: Omit<DemoRequest, 'requestId'>) => new Promise<FallIncident | null | 'timeout'>((resolve) => {
    if (!channel) return resolve('timeout')
    const requestId = Math.random().toString(36).slice(2)
    const timer = setTimeout(() => { channel.removeEventListener('message', onMsg); resolve('timeout') }, 700)
    function onMsg(e: MessageEvent<DemoResponse>) {
      if (e.data.requestId !== requestId) return
      clearTimeout(timer); channel!.removeEventListener('message', onMsg)
      resolve(e.data.type === 'fall:state' ? e.data.incident : null)
    }
    channel.addEventListener('message', onMsg)
    channel.postMessage({ ...msg, requestId } as DemoRequest)
  })
  const isStandalone = (id: string, token: string) => id === 'demo' && token === 'demo'

  return {
    demo: true,
    async get(id, token) {
      const r = await ask({ type: 'fall:get', incidentId: id, token })
      if (r !== 'timeout') return r
      return isStandalone(id, token) ? standaloneIncident() : null
    },
    async resolve(id, token) {
      const r = await ask({ type: 'fall:resolve', incidentId: id, token })
      if (r && r !== 'timeout') return r
      if (!isStandalone(id, token)) throw new Error('invalid')
      standalone = { ...standaloneIncident(), status: 'resolved', resolvedAt: new Date().toISOString() }
      return { ...standalone }
    },
    async report(id, token) {
      const r = await ask({ type: 'fall:report', incidentId: id, token })
      if (r && r !== 'timeout') return r
      if (!isStandalone(id, token)) throw new Error('invalid')
      standalone = { ...standaloneIncident(), status: 'reported', reportedAt: new Date().toISOString() }
      return { ...standalone }
    },
    watch(id, onChange) {
      if (!channel) return () => {}
      const onMsg = (e: MessageEvent<DemoResponse>) => {
        if (e.data.type === 'fall:state' && e.data.incident.incidentId === id) onChange(e.data.incident)
      }
      channel.addEventListener('message', onMsg)
      return () => channel.removeEventListener('message', onMsg)
    },
  }
}

export function createFallApi(): FallApi {
  const cfg = apiConfig()
  return cfg.mode === 'http' ? createHttpFallApi(cfg.base) : createDemoFallApi()
}
