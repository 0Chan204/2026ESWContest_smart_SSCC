import type {
  Burner, BurnerState, Contact, ContactSaveResult, CookingSession, Device, FallIncident, FallPolicy,
  FallStatus, InductionDevice, KitchenPolicy, LightDevice, Location, Presence, Publisher, PurifierDevice,
  HourlyWeather, RoomId, SafetyEvent, SafetyEventType, Severity, Weather, Zone,
} from '@/types'
import type { DataSource, DeviceControl, Snapshot, StreamMessage } from './types'

/**
 * 실제 백엔드 연동 (HomeVIS-Backend v0.4.x, develop).
 *
 *   loadSnapshot   GET  /snapshot · /safety-events · /sessions/{id} · /user · /guardian
 *                       · /policies/kitchen-absence · /policies/fall-safety · /sensing/results/latest
 *   subscribe      WS   /stream  (끊기면 다시 연결, ?since={마지막 이벤트 id} 로 놓친 안전 이벤트 받기)
 *                  GET  /devices  (15초마다 — 기기 응답 없음 판정은 서버가 하고, 바뀐 것만 알린다)
 *   controlDevice  POST /devices/{id}/commands  (전등 on/off 만. 인덕션은 조회 전용, 환풍기는 백엔드에 없음)
 *   submitFeedback POST /safety-events/{id}/feedback
 *   saveContact    PUT  /user | /guardian
 *   savePolicy     PUT  /policies/kitchen-absence
 *   saveFallPolicy PUT  /policies/fall-safety
 *   loadWeather    GET  /weather  (서버가 30분마다 미리 받아 둔 날씨. 서버는 키 없는 무료 Open-Meteo 사용)
 *
 * 원칙
 * - 서버 응답은 그대로 믿지 않고 필요한 필드만 골라 형태를 확인한 뒤 화면 형식으로 바꾼다.
 * - 쿠키·토큰을 보내지 않는다(credentials: 'omit'). 인증은 백엔드에 아직 없다.
 * - base 가 '' 이면 같은 주소로 요청하고, 로컬 개발에서는 Vite 프록시가 백엔드로 넘긴다.
 */

const API = '/api/v1'
const DEVICE_POLL_MS = 15_000
const HISTORY_LEN = 60
const SESSION_FETCH_LIMIT = 10

// ── 작은 검사 도구 ─────────────────────────────────────────────────────────
type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback)
const optStr = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined)
const num = (v: unknown, fallback = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : fallback)
const optNum = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const nowIso = () => new Date().toISOString()

// ── 백엔드 값 → 화면 값 ────────────────────────────────────────────────────
/** 백엔드 구역 이름(kitchen / toilet / room …) → 화면 공간 */
function mapRoom(v: unknown): RoomId {
  switch (v) {
    case 'kitchen': return 'kitchen'
    case 'toilet': case 'bathroom': return 'bathroom'
    case 'room': case 'bedroom': return 'bedroom'
    default: return 'living'
  }
}

function mapLocation(v: unknown): Location {
  if (v === null || v === undefined || v === '') return 'unknown'
  if (v === 'outside') return 'outside'
  return mapRoom(v)
}

const BURNER_STATES: readonly BurnerState[] = ['off', 'on', 'overheated', 'cooling']
function mapBurner(v: unknown): Burner | null {
  if (!isObj(v)) return null
  const state = BURNER_STATES.includes(v.deviceState as BurnerState) ? (v.deviceState as BurnerState) : 'off'
  return {
    burnerId: str(v.burnerId, 'burner-1'), deviceState: state,
    level: Math.max(0, Math.min(9, num(v.level))), temperature: num(v.temperature, 25), activeSec: Math.max(0, num(v.activeSec)),
  }
}

const PUBLISHERS: readonly Publisher[] = ['user', 'system', 'api']
const mapPublisher = (v: unknown): Publisher | undefined =>
  isObj(v) && PUBLISHERS.includes(v.publisher as Publisher) ? (v.publisher as Publisher) : undefined

