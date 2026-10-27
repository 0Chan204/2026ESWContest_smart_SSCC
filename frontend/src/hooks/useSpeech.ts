import { useCallback } from 'react'
import { usePreferences } from '@/store/PreferencesContext'

/**
 * 위험 알림 음성 안내 (TTS).
 * 개인정보·과금 방지를 위해 기기에 내장된(localService) 한국어 음성만 사용한다.
 * 내장 음성이 없으면 아무 것도 하지 않는다 (네트워크 음성으로 대체하지 않음).
 */
export function useSpeech() {
  const { ttsEnabled } = usePreferences()
  return useCallback((text: string | undefined) => {
    if (!ttsEnabled || !text || typeof window === 'undefined' || !('speechSynthesis' in window)) return
    const synth = window.speechSynthesis
    const voice = synth.getVoices().find((v) => v.lang.startsWith('ko') && v.localService)
    if (!voice) return
    synth.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.voice = voice
    u.lang = voice.lang
    u.rate = 0.95
    synth.speak(u)
  }, [ttsEnabled])
}
