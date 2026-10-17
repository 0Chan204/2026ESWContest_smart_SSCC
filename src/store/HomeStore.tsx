import {
  createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode,
} from 'react'
import { toast } from 'sonner'
import { createDataSource, type DataSource, type DeviceControl, type Snapshot, type StreamMessage } from '@/data/source'
import { maxRisk, phaseRisk } from '@/lib/labels'
import type {
  Contact, CookingSession, Device, FallIncident, FallPolicy, InductionDevice, KitchenPhase,
  KitchenPolicy, Location, Presence, Risk, SafetyEvent, Weather,
} from '@/types'

type AbsenceStage = 'none' | 'watch' | 'reduce' | 'off'

interface HomeState {
  ready: boolean
  devices: Device[]
  presence: { kitchen: Presence; bathroom: Presence }
  location: Location
  activeSessionId: string | null
  sessions: Record<string, CookingSession>
  events: SafetyEvent[]
  fall: FallIncident | null
  contacts: { user: Contact | null; guardian: Contact | null }
  policy: KitchenPolicy
  fallPolicy: FallPolicy
  absenceStage: AbsenceStage
  /** 방금 시스템이 수행한 안전 조치 (결과 안내 시트) */
  notice: SafetyEvent | null
  fallAlertOpen: boolean
  /** AI 판정 엔진의 최근 안내 문장 (화면 표시 + 음성) */
  announcement: { id: string; text: string; at: string } | null
  /** 처음 불러오기 실패 (백엔드가 꺼져 있는 등) */
  loadError: string | null
}

type Action =
  | { type: 'init'; snapshot: Snapshot }
  | { type: 'loadError'; message: string | null }
  | { type: 'message'; message: StreamMessage }
  | { type: 'dismissNotice' }
  | { type: 'setFallAlert'; open: boolean }
  | { type: 'feedback'; eventId: string; feedback: SafetyEvent['feedback'] }
  | { type: 'contact'; kind: 'user' | 'guardian'; contact: Contact }
  | { type: 'policy'; policy: KitchenPolicy }
  | { type: 'fallPolicy'; policy: FallPolicy }

const NOTICE_TYPES = new Set(['auto_power_reduced', 'auto_power_off', 'overheat_detected'])

function stageAfter(event: SafetyEvent, current: AbsenceStage): AbsenceStage {
  switch (event.type) {
    case 'absence_detected': return 'watch'
    case 'auto_power_reduced': return 'reduce'
    case 'auto_power_off': return 'off'
    case 'user_returned':
    case 'cooking_ended': return 'none'
    default: return current
  }
}

function reduceMessage(state: HomeState, m: StreamMessage): HomeState {
  switch (m.event) {
    case 'burner.telemetry':
      return {
        ...state,
        devices: state.devices.map((d) => {
          if (d.id !== m.data.deviceId || d.kind !== 'induction') return d
          const burner = m.data.burners[0] ?? d.burner
          return {
            ...d, burner, online: true,
            lastControl: m.data.lastControl ?? d.lastControl,
            alarm: m.data.alarm ?? d.alarm,
            tempHistory: [...d.tempHistory, burner.temperature].slice(-60),
          }
        }),
      }
    case 'presence.updated':
      return {
        ...state,
        presence: { ...state.presence, [m.data.room]: m.data },
        absenceStage: m.data.room === 'kitchen' && m.data.present ? 'none' : state.absenceStage,
      }
    case 'safety.event': {
      const e = m.data
      return {
        ...state,
        events: [e, ...state.events.filter((x) => x.eventId !== e.eventId)],
        absenceStage: e.room === 'kitchen' ? stageAfter(e, state.absenceStage) : state.absenceStage,
        notice: NOTICE_TYPES.has(e.type) ? e : state.notice,
      }
    }
    case 'session.updated': {
      const s = m.data
      return {
        ...state,
        sessions: { ...state.sessions, [s.sessionId]: s },
        activeSessionId: s.status === 'active' ? s.sessionId
          : state.activeSessionId === s.sessionId ? null : state.activeSessionId,
      }
    }
    case 'fall.incident':
      return {
        ...state, fall: m.data,
        fallAlertOpen: m.data.status === 'pending' ? true : state.fallAlertOpen,
      }
    case 'connection.changed':
      return { ...state, devices: state.devices.map((d) => (d.id === m.data.deviceId ? { ...d, online: m.data.online } : d)) }
    case 'device.updated':
      return { ...state, devices: state.devices.map((d) => (d.id === m.data.id ? m.data : d)) }
    case 'location.updated':
      return { ...state, location: m.data.location }
    case 'announcement':
      return { ...state, announcement: m.data }
  }
}