const ZONES: readonly Zone[] = ['kitchen', 'near', 'far', 'unknown']
function mapPresence(v: unknown): Presence | null {
  if (!isObj(v)) return null
  const room = mapRoom(v.room)
  if (room !== 'kitchen' && room !== 'bathroom') return null
  return {
    room, present: v.present === true,
    zone: ZONES.includes(v.zone as Zone) ? (v.zone as Zone) : 'unknown',
    absentSec: Math.max(0, num(v.absentSec)), confidence: Math.max(0, Math.min(1, num(v.confidence))),
    observedAt: str(v.observedAt, nowIso()),
  }
}

/** 아직 재실 판단 결과가 없을 때 쓰는 자리 (신뢰도 0) */
const unknownPresence = (room: 'kitchen' | 'bathroom'): Presence =>
  ({ room, present: false, zone: 'unknown', absentSec: 0, confidence: 0, observedAt: nowIso() })

const EVENT_TYPES: ReadonlySet<SafetyEventType> = new Set<SafetyEventType>([
  'cooking_started', 'absence_detected', 'auto_power_reduced', 'auto_power_off', 'overheat_detected',
  'command_blocked', 'overheat_cleared', 'user_returned', 'cooking_ended', 'fall_detected', 'fall_resolved',
  'fall_reported', 'fall_auto_reported', 'fall_escalated', 'ai_control', 'auto_dispense',
])
const SEVERITIES: readonly Severity[] = ['info', 'warning', 'danger']

function mapEvent(v: unknown): SafetyEvent | null {
  if (!isObj(v) || typeof v.eventId !== 'string' || typeof v.occurredAt !== 'string') return null
  if (!EVENT_TYPES.has(v.type as SafetyEventType)) return null
  const fb = isObj(v.feedback) && (v.feedback.verdict === 'approved' || v.feedback.verdict === 'rejected')
    ? { verdict: v.feedback.verdict, submittedAt: str(v.feedback.submittedAt, nowIso()) } as const
    : undefined
  return {
    eventId: v.eventId, type: v.type as SafetyEventType,
    severity: SEVERITIES.includes(v.severity as Severity) ? (v.severity as Severity) : 'info',
    occurredAt: v.occurredAt, room: mapRoom(v.room), sessionId: optStr(v.sessionId),
    temperature: optNum(v.temperature), trigger: optStr(v.trigger), action: optStr(v.action),
    reasoning: optStr(v.reasoning), guidance: optStr(v.guidance), feedback: fb,
  }
}

function mapSession(v: unknown): CookingSession | null {
  if (!isObj(v) || typeof v.sessionId !== 'string' || typeof v.startedAt !== 'string') return null
  return {
    sessionId: v.sessionId, startedAt: v.startedAt, endedAt: optStr(v.endedAt),
    status: v.status === 'active' ? 'active' : 'ended', peakTemperature: num(v.peakTemperature),
    timeline: arr(v.timeline).filter(isObj).map((t) => ({ at: str(t.at), type: str(t.type), summary: str(t.summary) })),
  }
}

const FALL_STATUSES: readonly FallStatus[] = ['pending', 'resolved', 'reported', 'auto_reported']
function mapFall(v: unknown): FallIncident | null {
  if (!isObj(v) || typeof v.incidentId !== 'string' || typeof v.detectedAt !== 'string') return null
  if (!FALL_STATUSES.includes(v.status as FallStatus)) return null
  return {
    incidentId: v.incidentId, room: mapRoom(v.room), status: v.status as FallStatus,
    detectedAt: v.detectedAt, confidence: num(v.confidence), confirmUrl: str(v.confirmUrl),
    autoReportAt: str(v.autoReportAt, v.detectedAt), eventId: optStr(v.eventId),
    resolvedAt: optStr(v.resolvedAt), reportedAt: optStr(v.reportedAt),
    guardianNotified: v.guardianNotified === true, burnerShutOff: v.shutoffSent === true,
  }
}

function mapContact(v: unknown): Contact | null {
  return isObj(v) && typeof v.name === 'string' && typeof v.phone === 'string' ? { name: v.name, phone: v.phone } : null
}

