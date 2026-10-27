import { useState } from 'react'
import { Outlet } from 'react-router'
import { BottomBar, NavRail } from './NavRail'
import { ActionNoticeSheet } from '@/features/alerts/ActionNoticeSheet'
import { FallAlertSheet } from '@/features/alerts/FallAlertSheet'
import { DemoPanel } from '@/features/alerts/DemoPanel'
import { AnnouncementSpeaker } from '@/features/alerts/AnnouncementSpeaker'
import { VoicePanel } from '@/features/voice/VoicePanel'
import { useVoice } from '@/features/voice/useVoice'

/**
 * 대시보드 골격.
 *  - 월패드(1180×660 이상): 왼쪽 레일 + 한 화면 고정 (페이지 스크롤 없음)
 *  - 세로 태블릿(768px 이상): 왼쪽 레일 + 콘텐츠 세로 스크롤
 *  - 휴대폰: 하단 탭바 + 콘텐츠 세로 스크롤
 */
export function AppShell() {
  const voice = useVoice()
  const [demoOpen, setDemoOpen] = useState(false)
  return (
    <div className="flex h-dvh overflow-hidden">
      <NavRail onVoice={voice.start} voiceActive={voice.open} wakeListening={voice.wakeListening} onDemo={() => setDemoOpen(true)} />
      <main className="min-w-0 flex-1 overflow-y-auto pb-24 md:pb-0 wall:overflow-hidden">
        <Outlet />
      </main>
      <BottomBar onVoice={voice.start} voiceActive={voice.open} wakeListening={voice.wakeListening} onDemo={() => setDemoOpen(true)} />
      <ActionNoticeSheet />
      <FallAlertSheet />
      <AnnouncementSpeaker />
      <DemoPanel open={demoOpen} onClose={() => setDemoOpen(false)} />
      {voice.open && <VoicePanel voice={voice} />}
    </div>
  )
}
