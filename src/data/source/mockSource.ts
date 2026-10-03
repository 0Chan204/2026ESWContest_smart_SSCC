import {
  DEFAULT_FALL_POLICY, DEFAULT_POLICY, GUIDANCE, isoAgo, seedDevices, seedHistory, seedPresence,
} from '@/data/seed'
import { openDemoChannel, type DemoRequest, type DemoResponse } from '@/data/demoChannel'
import type {
  Contact, CookingSession, Device, FallIncident, FallPolicy, InductionDevice, KitchenPolicy,
  Location, Presence, SafetyEvent, SafetyEventType, Severity,
} from '@/types'
import type { DataSource, DeviceControl, Snapshot, StreamMessage } from './types'

/**
 * 시연용 데이터 소스.
 *
 * 백엔드 v0.2.1 의 서버 로직(device_service · safety_service · fall_service)을 축소 재현한다.
 * - 인덕션 telemetry 3초 주기, 과열 진입 150°C / 해제 60°C
 * - 부재 정책: 관찰 → 화력 저감 → 전원 차단 (near 구역은 임계값 2배)
 * - 낙상: 인덕션 비상 차단 + 보호자 문자 + 미응답 시 자동 신고
 * 시연 시간을 줄이기 위해 부재 시간만 실제보다 12배 빠르게 흐른다(1초 = 12초).
 */

const TELEMETRY_MS = 3000
const PRESENCE_MS = 1000
const ABSENCE_SPEED = 12
const ROOM_TEMP = 25
const HISTORY_LEN = 60

