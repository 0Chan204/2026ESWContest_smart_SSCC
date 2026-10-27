import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useHome } from '@/store/HomeStore'
import { useSpeech } from '@/hooks/useSpeech'

/**
 * AI 판정 엔진의 안내 문장(ai.announcement · weather.briefing)을 화면에 띄우고 음성으로 읽는다.
 * 음성은 설정 > 음성 안내가 켜져 있고 기기 내장 한국어 음성이 있을 때만 (외부 음성 서비스 사용 안 함).
 */
export function AnnouncementSpeaker() {
  const { announcement } = useHome()
  const speak = useSpeech()
  const shown = useRef<string | null>(null)
  useEffect(() => {
    if (!announcement || shown.current === announcement.id) return
    shown.current = announcement.id
    toast(announcement.text, { duration: 8000 })
    speak(announcement.text)
  }, [announcement, speak])
  return null
}