function reducer(state: HomeState, a: Action): HomeState {
  switch (a.type) {
    case 'init': {
      const s = a.snapshot
      return {
        ...state, ready: true, loadError: null, devices: s.devices, presence: s.presence, location: s.location,
        activeSessionId: s.session?.sessionId ?? null,
        sessions: Object.fromEntries(s.sessions.map((x) => [x.sessionId, x])),
        events: s.events, fall: s.fall, contacts: s.contacts, policy: s.policy, fallPolicy: s.fallPolicy,
      }
    }
    case 'loadError': return { ...state, loadError: a.message }
    case 'message': return reduceMessage(state, a.message)
    case 'dismissNotice': return { ...state, notice: null }
    case 'setFallAlert': return { ...state, fallAlertOpen: a.open }
    case 'feedback':
      return { ...state, events: state.events.map((e) => (e.eventId === a.eventId ? { ...e, feedback: a.feedback } : e)) }
    case 'contact': return { ...state, contacts: { ...state.contacts, [a.kind]: a.contact } }
    case 'policy': return { ...state, policy: a.policy }
    case 'fallPolicy': return { ...state, fallPolicy: a.policy }
  }
}

const initial: HomeState = {
  ready: false, devices: [],
  presence: {} as HomeState['presence'],
  location: 'unknown', activeSessionId: null, sessions: {}, events: [], fall: null,
  contacts: { user: null, guardian: null },
  policy: {} as KitchenPolicy, fallPolicy: { autoReportSec: 60 },
  absenceStage: 'none', notice: null, fallAlertOpen: false, announcement: null, loadError: null,
}

interface HomeValue extends HomeState {
  source: DataSource
  induction: InductionDevice | undefined
  session: CookingSession | null
  kitchenPhase: KitchenPhase
  kitchenRisk: Risk
  bathroomRisk: Risk
  overallRisk: Risk
  onlineCount: number
  controlDevice: (id: string, control: DeviceControl) => Promise<void>
  submitFeedback: (eventId: string, verdict: 'approved' | 'rejected') => Promise<void>
  saveContact: (kind: 'user' | 'guardian', contact: Contact) => Promise<string>
  savePolicy: (p: KitchenPolicy) => Promise<void>
  saveFallPolicy: (p: FallPolicy) => Promise<void>
  dismissNotice: () => void
  setFallAlert: (open: boolean) => void
  /** 기기 상태를 서버에서 다시 받아온다 (플랫폼 샘플의 '검색' 버튼에 해당) */
  refresh: () => Promise<void>
  /** 끊긴 기기 다시 연결 시도. 시연 모드에서는 연결 복구를 흉내 낸다 */
  reconnect: (deviceId: string) => Promise<boolean>
  /** 마지막으로 상태를 확인한 시각 (ISO) */
  checkedAt: string | null
  /** 처음 불러오기를 다시 시도 */
  retryLoad: () => void
  /** 시계 옆 날씨 (없으면 null) */
  weather: Weather | null
}

const HomeContext = createContext<HomeValue | null>(null)

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

