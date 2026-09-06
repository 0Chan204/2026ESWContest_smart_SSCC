import { useState } from 'react'
import { Outlet } from 'react-router'
import { NavBar } from './NavBar'
import { ConnectionBanner } from './ConnectionBanner'
import { SettingsDrawer } from '@/features/settings/SettingsDrawer'
import { WarningModal } from '@/features/safety/WarningModal'
import { ResultModal } from '@/features/safety/ResultModal'
import { VoiceButton } from '@/features/voice/VoiceButton'
import { VoicePanel } from '@/features/voice/VoicePanel'
import { useVoice } from '@/features/voice/useVoice'

/**
 * 화면 골격.
 * 전체 높이를 flex 로 나눠 페이지 자체에 세로 스크롤이 생기지 않게 한다.
 */
export function AppShell() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const voice = useVoice()

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <NavBar onOpenSettings={() => setSettingsOpen(true)} />
      <ConnectionBanner />

      {/* 좌하단 플로팅 음성 버튼이 콘텐츠(테이블 행·버튼)를 가리지 않도록 하단 여백을 확보한다 */}
      <main className="min-h-0 flex-1 overflow-hidden pb-20">
        <Outlet />
      </main>

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <WarningModal />
      <ResultModal />

      <VoiceButton onStart={voice.start} active={voice.open} />
      {voice.open && <VoicePanel voice={voice} />}
    </div>
  )
}
