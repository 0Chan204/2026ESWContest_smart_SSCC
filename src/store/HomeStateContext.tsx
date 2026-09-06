import {
  createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef,
  type ReactNode,
} from 'react'
import { toast } from 'sonner'
import { createDataSource } from '@/data/source'
import type { RealtimePatch } from '@/data/source'
import type {
  Appliance, ConnectionIssue, Environment, PowerState, Presence,
  RoomId, SafetyIncident, SafetyLog, TimelineEvent,
} from '@/types'
import { formatClock } from '@/lib/format'
import { withObjectParticle } from '@/lib/korean'

interface HomeState {
  ready: boolean
  appliances: Appliance[]
  presence: Record<RoomId, Presence>
  environment: Record<RoomId, Environment>
  roomEvents: Record<RoomId, TimelineEvent[]>
  safetyLogs: SafetyLog[]
  connectionIssue: ConnectionIssue | null
  /** 진행 중인 위험 상황 (Warning 모달) */
  activeIncident: SafetyIncident | null
  /** 방금 완료된 안전 조치 (Result 모달) */
  lastResult: SafetyLog | null
}

type Action =
  | { type: 'init'; payload: Omit<HomeState, 'ready' | 'activeIncident' | 'lastResult'> }
  | { type: 'patch'; patch: RealtimePatch }
  | { type: 'setPower'; applianceId: string; power: PowerState; time: string }
  | { type: 'startIncident'; incident: SafetyIncident }
  | { type: 'resolveIncident'; log: SafetyLog; time: string }
  | { type: 'cancelIncident'; log: SafetyLog }
  | { type: 'clearResult' }
  | { type: 'dismissConnectionIssue' }

const EMPTY_ROOMS = { kitchen: [], bathroom: [] } as Record<RoomId, TimelineEvent[]>

const initialState: HomeState = {
  ready: false,
  appliances: [],
  presence: {} as Record<RoomId, Presence>,
  environment: {} as Record<RoomId, Environment>,
  roomEvents: EMPTY_ROOMS,
  safetyLogs: [],
  connectionIssue: null,
  activeIncident: null,
  lastResult: null,
}

function reducer(state: HomeState, action: Action): HomeState {
  switch (action.type) {
    case 'init':
      return { ...state, ...action.payload, ready: true }

    case 'patch': {
      const { patch } = action
      if (patch.kind === 'environment') {
        return {
          ...state,
          environment: { ...state.environment, [patch.room]: patch.environment },
        }
      }
      return { ...state, presence: { ...state.presence, [patch.room]: patch.presence } }
    }

    case 'setPower':
      return {
        ...state,
        appliances: state.appliances.map((a) =>
          a.id !== action.applianceId
            ? a
            : {
                ...a,
                power: action.power,
                lastUpdate: '방금 전',
                history: [
                  {
                    time: action.time,
                    kind: 'normal' as const,
                    text: action.power === 'ON' ? '전원 ON' : '전원 OFF',
                  },
                  ...a.history,
                ].slice(0, 5),
              },
        ),
      }

    case 'startIncident':
      return {
        ...state,
        activeIncident: action.incident,
        // 위험 상황이 진행 중인 기기는 warning 으로 표시해 홈/공간 화면에서도 바로 보이게 한다.
        appliances: state.appliances.map((a) =>
          a.id === action.incident.action.applianceId ? { ...a, status: 'warning' } : a,
        ),
      }

    case 'resolveIncident': {
      const incident = state.activeIncident
      if (!incident) return state
      return {
        ...state,
        activeIncident: null,
        lastResult: action.log,
        // 안전 조치를 실제 기기 상태에 반영한다.
        appliances: state.appliances.map((a) =>
          a.id !== incident.action.applianceId
            ? a
            : {
                ...a,
                status: 'normal',
                detail: incident.action.nextDetail,
                lastUpdate: '방금 전',
                history: [
                  { time: action.time, kind: 'warning' as const, text: incident.action.deviceHistoryText },
                  ...a.history,
                ].slice(0, 5),
              },
        ),
        // 처리 이력에 자동 기록한다.
        safetyLogs: [action.log, ...state.safetyLogs],
      }
    }

    case 'cancelIncident': {
      const applianceId = state.activeIncident?.action.applianceId
      return {
        ...state,
        activeIncident: null,
        appliances: state.appliances.map((a) =>
          a.id === applianceId ? { ...a, status: 'normal' } : a,
        ),
        safetyLogs: [action.log, ...state.safetyLogs],
      }
    }

    case 'clearResult':
      return { ...state, lastResult: null }

    case 'dismissConnectionIssue':
      return { ...state, connectionIssue: null }

    default:
      return state
  }
}

