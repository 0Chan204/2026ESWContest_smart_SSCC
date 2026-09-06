import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import { ROOM_KEY } from '@/lib/appliance'
import { matchCommand, nextDemoCommand, type VoiceIntent } from './commands'
import { createRecognition, type SpeechRecognitionLike } from './speech'

export type VoiceState =
  | 'idle' | 'listening' | 'recognized' | 'processing' | 'completed' | 'error'

export interface PendingConfirm {
  message: string
  run: () => void
}

export interface VoiceController {
  open: boolean
  state: VoiceState
  /** 실제 마이크가 아니라 데모 시뮬레이션으로 동작 중인지 */
  demo: boolean
  recognized: string
  reply: string
  pending: PendingConfirm | null
  start: () => void
  close: () => void
  confirm: () => void
  cancelConfirm: () => void
}

const REPLY_HIDE_MS = 2600

/**
 * 음성 상태 머신.
 *
 * - 사용자가 설정에서 켠 경우에만 실제 마이크(Web Speech API)를 사용한다.
 * - 꺼져 있거나 미지원 브라우저면 데모 시뮬레이션으로 동일한 상태 전이를 보여준다.
 * - 상태를 바꾸는 명령은 반드시 확인 단계를 거친다.
 */
export function useVoice(): VoiceController {
  const navigate = useNavigate()
  const { t, voiceEnabled } = usePreferences()
  const { applianceById, setPower } = useHomeState()

  const [open, setOpen] = useState(false)
  const [state, setState] = useState<VoiceState>('idle')
  const [demo, setDemo] = useState(false)
  const [recognized, setRecognized] = useState('')
  const [reply, setReply] = useState('')
  const [pending, setPending] = useState<PendingConfirm | null>(null)

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])

  const clearTimers = useCallback(() => {
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
  }, [])

  const later = useCallback((fn: () => void, ms: number) => {
    timersRef.current.push(setTimeout(fn, ms))
  }, [])

  const close = useCallback(() => {
    clearTimers()
    recognitionRef.current?.abort()
    recognitionRef.current = null
    setOpen(false)
    setState('idle')
    setRecognized('')
    setReply('')
    setPending(null)
  }, [clearTimers])

  useEffect(() => () => {
    clearTimers()
    recognitionRef.current?.abort()
  }, [clearTimers])

  const runIntent = useCallback(
    (intent: VoiceIntent) => {
      if (intent.kind === 'navigate') {
        navigate(intent.route)
        setReply(t(intent.replyKey))
        setState('completed')
        later(close, REPLY_HIDE_MS)
        return
      }

      const appliance = applianceById(intent.applianceId)
      // 제어를 지원하지 않는 기기는 음성으로도 조작할 수 없다.
      if (!appliance || !appliance.supportsControl) {
        setState('error')
        later(close, REPLY_HIDE_MS)
        return
      }

      // 상태를 바꾸는 명령은 즉시 실행하지 않고 확인을 받는다.
      setState('recognized')
      setPending({
        message: t(intent.confirmKey, { room: t(ROOM_KEY[appliance.room]) }),
        run: () => {
          setPower(intent.applianceId, intent.power)
          setPending(null)
          setReply(t(intent.replyKey))
          setState('completed')
          later(close, REPLY_HIDE_MS)
        },
      })
    },
    [navigate, t, applianceById, setPower, later, close],
  )

  const process = useCallback(
    (text: string) => {
      setState('processing')
      later(() => {
        const intent = matchCommand(text)
        if (!intent) {
          setState('error')
          later(close, REPLY_HIDE_MS)
          return
        }
        runIntent(intent)
      }, 700)
    },
    [later, close, runIntent],
  )

  const startDemo = useCallback(() => {
    setDemo(true)
    const picked = nextDemoCommand()
    later(() => {
      setRecognized(picked)
      setState('recognized')
      later(() => process(picked), 600)
    }, 1500)
  }, [later, process])

  const start = useCallback(() => {
    clearTimers()
    setOpen(true)
    setRecognized('')
    setReply('')
    setPending(null)
    setState('listening')

    // 설정에서 꺼져 있으면 마이크를 아예 요청하지 않는다.
    const recognition = voiceEnabled ? createRecognition() : null
    if (!recognition) {
      startDemo()
      return
    }

    setDemo(false)
    recognitionRef.current = recognition
    recognition.onresult = (event) => {
      const text = event.results[0]?.[0]?.transcript ?? ''
      setRecognized(text)
      setState('recognized')
      later(() => process(text), 500)
    }
    recognition.onerror = () => {
      setState('error')
      later(close, REPLY_HIDE_MS)
    }
    try {
      recognition.start()
    } catch {
      recognitionRef.current = null
      startDemo()
    }
  }, [voiceEnabled, clearTimers, startDemo, later, process, close])

  const confirm = useCallback(() => pending?.run(), [pending])
  const cancelConfirm = useCallback(() => {
    setPending(null)
    close()
  }, [close])

  return { open, state, demo, recognized, reply, pending, start, close, confirm, cancelConfirm }
}