const now = () => new Date().toISOString()
const uid = (p: string) => `${p}-${Math.random().toString(16).slice(2, 10)}`
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export function createMockSource(): DataSource {
  const devices: Device[] = seedDevices()
  const presence = seedPresence()
  const history = seedHistory()
  let location: Location = 'kitchen'
  const events: SafetyEvent[] = history.events
  const sessions = new Map<string, CookingSession>(history.sessions.map((s) => [s.sessionId, s]))
  let activeSessionId: string | null = null
  let absenceStage: 'none' | 'watch' | 'reduce' | 'off' = 'none'
  let policy: KitchenPolicy = { ...DEFAULT_POLICY }
  let fallPolicy: FallPolicy = { ...DEFAULT_FALL_POLICY }
  const contacts: { user: Contact | null; guardian: Contact | null } = { user: null, guardian: null }
  let fall: FallIncident | null = null
  let fallToken = ''
  let fallTimer: ReturnType<typeof setTimeout> | null = null

  const listeners = new Set<(m: StreamMessage) => void>()
  const timers: ReturnType<typeof setInterval>[] = []
  let channel: BroadcastChannel | null = null

  const emit = (m: StreamMessage) => listeners.forEach((l) => l(clone(m)))
  const induction = () => devices.find((d): d is InductionDevice => d.kind === 'induction')!

  // 현재 조리 세션 (화구가 켜진 상태로 시작하므로 진행 중 세션 하나를 만든다)
  {
    const id = 'ses-live'
    const startedAt = isoAgo(12 * 60_000)
    sessions.set(id, {
      sessionId: id, startedAt, status: 'active', peakTemperature: 97.5,
      timeline: [{ at: startedAt, type: 'cooking_started', summary: '화구 켜짐 · 화력 4단' }],
    })
    activeSessionId = id
  }

  function addTimeline(type: string, summary: string) {
    if (!activeSessionId) return
    const s = sessions.get(activeSessionId)
    if (!s) return
    s.timeline.push({ at: now(), type, summary })
    emit({ event: 'session.updated', data: s })
  }

  function emitEvent(type: SafetyEventType, severity: Severity, room: SafetyEvent['room'], extra: Partial<SafetyEvent> = {}) {
    const event: SafetyEvent = {
      eventId: uid('evt'), type, severity, occurredAt: now(), room,
      sessionId: room === 'kitchen' && activeSessionId ? activeSessionId : undefined,
      guidance: GUIDANCE[type], ...extra,
    }
    events.unshift(event)
    emit({ event: 'safety.event', data: event })
    return event
  }

  function emitTelemetry() {
    const d = induction()
    emit({
      event: 'burner.telemetry',
      data: { deviceId: d.id, reportedAt: now(), burners: [d.burner], lastControl: d.lastControl, alarm: d.alarm },
    })
  }

  /** 시스템 자동 명령 (BE commands_service.dispatch_command actor=system 과 같은 의미) */
  function systemCommand(type: 'set_level' | 'turn_off', level?: number) {
    const d = induction()
    const b = d.burner
    if (b.deviceState === 'overheated') return false
    if (type === 'turn_off') {
      if (b.deviceState === 'off') return false
      b.level = 0
      b.deviceState = b.temperature > ROOM_TEMP + 5 ? 'cooling' : 'off'
    } else if (level !== undefined) {
      if (b.deviceState !== 'on') return false
      b.level = level
    }
    d.lastControl = 'system'
    emitTelemetry()
    return true
  }

  // ── 인덕션 물리 시뮬레이션 (3초 주기) ─────────────────────────────────
  function tickTelemetry() {
    const d = induction()
    if (!d.online) return
    const b = d.burner
    const prev = b.deviceState
    if (b.deviceState === 'on') {
      const target = ROOM_TEMP + b.level * 20
      b.temperature += (target - b.temperature) * 0.15 + (Math.random() - 0.5) * 0.8
      b.activeSec += TELEMETRY_MS / 1000
      if (b.temperature >= policy.overheatEnterC) {
        b.deviceState = 'overheated'; b.level = 0; d.alarm = true
      }
    } else {
      b.temperature += (ROOM_TEMP - b.temperature) * 0.08
      if (b.deviceState === 'overheated' && b.temperature < policy.overheatExitC) {
        b.deviceState = 'off'; d.alarm = false
      } else if (b.deviceState === 'cooling' && b.temperature <= ROOM_TEMP + 5) {
        b.deviceState = 'off'
      }
    }
    b.temperature = Math.round(b.temperature * 10) / 10
    d.tempHistory = [...d.tempHistory, b.temperature].slice(-HISTORY_LEN)
    if (activeSessionId) {
      const s = sessions.get(activeSessionId)
      if (s && b.temperature >= s.peakTemperature + 1) {
        s.peakTemperature = Math.round(b.temperature)
        emit({ event: 'session.updated', data: s })
      }
    }

    // 상태 전이 → 안전 이벤트 / 세션 (BE device_service.handle_telemetry 와 동일한 규칙)
    if (prev !== b.deviceState) {
      if (b.deviceState === 'overheated') {
        emitEvent('overheat_detected', 'danger', 'kitchen', {
          temperature: b.temperature, trigger: `표면 온도 ${b.temperature.toFixed(0)}°C (기준 ${policy.overheatEnterC}°C)`,
          action: '과열 잠금 — 식을 때까지 켜기 차단', reasoning: '인덕션 본체가 과열 상태를 보고',
        })
        addTimeline('overheat_detected', `표면 온도 ${b.temperature.toFixed(0)}°C 과열 잠금`)
      }
      if (prev === 'overheated') {
        emitEvent('overheat_cleared', 'info', 'kitchen', { temperature: b.temperature, action: '과열 잠금 해제' })
        addTimeline('overheat_cleared', '냉각 완료 · 잠금 해제')
      }
      if (b.deviceState === 'off' && activeSessionId) {
        const s = sessions.get(activeSessionId)
        if (s) {
          s.status = 'ended'; s.endedAt = now()
          s.timeline.push({ at: now(), type: 'cooking_ended', summary: '화구 꺼짐' })
          emit({ event: 'session.updated', data: s })
        }
        emitEvent('cooking_ended', 'info', 'kitchen')
        activeSessionId = null
        absenceStage = 'none'
      }
    }
    emitTelemetry()
  }

  // ── 부재 정책 (BE safety_service.evaluate_presence 축소판) ───────────────
  function tickPresence() {
    const k = presence.kitchen
    if (!k.present) {
      k.absentSec += ABSENCE_SPEED
      k.observedAt = now()
      evaluateAbsence()
      emit({ event: 'presence.updated', data: k })
    } else if (Math.random() < 0.2) {
      k.confidence = Math.round((0.88 + Math.random() * 0.1) * 100) / 100
      k.observedAt = now()
      emit({ event: 'presence.updated', data: k })
    }
  }

  function evaluateAbsence() {
    const k = presence.kitchen
    const b = induction().burner
    if (k.confidence < policy.minConfidence) return
    const cooking = b.deviceState === 'on' || absenceStage !== 'none'
    if (!cooking) return
    const mult = k.zone === 'near' ? policy.nearZoneMultiplier : 1
    const absent = k.absentSec

    if (absent >= policy.offAfterSec * mult && absenceStage !== 'off') {
      absenceStage = 'off'
      const ok = systemCommand('turn_off')
      emitEvent('auto_power_off', 'danger', 'kitchen', {
        temperature: b.temperature, trigger: `주방 부재 ${Math.round(absent / 60)}분 경과`,
        action: ok ? '인덕션 전원 자동 차단' : '전원 차단 시도 (이미 꺼짐)', reasoning: '화력 저감 후에도 사용자가 돌아오지 않음',
      })
      addTimeline('auto_power_off', '장시간 부재로 자동 전원 차단')
    } else if (absent >= policy.reduceAfterSec * mult && absenceStage === 'watch') {
      absenceStage = 'reduce'
      const before = b.level
      const ok = systemCommand('set_level', policy.reduceToLevel)
      emitEvent('auto_power_reduced', 'warning', 'kitchen', {
        temperature: b.temperature,
        trigger: `주방 부재 ${Math.round(absent / 60)}분 경과 · 감지 정확도 ${Math.round(k.confidence * 100)}%`,
        action: ok ? `화력 ${before}단 → ${policy.reduceToLevel}단 자동 저감` : '저감 시도 (과열 잠금 중)',
        reasoning: '인덕션 작동 중 사용자 이탈이 기준 시간을 넘음',
      })
      addTimeline('auto_power_reduced', `화력 ${before} → ${policy.reduceToLevel}단 자동 저감`)
    } else if (absent >= policy.watchAfterSec * mult && absenceStage === 'none') {
      absenceStage = 'watch'
      emitEvent('absence_detected', 'warning', 'kitchen', {
        trigger: `부재 ${absent}초 경과 (기준 ${policy.watchAfterSec * mult}초)`,
        action: '조치 없음 (관찰 시작)', reasoning: '이탈이 감지되어 관찰 단계로 진입',
      })
      addTimeline('absence_detected', '사용자 이탈 감지 (관찰 시작)')
    }
  }

  function setLocation(next: Location) {
    location = next
    emit({ event: 'location.updated', data: { location, observedAt: now() } })
  }

  // ── 낙상 (BE fall_service 축소판) ────────────────────────────────────────
  function fallState(): FallIncident | null {
    return fall ? clone(fall) : null
  }

  function finishFall(status: 'resolved' | 'reported' | 'auto_reported') {
    if (!fall || fall.status !== 'pending') return
    if (fallTimer) clearTimeout(fallTimer)
    fall.status = status
    if (status === 'resolved') fall.resolvedAt = now()
    else fall.reportedAt = now()
    const map = {
      resolved: ['fall_resolved', 'info', '보호자가 "괜찮음" 으로 확인'],
      reported: ['fall_reported', 'danger', '보호자가 신고 요청'],
      auto_reported: ['fall_auto_reported', 'danger', '보호자 응답 없음 → 자동 신고 처리'],
    } as const
    const [type, sev, action] = map[status]
    emitEvent(type, sev, 'bathroom', {
      action, reasoning: status === 'auto_reported' ? `확인 대기 ${fallPolicy.autoReportSec}초 초과` : '보호자 확인 링크 응답',
    })
    emit({ event: 'fall.incident', data: fall })
    broadcastFall()
  }

  function broadcastFall() {
    if (channel && fall) channel.postMessage({ type: 'fall:state', requestId: 'push', incident: fall } satisfies DemoResponse)
  }

  function handleDemoRequest(msg: DemoRequest) {
    if (!channel) return
    const valid = fall && msg.incidentId === fall.incidentId && msg.token === fallToken
    if (!valid) {
      channel.postMessage({ type: 'fall:invalid', requestId: msg.requestId } satisfies DemoResponse)
      return
    }
    if (msg.type === 'fall:resolve') finishFall('resolved')
    if (msg.type === 'fall:report') finishFall('reported')
    channel.postMessage({ type: 'fall:state', requestId: msg.requestId, incident: fall! } satisfies DemoResponse)
  }

  // ── DataSource 구현 ──────────────────────────────────────────────────────
  return {
    kind: 'mock',

    async loadSnapshot(): Promise<Snapshot> {
      return clone({
        devices, presence, location,
        session: activeSessionId ? sessions.get(activeSessionId) ?? null : null,
        sessions: [...sessions.values()],
        events, fall: fallState(), contacts, policy, fallPolicy,
      })
    },

    subscribe(listener) {
      listeners.add(listener)
      if (timers.length === 0) {
        timers.push(setInterval(tickTelemetry, TELEMETRY_MS), setInterval(tickPresence, PRESENCE_MS))
        channel = openDemoChannel()
        if (channel) channel.onmessage = (e: MessageEvent<DemoRequest>) => handleDemoRequest(e.data)
      }
      return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
          timers.splice(0).forEach(clearInterval)
          channel?.close(); channel = null
        }
      }
    },

    async controlDevice(deviceId: string, control: DeviceControl) {
      const d = devices.find((x) => x.id === deviceId)
      // 인덕션·정수기는 원격 제어하지 않는다 (조회 전용).
      if (!d || (d.kind !== 'fan' && d.kind !== 'light') || !d.online) throw new Error('제어할 수 없는 기기입니다.')
      if (control.on !== undefined) { d.on = control.on; d.auto = false }
      if (d.kind === 'fan' && control.speed) { d.speed = control.speed; d.on = true; d.auto = false }
      if (d.kind === 'light' && control.brightness !== undefined) {
        d.brightness = Math.min(100, Math.max(10, Math.round(control.brightness))); d.on = true; d.auto = false
      }
      emit({ event: 'device.updated', data: d })
    },

    async submitFeedback(eventId, verdict) {
      const e = events.find((x) => x.eventId === eventId)
      if (!e) throw new Error('이벤트를 찾을 수 없습니다.')
      e.feedback = { verdict, submittedAt: now() }
      return e.feedback
    },

    async saveContact(kind, contact) {
      contacts[kind] = { ...contact }
      return {
        contact: { ...contact }, verificationSent: false,
        message: '저장했어요. 시연 모드라 확인 문자는 실제로 발송되지 않아요.',
      }
    },

    async savePolicy(next) { policy = { ...next }; return policy },
    async saveFallPolicy(next) { fallPolicy = { ...next }; return fallPolicy },

    demo: {
      leaveKitchen(zone) {
        const k: Presence = presence.kitchen
        k.present = false; k.zone = zone; k.absentSec = 0; k.confidence = 0.92; k.observedAt = now()
        setLocation(zone === 'near' ? 'living' : 'bedroom')
        emit({ event: 'presence.updated', data: k })
      },
      returnKitchen() {
        const k = presence.kitchen
        const wasAway = !k.present
        k.present = true; k.zone = 'kitchen'; k.absentSec = 0; k.observedAt = now()
        setLocation('kitchen')
        if (wasAway && absenceStage !== 'none') {
          emitEvent('user_returned', 'info', 'kitchen', { action: '위험 상태 해제' })
          addTimeline('user_returned', '사용자 복귀')
        }
        absenceStage = 'none'
        emit({ event: 'presence.updated', data: k })
      },
      overheat() {
        const d = induction()
        if (d.burner.deviceState !== 'on') {
          d.burner.deviceState = 'on'; d.burner.level = 8; d.lastControl = 'user'
          if (!activeSessionId) {
            const id = uid('ses')
            sessions.set(id, { sessionId: id, startedAt: now(), status: 'active', peakTemperature: d.burner.temperature, timeline: [] })
            activeSessionId = id
            addTimeline('cooking_started', '화구 켜짐 · 화력 8단')
          }
        }
        d.burner.level = 9
        d.burner.temperature = policy.overheatEnterC - 1
        tickTelemetry()
      },
      fall() {
        if (fall?.status === 'pending') return
        const d = induction()
        const wasCooking = d.burner.deviceState === 'on'
        if (wasCooking) systemCommand('turn_off')
        const incidentId = uid('fall')
        fallToken = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2)
        const detectedAt = now()
        fall = {
          incidentId, room: 'bathroom', status: 'pending', detectedAt, confidence: 0.91,
          confirmUrl: `${window.location.origin}/fall/${incidentId}?token=${fallToken}`,
          autoReportAt: new Date(Date.now() + fallPolicy.autoReportSec * 1000).toISOString(),
          guardianNotified: contacts.guardian !== null, burnerShutOff: wasCooking,
        }
        presence.bathroom = { ...presence.bathroom, present: true, observedAt: detectedAt }
        setLocation('bathroom')
        const light = devices.find((x) => x.kind === 'light')
        if (light && light.kind === 'light' && light.auto && !light.on) {
          light.on = true
          emit({ event: 'device.updated', data: light })
        }
        const e = emitEvent('fall_detected', 'danger', 'bathroom', {
          trigger: '서 있다가 누운 자세로 바뀐 뒤 10초간 움직임 없음',
          action: [wasCooking ? '인덕션 비상 전원 차단' : null, contacts.guardian ? '보호자 문자 발송' : '보호자 미등록 — 문자 미발송']
            .filter(Boolean).join(' · '),
          reasoning: '욕실 낙상 의심 (감지 정확도 91%)',
        })
        fall.eventId = e.eventId
        fallTimer = setTimeout(() => finishFall('auto_reported'), fallPolicy.autoReportSec * 1000)
        emit({ event: 'fall.incident', data: fall })
        emit({ event: 'presence.updated', data: presence.bathroom })
      },
      morningDispense() {
        const p = devices.find((x) => x.kind === 'purifier')
        if (!p || p.kind !== 'purifier') return
        if (p.autoDispensedToday) {
          emitEvent('auto_dispense', 'info', 'kitchen', {
            action: '출수 안 함 — 오늘 이미 자동 출수함', reasoning: '아침 자동 출수는 하루 1회로 제한', guidance: undefined,
          })
          return
        }
        p.dispensing = true
        emit({ event: 'device.updated', data: p })
        setTimeout(() => {
          p.dispensing = false; p.autoDispensedToday = true
          p.lastDispense = { at: now(), ml: 250, auto: true }
          emit({ event: 'device.updated', data: p })
          emitEvent('auto_dispense', 'info', 'kitchen', {
            trigger: '기상 후 주방 이동 · 5초 이상 머무름', action: '정수기 250mL 자동 출수',
            reasoning: '아침 6~10시 기상 감지 후 30분 이내 주방 이동',
          })
        }, 2500)
      },
      toggleOffline(deviceId) {
        const d = devices.find((x) => x.id === deviceId)
        if (!d) return
        d.online = !d.online
        emit({ event: 'connection.changed', data: { deviceId, online: d.online } })
      },
    },
  }
}
