import type {
  Appliance, ConnectionIssue, Environment, Presence, PowerState,
  RoomId, SafetyIncident, SafetyLog, TimelineEvent,
} from '@/types'

export interface HomeSnapshot {
  appliances: Appliance[]
  presence: Record<RoomId, Presence>
  environment: Record<RoomId, Environment>
  roomEvents: Record<RoomId, TimelineEvent[]>
  safetyLogs: SafetyLog[]
  connectionIssue: ConnectionIssue | null
}

/** 실시간 갱신 패치. 소스가 데이터의 주인이고 UI 는 받아서 반영만 한다. */
export type RealtimePatch =
  | { kind: 'environment'; room: RoomId; environment: Environment }
  | { kind: 'presence'; room: RoomId; presence: Presence }

/**
 * 데이터 소스 경계.
 *
 * 현재는 mockSource 만 구현되어 있다.
 * 실제 백엔드가 준비되면 httpSource 만 채우면 되고, UI 코드는 한 줄도 바뀌지 않는다.
 */
export interface SafetyDataSource {
  readonly kind: 'mock' | 'http'
  loadSnapshot(): Promise<HomeSnapshot>
  setPower(applianceId: string, power: PowerState): Promise<void>
  subscribe(listener: (patch: RealtimePatch) => void): () => void
  /** 데모용 위험 상황 트리거. 실제 소스에서는 서버 이벤트로 대체된다. */
  createIncident(room: RoomId): SafetyIncident | null
}