function mapPolicy(v: unknown): KitchenPolicy {
  const p = isObj(v) ? v : {}
  return {
    watchAfterSec: num(p.watchAfterSec, 60), reduceAfterSec: num(p.reduceAfterSec, 180), offAfterSec: num(p.offAfterSec, 600),
    reduceToLevel: num(p.reduceToLevel, 1), minConfidence: num(p.minConfidence, 0.7), nearZoneMultiplier: num(p.nearZoneMultiplier, 2),
    overheatEnterC: num(p.overheatEnterC, 150), overheatExitC: num(p.overheatExitC, 60), heartbeatTimeoutSec: num(p.heartbeatTimeoutSec, 15),
  }
}

/** 시간대별 예보 (백엔드 확장 예정 필드). 지금부터 12시간만, 형태가 맞는 항목만 쓴다 */
function mapHourly(v: unknown): HourlyWeather[] | undefined {
  const from = Date.now() - 60 * 60_000
  const items = arr(v).filter(isObj).flatMap((h): HourlyWeather[] => {
    const time = str(h.time ?? h.at)
    const t = new Date(time).getTime()
    if (!time || Number.isNaN(t) || t < from || typeof h.temperature !== 'number') return []
    return [{ time, temperature: h.temperature, code: num(h.weatherCode ?? h.code, -1), rainChance: optNum(h.precipitationProbability ?? h.rainChance) }]
  })
  return items.length > 0 ? items.slice(0, 12) : undefined
}

const ROOM_NAME: Record<RoomId, string> = { kitchen: '주방', bathroom: '욕실', bedroom: '침실', living: '거실' }

