/** 화면 모드. 일반 = 정보 밀도 높음, 어르신 = 단순화 + 큰 타이포 */
export type Mode = 'normal' | 'elderly'

export type Language = 'ko' | 'en'

/** 현재 지원 공간. 침실/거실 등은 이 유니온에 추가만 하면 확장된다. */
export type RoomId = 'kitchen' | 'bathroom'

/** 기기·공간의 안전 상태 */
export type DeviceStatus = 'normal' | 'warning' | 'danger' | 'offline'

/** 전원 상태. STANDBY 는 '대기'(정수기 등) */
export type PowerState = 'ON' | 'OFF' | 'STANDBY'

/** ApplianceCard 시각 변형 */
export type ApplianceVariant = 'active' | 'standby' | 'off' | 'warning' | 'danger' | 'offline'

export type TimelineKind = 'normal' | 'warning' | 'danger' | 'info'

export interface TimelineEvent {
  /** HH:MM */
  time: string
  kind: TimelineKind
  text: string
}

export interface Appliance {
  id: string
  name: string
  room: RoomId
  power: PowerState
  status: DeviceStatus
  /** 카드에 노출되는 핵심 상태 한 줄 (예: "화력 3단계") */
  detail: string
  /** 상세 팝업의 보조 정보 (예: "표면 온도 62°C · 작동 12분") */
  sub: string
  lastUpdate: string
  /**
   * 실제로 제어 API 가 존재하는 기기만 true.
   * false 인 기기는 버튼도 음성도 제어 UI 를 렌더링하지 않는다.
   */
  supportsControl: boolean
  history: TimelineEvent[]
}

export interface Presence {
  room: RoomId
  detected: boolean
  /** 예: "움직임 감지" */
  action: string
  /** 마지막 감지로부터 경과 초 */
  lastDetectedSec: number
  /** 0~100. 어르신 모드에서는 표시하지 않는다. */
  confidence: number
}

export interface EnvMetric {
  key: 'lux' | 'temp' | 'humidity' | 'air'
  value: string
  unit: string
  status: DeviceStatus
}

export interface Environment {
  room: RoomId
  metrics: EnvMetric[]
}

export type SafetyResult = 'success' | 'warning' | 'canceled'

/**
 * 처리 이력. 기획서에 따라 '상태 감지' / '상태 판단' 같은 중간 이벤트는
 * 여기에 담지 않는다. 실제로 시스템이 수행한 안전 처리만 기록한다.
 */
export interface SafetyLog {
  id: string
  /** ISO8601 (로컬 기준) */
  datetime: string
  room: RoomId
  content: string
  result: SafetyResult
  /** 판단 근거 목록 */
  reasoning: string[]
  relatedDevices: string[]
  confidence: number
}

/** 진행 중인 위험 상황 */
export interface SafetyIncident {
  id: string
  room: RoomId
  title: string
  description: string
  /** 카운트다운 초 */
  countdownSec: number
  facts: { icon: 'flame' | 'userX' | 'droplets'; text: string; emphasis?: boolean }[]
  reasoning: string[]
  relatedDevices: string[]
  confidence: number
  /** 카운트다운 종료 시 수행할 안전 조치 */
  action: {
    applianceId: string
    /** 조치 후 detail 로 교체될 문자열 */
    nextDetail: string
    /** 이력에 남길 내용 */
    logContent: string
    /** 기기 이력 타임라인에 남길 문구 */
    deviceHistoryText: string
  }
}

export interface ConnectionIssue {
  room: RoomId
  lastReceivedSec: number
}