export function HomeStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial)
  const sourceRef = useRef<DataSource>(createDataSource())
  const [checkedAt, setCheckedAt] = useState<string | null>(null)

  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const source = sourceRef.current
    let alive = true
    dispatch({ type: 'loadError', message: null })
    source.loadSnapshot().then((snapshot) => {
      if (!alive) return
      dispatch({ type: 'init', snapshot })
      setCheckedAt(new Date().toISOString())
    }).catch((e: unknown) => {
      if (alive) dispatch({ type: 'loadError', message: e instanceof Error ? e.message : '서버에 연결하지 못했어요.' })
    })
    const off = source.subscribe((message) => dispatch({ type: 'message', message }))
    return () => { alive = false; off() }
  }, [attempt])
  const retryLoad = useCallback(() => setAttempt((n) => n + 1), [])

  // 날씨: 10분마다 다시 받는다 (서버가 30분마다 갱신해 두므로 자주 부를 필요 없음)
  const [weather, setWeather] = useState<Weather | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => sourceRef.current.loadWeather().then((w) => { if (alive) setWeather(w) }).catch(() => { /* 날씨는 없어도 된다 */ })
    load()
    const t = setInterval(load, 10 * 60_000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const controlDevice = useCallback(async (id: string, control: DeviceControl) => {
    try { await sourceRef.current.controlDevice(id, control) }
    catch (e) { toast.error(e instanceof Error ? e.message : '기기를 제어하지 못했어요.') }
  }, [])

  const submitFeedback = useCallback(async (eventId: string, verdict: 'approved' | 'rejected') => {
    const feedback = await sourceRef.current.submitFeedback(eventId, verdict)
    dispatch({ type: 'feedback', eventId, feedback })
  }, [])

  const saveContact = useCallback(async (kind: 'user' | 'guardian', contact: Contact) => {
    const r = await sourceRef.current.saveContact(kind, contact)
    dispatch({ type: 'contact', kind, contact: r.contact })
    return r.message
  }, [])

  const savePolicy = useCallback(async (p: KitchenPolicy) => {
    dispatch({ type: 'policy', policy: await sourceRef.current.savePolicy(p) })
  }, [])

  const saveFallPolicy = useCallback(async (p: FallPolicy) => {
    dispatch({ type: 'fallPolicy', policy: await sourceRef.current.saveFallPolicy(p) })
  }, [])

  const refresh = useCallback(async () => {
    // 너무 빨리 끝나면 눌렀는지 알 수 없으므로 최소 표시 시간을 둔다
    try {
      const [snapshot] = await Promise.all([sourceRef.current.loadSnapshot(), wait(900)])
      dispatch({ type: 'init', snapshot })
      setCheckedAt(new Date().toISOString())
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '서버에 연결하지 못했어요.')
    }
  }, [])

  const reconnect = useCallback(async (deviceId: string) => {
    const source = sourceRef.current
    await wait(1400)
    if (source.demo) {
      source.demo.toggleOffline(deviceId)
      return true
    }
    // 실제 연결은 기기·게이트웨이가 다시 붙어야 하므로, 여기서는 상태를 다시 확인만 한다
    try {
      const snapshot = await source.loadSnapshot()
      dispatch({ type: 'init', snapshot })
      setCheckedAt(new Date().toISOString())
      return snapshot.devices.find((d) => d.id === deviceId)?.online ?? false
    } catch {
      return false
    }
  }, [])

  const dismissNotice = useCallback(() => dispatch({ type: 'dismissNotice' }), [])
  const setFallAlert = useCallback((open: boolean) => dispatch({ type: 'setFallAlert', open }), [])

  const value = useMemo<HomeValue>(() => {
    const induction = state.devices.find((d): d is InductionDevice => d.kind === 'induction')
    const overheated = induction?.burner.deviceState === 'overheated'
    const kitchenPhase: KitchenPhase = overheated ? 'overheat'
      : state.absenceStage === 'off' ? 'auto_off'
        : state.absenceStage === 'reduce' ? 'auto_reduced'
          : state.absenceStage === 'watch' ? 'absence_watch' : 'normal'
    const kitchenRisk = maxRisk(phaseRisk(kitchenPhase), induction && !induction.online ? 'uncertain' : 'normal')
    const bathroomRisk: Risk = state.fall?.status === 'pending' ? 'danger' : 'normal'
    return {
      ...state, source: sourceRef.current, induction,
      session: state.activeSessionId ? state.sessions[state.activeSessionId] ?? null : null,
      kitchenPhase, kitchenRisk, bathroomRisk, overallRisk: maxRisk(kitchenRisk, bathroomRisk),
      onlineCount: state.devices.filter((d) => d.online).length,
      controlDevice, submitFeedback, saveContact, savePolicy, saveFallPolicy, dismissNotice, setFallAlert,
      refresh, reconnect, checkedAt, retryLoad, weather,
    }
  }, [state, controlDevice, submitFeedback, saveContact, savePolicy, saveFallPolicy, dismissNotice, setFallAlert,
    refresh, reconnect, checkedAt, retryLoad, weather])

  return <HomeContext.Provider value={value}>{children}</HomeContext.Provider>
}

export function useHome(): HomeValue {
  const ctx = useContext(HomeContext)
  if (!ctx) throw new Error('useHome 은 HomeStoreProvider 안에서만 사용할 수 있습니다.')
  return ctx
}