interface HomeStateValue extends HomeState {
  applianceById: (id: string) => Appliance | undefined
  setPower: (applianceId: string, power: PowerState) => void
  triggerIncident: (room: RoomId) => void
  resolveIncident: () => void
  cancelIncident: () => void
  clearResult: () => void
  dismissConnectionIssue: () => void
  /** 확인이 필요한 알림 건수 */
  alertCount: number
  /** 정상 연결된 기기 수 */
  onlineCount: number
}

const HomeStateContext = createContext<HomeStateValue | null>(null)

function nowIso(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function HomeStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const sourceRef = useRef(createDataSource())

  useEffect(() => {
    const source = sourceRef.current
    let alive = true

    source.loadSnapshot().then((snapshot) => {
      if (!alive) return
      dispatch({ type: 'init', payload: snapshot })
    })

    const unsubscribe = source.subscribe((patch) => dispatch({ type: 'patch', patch }))
    return () => {
      alive = false
      unsubscribe()
    }
  }, [])

  const applianceById = useCallback(
    (id: string) => state.appliances.find((a) => a.id === id),
    [state.appliances],
  )

  const setPower = useCallback(
    (applianceId: string, power: PowerState) => {
      const appliance = sourceRefCurrentAppliance(state.appliances, applianceId)
      // 제어를 지원하지 않는 기기는 어떤 경로(버튼/음성)로도 상태를 바꿀 수 없다.
      if (!appliance || !appliance.supportsControl) return
      void sourceRef.current.setPower(applianceId, power)
      dispatch({ type: 'setPower', applianceId, power, time: formatClock(new Date()) })
      const roomLabel = appliance.room === 'kitchen' ? '주방' : '화장실'
      toast.success(
        `${roomLabel} ${withObjectParticle(appliance.name)} ${power === 'ON' ? '켰습니다.' : '껐습니다.'}`,
      )
    },
    [state.appliances],
  )

  const triggerIncident = useCallback((room: RoomId) => {
    const incident = sourceRef.current.createIncident(room)
    if (incident) dispatch({ type: 'startIncident', incident })
  }, [])

  const resolveIncident = useCallback(() => {
    const incident = state.activeIncident
    if (!incident) return
    const log: SafetyLog = {
      id: `log-${incident.id}`,
      datetime: nowIso(),
      room: incident.room,
      content: incident.action.logContent,
      result: 'success',
      reasoning: incident.reasoning,
      relatedDevices: incident.relatedDevices,
      confidence: incident.confidence,
    }
    dispatch({ type: 'resolveIncident', log, time: formatClock(new Date()) })
  }, [state.activeIncident])

  const cancelIncident = useCallback(() => {
    const incident = state.activeIncident
    if (!incident) return
    // 사용자가 직접 처리한 것도 감사 로그로 남긴다.
    const log: SafetyLog = {
      id: `log-${incident.id}-canceled`,
      datetime: nowIso(),
      room: incident.room,
      content: `${incident.title} · 사용자가 직접 처리를 선택함`,
      result: 'canceled',
      reasoning: incident.reasoning,
      relatedDevices: incident.relatedDevices,
      confidence: incident.confidence,
    }
    dispatch({ type: 'cancelIncident', log })
  }, [state.activeIncident])

  const clearResult = useCallback(() => dispatch({ type: 'clearResult' }), [])
  const dismissConnectionIssue = useCallback(
    () => dispatch({ type: 'dismissConnectionIssue' }),
    [],
  )

  const alertCount = useMemo(
    () => state.appliances.filter((a) => a.status === 'warning' || a.status === 'danger').length,
    [state.appliances],
  )

  const onlineCount = useMemo(
    () => state.appliances.filter((a) => a.status !== 'offline').length,
    [state.appliances],
  )

  const value = useMemo<HomeStateValue>(
    () => ({
      ...state,
      applianceById,
      setPower,
      triggerIncident,
      resolveIncident,
      cancelIncident,
      clearResult,
      dismissConnectionIssue,
      alertCount,
      onlineCount,
    }),
    [
      state, applianceById, setPower, triggerIncident, resolveIncident,
      cancelIncident, clearResult, dismissConnectionIssue, alertCount, onlineCount,
    ],
  )

  return <HomeStateContext.Provider value={value}>{children}</HomeStateContext.Provider>
}

function sourceRefCurrentAppliance(list: Appliance[], id: string): Appliance | undefined {
  return list.find((a) => a.id === id)
}

export function useHomeState(): HomeStateValue {
  const ctx = useContext(HomeStateContext)
  if (!ctx) throw new Error('useHomeState 는 HomeStateProvider 안에서만 사용할 수 있습니다.')
  return ctx
}
