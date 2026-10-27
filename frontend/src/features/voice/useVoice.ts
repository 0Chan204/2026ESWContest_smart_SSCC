import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { usePreferences } from '@/store/PreferencesContext'
import { useHome } from '@/store/HomeStore'
import { useSpeech } from '@/hooks/useSpeech'
import { describeBathroom, describeKitchen, HERO_TITLE } from '@/lib/rooms'
import { withObjectParticle } from '@/lib/korean'
import { AIR_LEVEL_LABEL, ROOM_LABEL } from '@/lib/labels'
import { FAN_SPEED_LABEL } from '@/lib/device'
import { isoWithOffset } from '@/lib/format'
import type { DeviceControl, StreamMessage, VoiceMeta, VoiceRecord } from '@/data/source'
import type { Device } from '@/types'
import { matchCommand, matchNavigation, nextDemoCommand, type VoiceIntent } from './commands'
import { createRecognition, finalTranscripts, speechSupported, type SpeechRecognitionLike } from './speech'
import { detectWake } from './wake'

export type VoiceState = 'idle' | 'listening' | 'recognized' | 'processing' | 'confirm' | 'completed' | 'error'

export interface VoiceController {
  open: boolean
  state: VoiceState
  /** 마이크 없이 예시 명령으로 보여주는 중 */
  demo: boolean
  heard: string
  reply: string
  /** processing 일 때 보여줄 글자 (알아들었어요 · 확인하고 있어요 · 실행하고 있어요) */
  progress: string
  /** error 일 때 보여줄 글자 */
  errorText: string
  /** 확인 창 (deadline 이 있으면 그때까지 답이 없으면 서버가 취소) */
  pending: { message: string; deadline?: string } | null
  /** 호출어 대기 중 — 마이크가 켜져 있다 */
  wakeListening: boolean
  start: () => void
  close: () => void
  confirm: () => void
  cancel: () => void
}

export const UNAVAILABLE = '지금은 음성 명령을 쓸 수 없어요'
const MISHEARD = '잘 듣지 못했어요'
const HIDE_MS = 3200
/** 호출어만 들었을 때 다음 말을 기다리는 시간 */
const WAKE_FOLLOW_MS = 8000
/** 서버 응답이 끝내 오지 않을 때 (서버 판정 대기 10초 + 확인 창 30초와 별개로 진행 중 단계만) */
const BACKEND_SAFETY_MS = 20_000

/** TTS 가 말하는 동안에는 호출어 대기를 멈춘다 (자기 목소리를 듣지 않도록) */
function useSpeaking(active: boolean): boolean {
  const [speaking, setSpeaking] = useState(false)
  useEffect(() => {
    if (!active || typeof window === 'undefined' || !('speechSynthesis' in window)) { setSpeaking(false); return }
    const t = setInterval(() => setSpeaking(window.speechSynthesis.speaking), 300)
    return () => clearInterval(t)
  }, [active])
  return speaking
}

function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || !document.hidden)
  useEffect(() => {
    const on = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])
  return visible
}

/** 기기 조작을 묻는 문장과 실행 뒤 문장 */
function phrase(name: string, c: DeviceControl): { ask: string; done: string } {
  const obj = withObjectParticle(name)
  if (c.speed) return { ask: `${name} 풍량을 ${FAN_SPEED_LABEL[c.speed]}으로 바꿀까요?`, done: `${name} 풍량을 ${FAN_SPEED_LABEL[c.speed]}으로 바꿨어요.` }
  if (c.brightness !== undefined && c.brightness <= 20) return { ask: `${obj} 절전 밝기로 낮출까요?`, done: `${obj} 절전 밝기로 낮췄어요.` }
  if (c.brightness !== undefined) return { ask: `${obj} 가장 밝게 할까요?`, done: `${obj} 가장 밝게 했어요.` }
  if (c.mode) {
    const m = c.mode === 'auto' ? '자동' : '수동'
    return { ask: `${name} 운전 모드를 ${m}으로 바꿀까요?`, done: `${name} 운전 모드를 ${m}으로 바꿨어요.` }
  }
  return c.on ? { ask: `${obj} 켤까요?`, done: `${obj} 켰어요.` } : { ask: `${obj} 끌까요?`, done: `${obj} 껐어요.` }
}

