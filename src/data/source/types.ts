import type {
  Burner, Contact, ContactSaveResult, CookingSession, Device, FallIncident, FallPolicy,
  KitchenPolicy, Location, Presence, Publisher, SafetyEvent,
} from '@/types'

export interface Snapshot {
  devices: Device[]
  presence: { kitchen: Presence; bathroom: Presence }
  location: Location
  session: CookingSession | null
  sessions: CookingSession[]
  events: SafetyEvent[]
  fall: FallIncident | null
  contacts: { user: Contact | null; guardian: Contact | null }
  policy: KitchenPolicy
  fallPolicy: FallPolicy
}

/**
 * 실시간 메시지. 이벤트 이름과 data 형태는 백엔드 WebSocket(/api/v1/stream)의
 * { event, at, data } 봉투를 그대로 따른다.
 * "(FE 확장)" 표시는 백엔드가 아직 보내지 않아 프론트가 먼저 정의한 이벤트다.
 */
export type StreamMessage =
  | {
      event: 'burner.telemetry'
      data: {
        deviceId: string
        reportedAt: string
        burners: Burner[]
        /** (FE 확장) BE telemetry 원본에는 있으나 WS 페이로드에는 아직 없음 */
        lastControl?: Publisher
        alarm?: boolean
      }
    }
  | { event: 'presence.updated'; data: Presence }
  | { event: 'safety.event'; data: SafetyEvent }
  | { event: 'session.updated'; data: CookingSession }
  | { event: 'fall.incident'; data: FallIncident }
  /** (FE 확장) 기기 온라인 상태 변경 */
  | { event: 'connection.changed'; data: { deviceId: string; online: boolean } }
  /** (FE 확장) 정수기·환풍기·욕실 조명 상태 */
  | { event: 'device.updated'; data: Device }
  /** (FE 확장) 중앙제어가 판단한 사용자 위치 */
  | { event: 'location.updated'; data: { location: Location; observedAt: string } }

export interface DeviceControl {
  on?: boolean
  speed?: 1 | 2 | 3
  brightness?: number
}

/** 시연 전용 조작. 실제 서버 소스에서는 null */
export interface DemoControls {
  leaveKitchen(zone: 'near' | 'far'): void
  returnKitchen(): void
  overheat(): void
  fall(): void
  morningDispense(): void
  toggleOffline(deviceId: string): void
}

/**
 * 데이터 소스 경계. 화면은 이 인터페이스만 안다.
 * mockSource(현재) → httpSource(백엔드 연동) 교체 시 화면 코드는 바뀌지 않는다.
 */
export interface DataSource {
  readonly kind: 'mock' | 'http'
  loadSnapshot(): Promise<Snapshot>
  subscribe(listener: (message: StreamMessage) => void): () => void
  /** 환풍기·욕실 조명만 허용. 인덕션은 원격 제어하지 않는다(조회 전용 결정). */
  controlDevice(deviceId: string, control: DeviceControl): Promise<void>
  submitFeedback(eventId: string, verdict: 'approved' | 'rejected'): Promise<SafetyEvent['feedback']>
  saveContact(kind: 'user' | 'guardian', contact: Contact): Promise<ContactSaveResult>
  savePolicy(policy: KitchenPolicy): Promise<KitchenPolicy>
  saveFallPolicy(policy: FallPolicy): Promise<FallPolicy>
  readonly demo: DemoControls | null
}
