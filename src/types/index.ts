/**
 * 프론트엔드 도메인 타입.
 *
 * 인덕션·안전 이벤트·세션·낙상·정책은 백엔드 v0.2.1(app/schemas.py)과 필드명·값을 맞췄다.
 * 백엔드가 아직 제공하지 않는 정보(정수기·환풍기·욕실 조명, 위치, 안내 문장)는
 * 임베디드/중앙제어 파트 설계(중간발표 자료)를 따라 프론트 확장 필드로 둔다.
 */

export type Mode = 'normal' | 'elderly'
export type Language = 'ko' | 'en'
/** 화면 테마. 기본 light (밝은 주방 월패드). 다크·시스템은 설정에서 선택 */
export type Theme = 'dark' | 'light' | 'system'

/** 부스 구성: 침실 · 거실 · 주방 · 욕실 */
export type RoomId = 'kitchen' | 'bathroom' | 'bedroom' | 'living'
/** 사용자 현재 위치 (중앙제어: 집 밖 / 판단 불가 포함) */
export type Location = RoomId | 'outside' | 'unknown'

/** 화면에 보여줄 위험 단계 (중앙제어 CAUTION/WARNING/DANGER + 센서 불확실) */
export type Risk = 'normal' | 'caution' | 'warning' | 'danger' | 'uncertain'

// ── 인덕션 (BE BurnerTelemetry) ───────────────────────────────────────────
export type BurnerState = 'off' | 'on' | 'overheated' | 'cooling'
export type Publisher = 'user' | 'system' | 'api'

export interface Burner {
  burnerId: string
  deviceState: BurnerState
  /** 0~9 (off·overheated 면 0) */
  level: number
  temperature: number
  activeSec: number
}

/** BE compute_safety_phase() 와 같은 값 */
export type KitchenPhase = 'normal' | 'absence_watch' | 'auto_reduced' | 'auto_off' | 'overheat'

// ── 기기 ─────────────────────────────────────────────────────────────────
interface DeviceBase {
  id: string
  name: string
  room: RoomId
  online: boolean
}

export interface InductionDevice extends DeviceBase {
  kind: 'induction'
  burner: Burner
  /** 마지막으로 상태를 바꾼 주체 (user=본체 조작, system=안전 자동 조치) */
  lastControl: Publisher
  alarm: boolean
  /** 온도 추이 (최근 → 마지막 원소) */
  tempHistory: number[]
}

export interface PurifierDevice extends DeviceBase {
  kind: 'purifier'
  dispensing: boolean
  lastDispense: { at: string; ml: number; auto: boolean } | null
  /** 아침 자동 출수는 하루 1회 */
  autoDispensedToday: boolean
}

export interface FanDevice extends DeviceBase {
  kind: 'fan'
  on: boolean
  /** 풍량 1~3 (PWM 단계) */
  speed: 1 | 2 | 3
  auto: boolean
}

export interface LightDevice extends DeviceBase {
  kind: 'light'
  on: boolean
  brightness: number
  auto: boolean
  /** 밝기 조절 가능 여부. 백엔드 전등은 켜기/끄기만 지원해 false (기본 true) */
  dimmable?: boolean
}

export type Device = InductionDevice | PurifierDevice | FanDevice | LightDevice

// ── 재실 (BE PresenceReport) ─────────────────────────────────────────────
export type Zone = 'kitchen' | 'near' | 'far' | 'unknown'

export interface Presence {
  room: 'kitchen' | 'bathroom'
  present: boolean
  zone: Zone
  absentSec: number
  /** 0~1 */
  confidence: number
  observedAt: string
}

// ── 안전 이벤트 (BE SafetyEvent) ──────────────────────────────────────────
export type SafetyEventType =
  | 'cooking_started'
  | 'absence_detected'
  | 'auto_power_reduced'
  | 'auto_power_off'
  | 'overheat_detected'
  | 'command_blocked'
  | 'overheat_cleared'
  | 'user_returned'
  | 'cooking_ended'
  | 'fall_detected'
  | 'fall_resolved'
  | 'fall_reported'
  | 'fall_auto_reported'
  /** BE v0.3.1: 사용자가 응답하지 않아 보호자에게 알림을 넘김 */
  | 'fall_escalated'
  /** BE v0.3: AI 중앙 판정 엔진의 판단으로 가전을 제어함 */
  | 'ai_control'
  /** 프론트 확장: 중앙제어 아침 자동 출수 */
  | 'auto_dispense'

export type Severity = 'info' | 'warning' | 'danger'

export interface SafetyEvent {
  eventId: string
  type: SafetyEventType
  severity: Severity
  occurredAt: string
  room: RoomId
  sessionId?: string
  temperature?: number
  trigger?: string
  action?: string
  reasoning?: string
  /** 중앙제어 LLM 이 만든 안내 문장 (BE 연동 예정 필드) */
  guidance?: string
  feedback?: { verdict: 'approved' | 'rejected'; submittedAt: string }
}

// ── 조리 세션 (BE SessionRecord) ──────────────────────────────────────────
export interface SessionEntry {
  at: string
  type: string
  summary: string
}

export interface CookingSession {
  sessionId: string
  startedAt: string
  endedAt?: string
  status: 'active' | 'ended'
  peakTemperature: number
  timeline: SessionEntry[]
}

// ── 낙상 (BE FallIncident) ───────────────────────────────────────────────
export type FallStatus = 'pending' | 'resolved' | 'reported' | 'auto_reported'

export interface FallIncident {
  incidentId: string
  room: RoomId
  status: FallStatus
  detectedAt: string
  confidence: number
  confirmUrl: string
  autoReportAt: string
  eventId?: string
  resolvedAt?: string
  reportedAt?: string
  /** 프론트 표시용: 보호자 문자 발송 여부 / 인덕션 비상 차단 여부 */
  guardianNotified?: boolean
  burnerShutOff?: boolean
}

// ── 연락처 / 정책 ────────────────────────────────────────────────────────
export interface Contact {
  name: string
  /** 숫자만 저장 */
  phone: string
}

export interface ContactSaveResult {
  contact: Contact
  verificationSent: boolean
  message: string
}

export interface KitchenPolicy {
  watchAfterSec: number
  reduceAfterSec: number
  offAfterSec: number
  reduceToLevel: number
  minConfidence: number
  nearZoneMultiplier: number
  overheatEnterC: number
  overheatExitC: number
  heartbeatTimeoutSec: number
}

export interface FallPolicy {
  autoReportSec: number
}

// ── 날씨 (BE GET /weather · WeatherBriefing) ─────────────────────────────
export interface Weather {
  location: string
  temperature: number
  /** 날씨 상태 한국어 (맑음, 흐림, 비 …) */
  condition: string
  /** WMO 날씨 코드 (아이콘 고르기) */
  code: number
  max?: number
  min?: number
  /** 체감 온도 */
  feels?: number
  /** 습도 (%) */
  humidity?: number
  /** 오늘 최대 강수 확률 (%) */
  rainChance?: number
  /** 서버가 날씨를 받아온 시각 (ISO) */
  fetchedAt?: string
  /** 앞으로 몇 시간의 예보 (백엔드가 hourly 를 주면 채워진다) */
  hourly?: HourlyWeather[]
  /** 오래된 값(인터넷 끊김 등)이면 true */
  stale: boolean
  /** 안내 문장 */
  text: string
}

export interface HourlyWeather {
  /** ISO 시각 */
  time: string
  temperature: number
  code: number
  /** 강수 확률 (%) */
  rainChance?: number
}
