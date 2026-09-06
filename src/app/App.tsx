import { Navigate, Route, Routes } from 'react-router'
import { Toaster } from 'sonner'
import { AppShell } from './AppShell'
import { ModeSelect } from '@/features/onboarding/ModeSelect'
import { HomePage } from '@/features/home/HomePage'
import { RoomPage } from '@/features/room/RoomPage'
import { HistoryPage } from '@/features/history/HistoryPage'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'

export default function App() {
  const { mode } = usePreferences()
  const { ready } = useHomeState()

  // 최초 진입 시 딱 한 번만 모드 선택 화면을 보여준다.
  if (mode === null) {
    return (
      <>
        <ModeSelect />
        <Toaster position="bottom-right" richColors duration={3000} />
      </>
    )
  }

  if (!ready) {
    return (
      <div className="flex h-dvh items-center justify-center text-sm text-gray-500">
        불러오는 중...
      </div>
    )
  }

  return (
    <>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/home" element={<HomePage />} />
          <Route path="/kitchen" element={<RoomPage room="kitchen" />} />
          <Route path="/bathroom" element={<RoomPage room="bathroom" />} />
          <Route path="/history" element={<HistoryPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/home" replace />} />
      </Routes>
      <Toaster position="bottom-right" richColors duration={3000} />
    </>
  )
}
