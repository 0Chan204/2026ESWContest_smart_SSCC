import { useState } from 'react'
import { Outlet } from 'react-router'
import { NavRail } from './NavRail'
import { ActionNoticeSheet } from '@/features/alerts/ActionNoticeSheet'
import { FallAlertSheet } from '@/features/alerts/FallAlertSheet'
import { DemoPanel } from '@/features/alerts/DemoPanel'
import { VoicePanel } from '@/features/voice/VoicePanel'
import { useVoice } from '@/features/voice/useVoice'

/** 태블릿 대시보드 골격: 왼쪽 레일 + 화면. 전체 높이를 고정해 페이지 스크롤이 생기지 않는다. */
export function AppShell() {
  const voice = useVoice()
  const [demoOpen, setDemoOpen] = useState(false)
  return (
    <div className="flex h-dvh overflow-hidden">
      <NavRail onVoice={voice.start} voiceActive={voice.open} onDemo={() => setDemoOpen(true)} />
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
      <ActionNoticeSheet />
      <FallAlertSheet />
      <DemoPanel open={demoOpen} onClose={() => setDemoOpen(false)} />
      {voice.open && <VoicePanel voice={voice} />}
    </div>
  )
}
