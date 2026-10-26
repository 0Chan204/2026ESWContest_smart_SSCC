import type {
  AirMode, Burner, Contact, ContactSaveResult, CookingSession, Device, FallIncident, FallPolicy,
  KitchenPolicy, Location, Presence, Publisher, SafetyEvent, SensingNode, SensingSample, Weather,
} from '@/types'

export interface Snapshot {
  devices: Device[]
  presence: { kitchen: Presence; bathroom: Presence }
  location: Location
  /** 최근 최종 재실 판단 결과 (오래된 것부터, 최대 60개) */
  sensing: SensingSample[]
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
  /** 정수기·환풍기·조명 상태 (백엔드 device.state 를 화면 기기 형식으로 바꾼 것) */
  | { event: 'device.updated'; data: Device }
  /** (FE 확장) 중앙제어가 판단한 사용자 위치 */
  | { event: 'location.updated'; data: { location: Location; observedAt: string } }
  /** BE ai.announcement · weather.briefing — 화면에 띄우고 음성으로 읽는 안내 문장 (음성 명령 답변은 제외) */
  | { event: 'announcement'; data: { id: string; text: string; at: string } }
  /** BE sensing.result — 최종 재실 판단 (약 1초마다) */
  | { event: 'sensing.result'; data: SensingSample }
  /** BE voice.status — 음성 명령 진행 상황 (docs/VOICE.md) */
  | { event: 'voice.status'; data: VoiceRecord }

export interface DeviceControl {
  on?: boolean
  speed?: 1 | 2 | 3
  brightness?: number
  /** 공기청정기 운전 모드 */
  mode?: AirMode
}

// ── 음성 명령 (BE v0.7 docs/VOICE.md) ─────────────────────────────────────
export type VoiceStatus =
  | 'received' | 'thinking' | 'confirm_required' | 'executed' | 'answered' | 'cancelled' | 'timeout' | 'failed'

/** voice.status 의 data 중 화면에 필요한 것만 */
export interface VoiceRecord {
  voiceId: string
  status: VoiceStatus
  /** 사용자에게 들려줄 답변 */
  answer?: string
  /** 확인 창 문구 (서버가 만든 문장을 그대로 보여준다) */
  confirmText?: string
  /** 이 시각까지 확인이 없으면 서버가 취소 (ISO) */
  confirmDeadline?: string
}

export interface VoiceMeta {
  /** 음성 인식 신뢰도 0~1 */
  confidence?: number
  /** 인식이 끝난 시각 (시간대 포함 ISO, 예: 2026-10-24T21:00:00+09:00) */
  recognizedAt: string
}

/** 백엔드 음성 명령 창구. 백엔드에 연결했을 때만 있다 (시연 모드는 화면 안 규칙으로 처리) */
export interface VoiceService {
  /** 인식한 전체 문장을 보낸다. 202 면 voiceId, 실패하면 예외 */
  send(text: string, meta: VoiceMeta): Promise<{ voiceId: string }>
  /** 확인 창 결과 (true 실행 / false 취소) */
  confirm(voiceId: string, approved: boolean): Promise<void>
}

/** 시연 전용 조작. 실제 서버 소스에서는 null */
export interface DemoControls {
  leaveKitchen(zone: 'near' | 'far'): void
  returnKitchen(): void
  overheat(): void
  fall(): void
  morningDispense(): void
  toggleOffline(deviceId: string): void
  /** (v5) 인덕션 켜짐 → 꺼져 있던 공기청정기를 HomeVIS 가 켬 (이미 조리 중이면 공기청정기만) */
  startCooking(): void
  /** (v5) 공기질 나빠짐 (자동 모드면 공기청정기가 스스로 켜짐) */
  airWorse(): void
}

/**
 * 데이터 소스 경계. 화면은 이 인터페이스만 안다.
 * mockSource(현재) → httpSource(백엔드 연동) 교체 시 화면 코드는 바뀌지 않는다.
 */
export interface DataSource {
  readonly kind: 'mock' | 'http'
  loadSnapshot(): Promise<Snapshot>
  subscribe(listener: (message: StreamMessage) => void): () => void
  /** 환풍기·조명·공기청정기만 허용. 인덕션·정수기는 원격 제어하지 않는다(조회 전용 결정). */
  controlDevice(deviceId: string, control: DeviceControl): Promise<void>
  submitFeedback(eventId: string, verdict: 'approved' | 'rejected'): Promise<SafetyEvent['feedback']>
  saveContact(kind: 'user' | 'guardian', contact: Contact): Promise<ContactSaveResult>
  savePolicy(policy: KitchenPolicy): Promise<KitchenPolicy>
  saveFallPolicy(policy: FallPolicy): Promise<FallPolicy>
  /** 시계 옆 날씨. 받아 둔 날씨가 없으면 null */
  loadWeather(): Promise<Weather | null>
  /** 공간별 센서 노드 신호 상태 (재실 감지 화면을 열어 둔 동안 몇 초마다 부른다) */
  loadSensingNodes(): Promise<SensingNode[]>
  /** 백엔드 음성 명령. 시연 소스에서는 null */
  readonly voice: VoiceService | null
  readonly demo: DemoControls | null
}
