import { Navigate, Route, Routes } from 'react-router'
import { Toaster } from 'sonner'
import { AppShell } from './AppShell'
import { ModeSelect } from '@/features/onboarding/ModeSelect'
import { HomePage } from '@/features/home/HomePage'
import { KitchenPage } from '@/features/kitchen/KitchenPage'
import { BathroomPage } from '@/features/bathroom/BathroomPage'
import { HistoryPage } from '@/features/history/HistoryPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { FallConfirmPage } from '@/features/fall/FallConfirmPage'
import { HomeStoreProvider, useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'

/**
 * 두 종류의 화면:
 *  - /fall/:id  보호자 휴대폰에서 문자 링크로 여는 단독 모바일 페이지 (모드 선택·대시보드 데이터 없음)
 *  - 그 외      가정용 태블릿 대시보드 (1280×800 · 1440×900 가로)
 */
export default function App() {
  return (
    <Routes>
      <Route path="/fall/:incidentId" element={<FallConfirmPage />} />
      <Route path="*" element={<Dashboard />} />
    </Routes>
  )
}

function Dashboard() {
  const { mode } = usePreferences()
  if (mode === null) return <ModeSelect />
  // 대시보드 데이터·시뮬레이터는 대시보드에서만 띄운다 (보호자 페이지 탭과 분리)
  return (
    <HomeStoreProvider>
      <DashboardRoutes />
      <Toaster position="bottom-right" richColors duration={3000} />
    </HomeStoreProvider>
  )
}

function DashboardRoutes() {
  const { ready } = useHome()
  if (!ready) return <div className="flex h-dvh items-center justify-center text-ink-3">불러오는 중…</div>
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/home" element={<HomePage />} />
        <Route path="/kitchen" element={<KitchenPage />} />
        <Route path="/bathroom" element={<BathroomPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/home" replace />} />
    </Routes>
  )
}