/**
 * 음성 상태 머신. 원칙:
 * 1) 음성으로 되는 조작은 화면 버튼으로도 된다 (Voice-only 기능 없음)
 * 2) 기기 상태를 바꾸는 명령은 확인을 받고 실행한다
 * 3) 마이크는 설정에서 켠 경우에만 요청한다 (기본 꺼짐 — 음성이 외부로 전송될 수 있음)
 *
 * 처리 경로 (백엔드 docs/VOICE.md)
 * - 화면 이동("주방", "기록 보여줘", "설정", "우리 집")은 화면에서 바로 처리하고 서버로 보내지 않는다.
 * - 백엔드 연결(source.voice 있음): 나머지 문장은 POST /voice/commands → WS voice.status 로 진행 · 확인 창 · 답변.
 * - 시연(source.voice 없음) · 예시 명령(마이크 없음): commands.ts 의 화면 안 규칙으로 처리.
 * - 호출어 "홈비스": 설정에서 켜면 계속 듣다가, 문장 앞에 호출어가 있을 때만 명령으로 처리한다.
 */
export function useVoice(): VoiceController {
  const navigate = useNavigate()
  const { voiceEnabled, wakeWordEnabled } = usePreferences()
  const home = useHome()
  const homeRef = useRef(home)
  homeRef.current = home
  const speak = useSpeech()

  const [open, setOpen] = useState(false)
  const [state, setState] = useState<VoiceState>('idle')
  const [demo, setDemo] = useState(false)
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')
  const [progress, setProgress] = useState('')
  const [errorText, setErrorText] = useState(MISHEARD)
  const [pending, setPending] = useState<VoiceController['pending']>(null)
  /** 호출어만 듣고 패널을 연 상태 — 호출어 인식기가 다음 말을 받는다 */
  const [wakeMode, setWakeMode] = useState(false)
  const wakeModeRef = useRef(false)
  wakeModeRef.current = wakeMode

  const oneShotRef = useRef<SpeechRecognitionLike | null>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  /** 지금 기다리는 백엔드 음성 명령 */
  const voiceIdRef = useRef<string | null>(null)
  /** 백엔드 확인 창이 떠 있는지 (닫으면 취소를 보낸다) */
  const confirmingRef = useRef(false)
  /** POST 응답보다 먼저 온 voice.status 를 잠시 보관 */
  const statusBuffer = useRef(new Map<string, VoiceRecord>())
  /** 시연 모드 확인 창의 실행 동작 */
  const localRunRef = useRef<(() => void) | null>(null)
  /** 보낸 요청 순번 (닫은 뒤 늦게 온 응답 무시) */
  const seqRef = useRef(0)

  const later = useCallback((fn: () => void, ms: number) => { timers.current.push(setTimeout(fn, ms)) }, [])
  const clearTimers = useCallback(() => { timers.current.forEach(clearTimeout); timers.current = [] }, [])

  const close = useCallback(() => {
    clearTimers()
    const id = voiceIdRef.current
    const svc = homeRef.current.source.voice
    // 확인 창이 떠 있는 채로 닫으면 실행하지 않는다
    if (id && confirmingRef.current && svc) void svc.confirm(id, false).catch(() => { /* 서버가 30초 뒤 자동 취소 */ })
    voiceIdRef.current = null; confirmingRef.current = false; localRunRef.current = null; seqRef.current += 1
    oneShotRef.current?.abort(); oneShotRef.current = null
    setOpen(false); setState('idle'); setHeard(''); setReply(''); setPending(null); setWakeMode(false); setProgress('')
  }, [clearTimers])
  useEffect(() => () => { timers.current.forEach(clearTimeout); oneShotRef.current?.abort() }, [])

  const finish = useCallback((text: string) => {
    voiceIdRef.current = null; confirmingRef.current = false
    setPending(null); setReply(text); setState('completed'); speak(text)
    later(close, Math.max(HIDE_MS, text.length * 110))
  }, [later, close, speak])

  const fail = useCallback((text: string = MISHEARD) => {
    voiceIdRef.current = null; confirmingRef.current = false
    setPending(null); setErrorText(text); setState('error'); later(close, HIDE_MS)
  }, [later, close])

  // ── 시연 모드 · 화면 이동 ───────────────────────────────────────────────
  const run = useCallback((intent: VoiceIntent) => {
    const h = homeRef.current
    if (intent.kind === 'refuse') return finish(intent.reply)
    if (intent.kind === 'navigate') {
      navigate(intent.route)
      const k = describeKitchen(h.kitchenPhase, h.induction, h.presence.kitchen)
      const b = describeBathroom(h.fall, h.presence.bathroom)
      const text = {
        home: `${HERO_TITLE[h.overallRisk]}. 주방은 ${k.short}, 욕실은 ${b.short}.`,
        kitchen: `주방은 지금 ${k.text}.`,
        bathroom: `욕실은 지금 ${b.text}.`,
        history: '안전 기록을 보여드릴게요.',
        settings: '설정 화면이에요.',
      }[intent.reply]
      return finish(text)
    }
    if (intent.kind === 'answer') {
      if (intent.topic === 'weather') {
        const w = h.weather
        return finish(w ? (w.text || `${w.location} 지금 ${w.condition}, ${Math.round(w.temperature)}도예요.`) : '날씨 정보를 아직 받지 못했어요.')
      }
      const a = h.devices.find((d) => d.kind === 'air')
      if (!a || a.kind !== 'air') return finish('공기청정기가 연결되어 있지 않아요.')
      const q = a.airQuality
      if (!q?.level && q?.pm25 === undefined) return finish('공기질 값을 아직 받지 못했어요.')
      return finish(`${ROOM_LABEL[a.room]} 공기는 ${q.level ? AIR_LEVEL_LABEL[q.level] : '측정 중'}이에요.${q.pm25 !== undefined ? ` 초미세먼지 ${Math.round(q.pm25)}이에요.` : ''}`)
    }
    // 기기 제어: 말한 공간 → 지금 있는 공간 → 그 종류의 첫 기기
    const kind = intent.device
    const all = h.devices.filter((d): d is Extract<Device, { kind: typeof kind }> => d.kind === kind)
    const device = intent.room ? all.find((d) => d.room === intent.room)
      : all.find((d) => d.room === h.location) ?? all[0]
    if (!device) return finish(intent.room ? `${ROOM_LABEL[intent.room]}에는 그 기기가 없어요.` : '그 기기는 아직 등록되어 있지 않아요.')
    if (!device.online) return finish('지금은 그 기기와 연결이 끊겨 있어요.')
    const { ask, done } = phrase(device.name, intent.control)
    localRunRef.current = () => {
      void h.controlDevice(device.id, intent.control)
      localRunRef.current = null
      finish(done)
    }
    setPending({ message: ask }); setState('confirm')
  }, [navigate, finish])

  // ── 백엔드 음성 명령 ────────────────────────────────────────────────────
  const applyStatus = useCallback((rec: VoiceRecord) => {
    switch (rec.status) {
      case 'received': setState('processing'); setProgress('알아들었어요'); return
      case 'thinking': setState('processing'); setProgress('확인하고 있어요'); return
      case 'confirm_required':
        confirmingRef.current = true
        setPending({ message: rec.confirmText ?? '실행할까요?', deadline: rec.confirmDeadline }); setState('confirm'); return
      case 'executed': return finish(rec.answer ?? '실행했어요.')
      case 'answered': return finish(rec.answer ?? '알겠어요.')
      case 'cancelled': case 'timeout': return fail(MISHEARD)
      case 'failed': return fail(UNAVAILABLE)
    }
  }, [finish, fail])

  const { subscribeStream } = home
  useEffect(() => subscribeStream((m: StreamMessage) => {
    if (m.event !== 'voice.status') return
    const buf = statusBuffer.current
    buf.set(m.data.voiceId, m.data)
    if (buf.size > 20) buf.delete(buf.keys().next().value!)
    if (voiceIdRef.current === m.data.voiceId) applyStatus(m.data)
  }), [subscribeStream, applyStatus])

  const sendToBackend = useCallback((text: string, meta: VoiceMeta) => {
    const svc = homeRef.current.source.voice
    if (!svc) return fail(UNAVAILABLE)
    const seq = ++seqRef.current
    setState('processing'); setProgress('알아들었어요')
    svc.send(text, meta).then(({ voiceId }) => {
      if (seq !== seqRef.current) { void svc.confirm(voiceId, false).catch(() => { /* 확인 창이 아니면 409 — 무시 */ }); return }
      voiceIdRef.current = voiceId
      const early = statusBuffer.current.get(voiceId)
      if (early) applyStatus(early)
      later(() => { if (voiceIdRef.current === voiceId && !confirmingRef.current) fail(MISHEARD) }, BACKEND_SAFETY_MS)
    }).catch(() => { if (seq === seqRef.current) fail(UNAVAILABLE) })
  }, [fail, applyStatus, later])

  /**
   * 인식한 문장 하나 처리.
   * local = 예시 명령(마이크 없음) — 백엔드로 보내지 않는다.
   */
  const handleText = useCallback((text: string, confidence: number | undefined, local: boolean) => {
    const { wake, rest } = detectWake(text)
    const body = wake ? rest : text.trim()
    if (!body) return fail(MISHEARD)
    setHeard(body); setState('recognized')
    const nav = matchNavigation(body)
    if (nav) { later(() => run(nav), 400); return }
    if (!local && homeRef.current.source.voice) {
      // 서버가 호출어를 떼므로 들은 문장 그대로 보낸다
      sendToBackend(text.trim(), { confidence, recognizedAt: isoWithOffset() })
      return
    }
    later(() => {
      const intent = matchCommand(body)
      if (!intent) return fail(MISHEARD)
      run(intent)
    }, 500)
  }, [fail, later, run, sendToBackend])

  // ── 호출어 대기 ─────────────────────────────────────────────────────────
  const supported = speechSupported()
  const visible = usePageVisible()
  const speaking = useSpeaking(wakeWordEnabled && voiceEnabled)
  const [blocked, setBlocked] = useState(false)
  const want = wakeWordEnabled && voiceEnabled && supported && !blocked && visible
  const paused = speaking || (open && !wakeMode)
  const wakeRecRef = useRef<SpeechRecognitionLike | null>(null)
  const wakeRestart = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wakeFailures = useRef(0)
  const activeRef = useRef(false)
  activeRef.current = want && !paused

  /** 호출어 인식기가 들은 문장 */
  const onWakeTranscript = useCallback((text: string, confidence?: number) => {
    const { wake, rest } = detectWake(text)
    if (wakeModeRef.current) {
      // 호출어 뒤 다음 말 = 명령
      setWakeMode(false); clearTimers()
      if (wake && !rest) { setWakeMode(true); later(() => { if (wakeModeRef.current) { setWakeMode(false); fail(MISHEARD) } }, WAKE_FOLLOW_MS); return }
      handleText(text, confidence, false)
      return
    }
    if (!wake) return
    clearTimers()
    setOpen(true); setDemo(false); setReply(''); setPending(null)
    if (!rest) {
      setHeard(''); setState('listening'); setWakeMode(true)
      later(() => { if (wakeModeRef.current) { setWakeMode(false); fail(MISHEARD) } }, WAKE_FOLLOW_MS)
      return
    }
    handleText(text, confidence, false)
  }, [handleText, later, fail, clearTimers])
  const onWakeRef = useRef(onWakeTranscript)
  onWakeRef.current = onWakeTranscript

  const stopWake = useCallback(() => {
    if (wakeRestart.current) { clearTimeout(wakeRestart.current); wakeRestart.current = null }
    const rec = wakeRecRef.current
    wakeRecRef.current = null
    rec?.abort()
  }, [])

  const startWake = useCallback(() => {
    wakeRestart.current = null
    if (wakeRecRef.current || !activeRef.current) return
    const rec = createRecognition({ continuous: true })
    if (!rec) return
    wakeRecRef.current = rec
    const startedAt = Date.now()
    const scheduleRestart = () => {
      if (!activeRef.current || wakeRestart.current) return
      // 정상 종료(브라우저가 1분쯤마다 끊음)는 바로, 오류가 이어지면 점점 늦게 (최대 10초)
      const delay = Math.min(10_000, 300 * 2 ** wakeFailures.current)
      wakeRestart.current = setTimeout(startWake, delay)
    }
    rec.onresult = (e) => {
      wakeFailures.current = 0
      for (const r of finalTranscripts(e)) onWakeRef.current(r.text, r.confidence)
    }
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture') {
        setBlocked(true)
        toast.error('마이크를 쓸 수 없어 호출어 대기를 멈췄어요.')
      } else if (e.error !== 'no-speech' && e.error !== 'aborted') {
        wakeFailures.current = Math.min(wakeFailures.current + 1, 6)
      }
    }
    rec.onend = () => {
      if (wakeRecRef.current !== rec) return
      wakeRecRef.current = null
      if (Date.now() - startedAt > 5000) wakeFailures.current = 0
      scheduleRestart()
    }
    try { rec.start() } catch {
      wakeRecRef.current = null
      wakeFailures.current = Math.min(wakeFailures.current + 1, 6)
      scheduleRestart()
    }
  }, [])

  useEffect(() => {
    if (want && !paused) startWake()
    else stopWake()
  }, [want, paused, startWake, stopWake])
  useEffect(() => stopWake, [stopWake])
  // 설정에서 다시 켜면 막힘 상태를 푼다
  useEffect(() => { if (!wakeWordEnabled || !voiceEnabled) setBlocked(false) }, [wakeWordEnabled, voiceEnabled])

  // ── 마이크 버튼 ─────────────────────────────────────────────────────────
  const start = useCallback(() => {
    if (open) return close()
    clearTimers()
    setOpen(true); setHeard(''); setReply(''); setPending(null); setState('listening'); setWakeMode(false)
    const useMic = voiceEnabled && supported
    if (!useMic) {
      setDemo(true)
      const cmd = nextDemoCommand()
      later(() => { setHeard(cmd); setState('recognized'); later(() => handleText(cmd, undefined, true), 500) }, 1400)
      return
    }
    setDemo(false)
    // 호출어 인식기가 돌고 있으면 먼저 멈춘다 (인식기는 하나만 쓸 수 있다)
    const wasWake = !!wakeRecRef.current
    stopWake()
    later(() => {
      const rec = createRecognition()
      if (!rec) return fail(MISHEARD)
      oneShotRef.current = rec
      let got = false
      rec.onresult = (e) => {
        const r = finalTranscripts(e)[0]
        if (!r || got) return
        got = true
        setHeard(r.text); setState('recognized')
        later(() => handleText(r.text, r.confidence, false), 300)
      }
      rec.onerror = (e) => { if (e.error !== 'aborted') { got = true; fail(MISHEARD) } }
      // 아무 말 없이 끝나면 (오류 없이 끝나는 브라우저도 있다)
      rec.onend = () => { if (oneShotRef.current === rec) oneShotRef.current = null; if (!got) fail(MISHEARD) }
      try { rec.start() } catch { oneShotRef.current = null; fail(MISHEARD) }
    }, wasWake ? 250 : 0)
  }, [open, close, voiceEnabled, supported, later, handleText, stopWake, fail, clearTimers])

  const confirm = useCallback(() => {
    const id = voiceIdRef.current
    const svc = homeRef.current.source.voice
    if (id && confirmingRef.current && svc) {
      confirmingRef.current = false
      setPending(null); setState('processing'); setProgress('실행하고 있어요')
      svc.confirm(id, true).catch(() => fail(UNAVAILABLE))
      return
    }
    localRunRef.current?.()
  }, [fail])

  // 개발 서버에서만: 마이크 없이 문장을 넣어 보는 시험 창구 (빌드에는 들어가지 않는다)
  const testRef = useRef({ handleText, onWakeTranscript })
  testRef.current = { handleText, onWakeTranscript }
  useEffect(() => {
    if (!import.meta.env.DEV) return
    const w = window as unknown as { __homevisVoice?: unknown }
    w.__homevisVoice = {
      /** 마이크 버튼으로 말한 것처럼 */
      say: (text: string) => { setOpen(true); setDemo(false); setReply(''); setPending(null); testRef.current.handleText(text, 0.9, false) },
      /** 호출어 대기 중에 들은 것처럼 */
      hear: (text: string) => testRef.current.onWakeTranscript(text, 0.9),
    }
    return () => { delete w.__homevisVoice }
  }, [])

  return {
    open, state, demo, heard, reply, progress, errorText, pending,
    wakeListening: want && !paused,
    start, close, confirm, cancel: close,
  }
}
