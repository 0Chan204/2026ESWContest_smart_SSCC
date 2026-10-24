import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { usePreferences } from '@/store/PreferencesContext'
import { useHome } from '@/store/HomeStore'
import { describeBathroom, describeKitchen, HERO_TITLE } from '@/lib/rooms'
import { withObjectParticle } from '@/lib/korean'
import { matchCommand, nextDemoCommand, type VoiceIntent } from './commands'
import { createRecognition, type SpeechRecognitionLike } from './speech'

export type VoiceState = 'idle' | 'listening' | 'recognized' | 'processing' | 'completed' | 'error'

export interface VoiceController {
  open: boolean
  state: VoiceState
  demo: boolean
  heard: string
  reply: string
  pending: { message: string; run: () => void } | null
  start: () => void
  close: () => void
  confirm: () => void
}

const HIDE_MS = 3200

/**
 * 음성 상태 머신. 원칙:
 * 1) 음성으로 되는 조작은 화면 버튼으로도 된다 (Voice-only 기능 없음)
 * 2) 기기 상태를 바꾸는 명령은 확인을 받고 실행한다
 * 3) 마이크는 설정에서 켠 경우에만 요청한다 (기본 꺼짐 — 음성이 외부로 전송될 수 있음)
 */
export function useVoice(): VoiceController {
  const navigate = useNavigate()
  const { voiceEnabled } = usePreferences()
  const home = useHome()
  const homeRef = useRef(home)
  homeRef.current = home

  const [open, setOpen] = useState(false)
  const [state, setState] = useState<VoiceState>('idle')
  const [demo, setDemo] = useState(false)
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')
  const [pending, setPending] = useState<VoiceController['pending']>(null)
  const recRef = useRef<SpeechRecognitionLike | null>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  const later = useCallback((fn: () => void, ms: number) => { timers.current.push(setTimeout(fn, ms)) }, [])
  const close = useCallback(() => {
    timers.current.forEach(clearTimeout); timers.current = []
    recRef.current?.abort(); recRef.current = null
    setOpen(false); setState('idle'); setHeard(''); setReply(''); setPending(null)
  }, [])
  useEffect(() => () => { timers.current.forEach(clearTimeout); recRef.current?.abort() }, [])

  const finish = useCallback((text: string) => {
    setReply(text); setState('completed'); later(close, HIDE_MS)
  }, [later, close])

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
    const device = h.devices.find((d) => d.kind === intent.device && d.room === intent.room)
    if (!device) return finish('그 기기는 아직 등록되어 있지 않아요.')
    if (!device.online) return finish('지금은 그 기기와 연결이 끊겨 있어요.')
    setState('recognized')
    setPending({
      message: intent.confirm,
      run: () => {
        void h.controlDevice(device.id, { on: intent.on })
        setPending(null)
        finish(`${withObjectParticle(device.name)} ${intent.on ? '켰어요' : '껐어요'}.`)
      },
    })
  }, [navigate, finish])

  const process = useCallback((text: string) => {
    setState('processing')
    later(() => {
      const intent = matchCommand(text)
      if (!intent) { setState('error'); later(close, HIDE_MS); return }
      run(intent)
    }, 600)
  }, [later, close, run])

  const start = useCallback(() => {
    if (open) return close()
    setOpen(true); setHeard(''); setReply(''); setPending(null); setState('listening')
    const rec = voiceEnabled ? createRecognition() : null
    if (!rec) {
      setDemo(true)
      const cmd = nextDemoCommand()
      later(() => { setHeard(cmd); setState('recognized'); later(() => process(cmd), 500) }, 1400)
      return
    }
    setDemo(false)
    recRef.current = rec
    rec.onresult = (e) => {
      const text = e.results[0]?.[0]?.transcript ?? ''
      setHeard(text); setState('recognized'); later(() => process(text), 400)
    }
    rec.onerror = () => { setState('error'); later(close, HIDE_MS) }
    try { rec.start() } catch { recRef.current = null; setState('error'); later(close, HIDE_MS) }
  }, [open, close, voiceEnabled, later, process])

  const confirm = useCallback(() => pending?.run(), [pending])
  return { open, state, demo, heard, reply, pending, start, close, confirm }
}