// ── 데이터 소스 ────────────────────────────────────────────────────────────
export function createHttpSource(base: string): DataSource {
  const root = base.replace(/\/+$/, '')
  const opts: RequestInit = { credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer' }

  /** 화면에 그대로 보여줘도 되는 오류 문장 (서버 응답 본문은 노출하지 않는다) */
  class ApiError extends Error {
    constructor(message: string, readonly status = 0) { super(message) }
  }

  async function request(path: string, init?: RequestInit): Promise<unknown> {
    let res: Response
    try {
      res = await fetch(`${root}${API}${path}`, { ...opts, ...init })
    } catch {
      throw new ApiError('서버에 연결하지 못했어요. 백엔드가 실행 중인지 확인해 주세요.')
    }
    if (!res.ok) {
      const message = res.status === 404 ? '찾을 수 없어요.'
        : res.status === 409 ? '지금 상태에서는 할 수 없는 동작이에요.'
        : res.status === 422 ? '입력값을 확인해 주세요.'
        : res.status >= 500 ? '서버에서 오류가 났어요. 잠시 후 다시 시도해 주세요.'
        : '요청을 처리하지 못했어요.'
      throw new ApiError(message, res.status)
    }
    return res.status === 204 ? null : res.json()
  }
  const get = (path: string) => request(path)
  /** 404 면 null (아직 등록·수신된 값이 없는 경우) */
  const getOrNull = (path: string) => request(path).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  })
  const send = (method: 'POST' | 'PUT', path: string, body: unknown) =>
    request(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

  // 화면 형식 기기 목록과 인덕션 온도 기록 (새로고침해도 그래프가 이어지도록 소스가 들고 있는다)
  let devices: Device[] = []
  const tempHistory = new Map<string, number[]>()
  let fallPolicyRaw: Obj = { userAlertWaitSec: 30, autoReportSec: 60 }

  function pushTemp(id: string, t: number) {
    const h = tempHistory.get(id) ?? []
    h.push(t)
    tempHistory.set(id, h.slice(-HISTORY_LEN))
  }

  /** GET /snapshot 의 devices(DeviceInfo[]) + appliances(화구 상세) → 화면 기기 */
  function buildDevices(snapshot: Obj): Device[] {
    const appliances = arr(snapshot.appliances).filter(isObj)
    return arr(snapshot.devices).filter(isObj).flatMap((info): Device[] => {
      const id = str(info.deviceId)
      if (!id) return []
      const room = mapRoom(info.room)
      const online = info.online === true
      const auto = info.control_state === 'homevis'
      const cur = isObj(info.current_state) ? info.current_state : {}
      if (info.device === 'stove') {
        const ap = appliances.find((a) => a.deviceId === id)
        const burner = mapBurner(arr(ap?.burners)[0]) ?? {
          burnerId: 'burner-1', deviceState: BURNER_STATES.includes(cur.state as BurnerState) ? (cur.state as BurnerState) : 'off',
          level: num(cur.level), temperature: num(cur.temperature, 25), activeSec: 0,
        }
        if (!tempHistory.has(id)) pushTemp(id, burner.temperature)
        const d: InductionDevice = {
          id, kind: 'induction', name: '인덕션', room, online, burner,
          lastControl: mapPublisher(ap?.lastControl) ?? (auto ? 'system' : 'user'), alarm: false,
          tempHistory: [...(tempHistory.get(id) ?? [burner.temperature])],
        }
        return [d]
      }
      if (info.device === 'light') {
        const d: LightDevice = {
          id, kind: 'light', name: `${ROOM_NAME[room]} 조명`, room, online,
          on: info.is_on === true, brightness: 100, auto, dimmable: false,
        }
        return [d]
      }
      if (info.device === 'water_purifier') {
        const ml = optNum(cur.lastDispensedMl)
        const d: PurifierDevice = {
          id, kind: 'purifier', name: '정수기', room, online, dispensing: info.is_on === true,
          lastDispense: ml ? { at: str(info.updatedAt, nowIso()), ml, auto } : null,
          autoDispensedToday: false,
        }
        return [d]
      }
      return []
    })
  }

  async function loadSnapshot(): Promise<Snapshot> {
    const [snap, evRes, user, guardian, policy, fallPolicy, sensing] = await Promise.all([
      get('/snapshot'),
      get('/safety-events?page=1&size=200'),
      getOrNull('/user'),
      getOrNull('/guardian'),
      get('/policies/kitchen-absence'),
      get('/policies/fall-safety'),
      getOrNull('/sensing/results/latest'),
    ])
    if (!isObj(snap)) throw new ApiError('서버 응답 형식이 올바르지 않아요.')

    devices = buildDevices(snap)
    // 서버는 오래된 것부터 준다 → 화면은 최신이 위
    const events = arr(isObj(evRes) ? evRes.items : []).map(mapEvent).filter((e): e is SafetyEvent => e !== null).reverse()

    const session = mapSession(snap.session)
    const ids = [...new Set(events.map((e) => e.sessionId).filter((s): s is string => !!s && s !== session?.sessionId))]
      .slice(0, SESSION_FETCH_LIMIT)
    const fetched = await Promise.allSettled(ids.map((id) => get(`/sessions/${encodeURIComponent(id)}`)))
    const sessions = [session, ...fetched.map((r) => (r.status === 'fulfilled' ? mapSession(r.value) : null))]
      .filter((s): s is CookingSession => s !== null)

    const rooms = isObj(snap.rooms) ? snap.rooms : {}
    const presenceOf = (key: string) => mapPresence(isObj(rooms[key]) ? (rooms[key] as Obj).presence : null)
    const kitchen = presenceOf('kitchen') ?? unknownPresence('kitchen')
    const bathroom = presenceOf('toilet') ?? presenceOf('bathroom') ?? unknownPresence('bathroom')

    let location: Location = isObj(sensing) ? mapLocation(sensing.room) : 'unknown'
    if (location === 'unknown' && kitchen.present) location = 'kitchen'

    if (isObj(fallPolicy)) fallPolicyRaw = fallPolicy

    return {
      devices, presence: { kitchen, bathroom }, location, session, sessions, events,
      // 진행 중인 낙상 사건 목록 API 가 없어 처음엔 비워 두고, WebSocket fall.incident 로 받는다
      fall: null,
      contacts: { user: mapContact(user), guardian: mapContact(guardian) },
      policy: mapPolicy(policy),
      fallPolicy: { autoReportSec: num(isObj(fallPolicy) ? fallPolicy.autoReportSec : undefined, 60) },
    }
  }

  // ── 실시간 ──────────────────────────────────────────────────────────────
  function streamUrl(lastEventId: string | null): string {
    const origin = root || window.location.origin
    const u = new URL(`${API}/stream`, origin)
    u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
    if (lastEventId) u.searchParams.set('since', lastEventId)
    return u.toString()
  }

  /** 서버 봉투 { event, at, data } → 화면 메시지 (모르는 이벤트는 무시) */
  function translate(event: string, at: string, data: Obj): StreamMessage[] {
    switch (event) {
      case 'burner.telemetry': {
        const burners = arr(data.burners).map(mapBurner).filter((b): b is Burner => b !== null)
        const id = str(data.deviceId)
        if (!id || burners.length === 0) return []
        pushTemp(id, burners[0]!.temperature)
        return [{ event: 'burner.telemetry', data: { deviceId: id, reportedAt: str(data.reportedAt, at), burners } }]
      }
      case 'presence.updated': {
        const p = mapPresence(data)
        return p ? [{ event: 'presence.updated', data: p }] : []
      }
      case 'safety.event': {
        const e = mapEvent(data)
        return e ? [{ event: 'safety.event', data: e }] : []
      }
      case 'session.updated': {
        const s = mapSession(data)
        return s ? [{ event: 'session.updated', data: s }] : []
      }
      case 'fall.incident': {
        const f = mapFall(data)
        return f ? [{ event: 'fall.incident', data: f }] : []
      }
      case 'device.state': {
        const d = devices.find((x) => x.id === data.deviceId)
        const st = isObj(data.state) ? data.state : null
        if (!d || !st) return []
        let next: Device | null = null
        if (d.kind === 'light') next = { ...d, online: true, on: st.power === 'on' }
        if (d.kind === 'purifier') {
          const ml = optNum(st.lastDispensedMl)
          next = { ...d, online: true, dispensing: st.status === 'dispensing',
            lastDispense: ml ? { at: str(st.reportedAt, at), ml, auto: d.lastDispense?.auto ?? false } : d.lastDispense }
        }
        if (!next) return []
        devices = devices.map((x) => (x.id === next.id ? next : x))
        return [{ event: 'device.updated', data: next }]
      }
      case 'sensing.result':
        return [{ event: 'location.updated', data: { location: mapLocation(data.room), observedAt: str(data.observedAt, at) } }]
      case 'ai.announcement':
      case 'weather.briefing': {
        const text = str(data.text).trim()
        if (!text) return []
        return [{ event: 'announcement', data: { id: `${event}:${str(data.decisionId, at)}`, text: text.slice(0, 500), at } }]
      }
      default:
        return []
    }
  }

  function subscribe(listener: (m: StreamMessage) => void): () => void {
    let ws: WebSocket | null = null
    let closed = false
    let retry = 1000
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let lastEventId: string | null = null

    const connect = () => {
      if (closed) return
      ws = new WebSocket(streamUrl(lastEventId))
      ws.onopen = () => { retry = 1000 }
      ws.onmessage = (ev) => {
        if (typeof ev.data !== 'string' || ev.data.length > 1_000_000) return
        let env: unknown
        try { env = JSON.parse(ev.data) } catch { return }
        if (!isObj(env) || typeof env.event !== 'string' || !isObj(env.data)) return
        if (env.event === 'safety.event' && typeof env.data.eventId === 'string') lastEventId = env.data.eventId
        for (const m of translate(env.event, str(env.at, nowIso()), env.data)) listener(m)
      }
      ws.onclose = () => {
        ws = null
        if (closed) return
        retryTimer = setTimeout(connect, retry)
        retry = Math.min(retry * 2, 10_000)
      }
      ws.onerror = () => ws?.close()
    }
    connect()

    // 서버가 판정한 온라인 상태가 바뀐 기기만 알린다 (telemetry 가 끊긴 기기 감지)
    const poll = setInterval(async () => {
      try {
        const res = await get('/devices')
        for (const info of arr(isObj(res) ? res.items : []).filter(isObj)) {
          const d = devices.find((x) => x.id === info.deviceId)
          if (!d || d.online === (info.online === true)) continue
          devices = devices.map((x) => (x.id === d.id ? { ...x, online: info.online === true } : x))
          listener({ event: 'connection.changed', data: { deviceId: d.id, online: info.online === true } })
        }
      } catch { /* 다음 주기에 다시 */ }
    }, DEVICE_POLL_MS)

    return () => {
      closed = true
      if (retryTimer) clearTimeout(retryTimer)
      clearInterval(poll)
      ws?.close()
    }
  }

  // ── 동작 ────────────────────────────────────────────────────────────────
  async function controlDevice(deviceId: string, control: DeviceControl): Promise<void> {
    const d = devices.find((x) => x.id === deviceId)
    if (!d) throw new ApiError('등록되지 않은 기기예요.')
    if (d.kind !== 'light') throw new ApiError('이 기기는 화면에서 제어할 수 없어요.')
    if (control.on === undefined) throw new ApiError('전등은 켜기·끄기만 할 수 있어요.')
    await send('POST', `/devices/${encodeURIComponent(deviceId)}/commands`, { type: control.on ? 'on' : 'off' })
    // 실제 상태는 기기 응답(device.state)이 오면 바뀐다
  }

  async function submitFeedback(eventId: string, verdict: 'approved' | 'rejected') {
    const r = await send('POST', `/safety-events/${encodeURIComponent(eventId)}/feedback`, { verdict })
    return { verdict, submittedAt: str(isObj(r) ? r.submittedAt : undefined, nowIso()) }
  }

  async function saveContact(kind: 'user' | 'guardian', contact: Contact): Promise<ContactSaveResult> {
    const r = await send('PUT', `/${kind}`, { name: contact.name, phone: contact.phone })
    const saved = mapContact(isObj(r) ? r[kind] : null) ?? contact
    const sent = isObj(r) && r.verificationSent === true
    return {
      contact: saved, verificationSent: sent,
      message: sent ? '저장했어요. 확인 문자를 보냈어요.' : '저장했어요. (확인 문자는 보내지 않았어요)',
    }
  }

  async function savePolicy(policy: KitchenPolicy): Promise<KitchenPolicy> {
    return mapPolicy(await send('PUT', '/policies/kitchen-absence', policy))
  }

  async function saveFallPolicy(policy: FallPolicy): Promise<FallPolicy> {
    // 화면에 없는 userAlertWaitSec 등은 서버 값을 그대로 유지한다
    const r = await send('PUT', '/policies/fall-safety', { ...fallPolicyRaw, autoReportSec: policy.autoReportSec })
    if (isObj(r)) fallPolicyRaw = r
    return { autoReportSec: num(isObj(r) ? r.autoReportSec : undefined, policy.autoReportSec) }
  }

  async function loadWeather(): Promise<Weather | null> {
    const r = await get('/weather')
    if (!isObj(r) || r.available !== true || !isObj(r.weather)) return null
    const w = r.weather
    if (typeof w.temperature !== 'number') return null
    return {
      location: str(w.location, ''), temperature: w.temperature, condition: str(w.condition, ''),
      code: num(w.weatherCode, -1), max: optNum(w.tempMax), min: optNum(w.tempMin),
      feels: optNum(w.apparentTemperature), humidity: optNum(w.humidity), rainChance: optNum(w.precipitationProbability),
      fetchedAt: optStr(w.fetchedAt) ?? optStr(r.basedOn),
      hourly: mapHourly(w.hourly ?? r.hourly),
      stale: r.stale === true, text: str(r.text).slice(0, 300),
    }
  }

  return { kind: 'http', loadSnapshot, subscribe, controlDevice, submitFeedback, saveContact, savePolicy, saveFallPolicy, loadWeather, demo: null }
}
