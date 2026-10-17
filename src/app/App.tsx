import { Navigate, Route, Routes } from 'react-router'
import { Toaster } from 'sonner'
import { AppShell } from './AppShell'
import { ModeSelect } from '@/features/onboarding/ModeSelect'
import { ConsentDialog } from '@/features/onboarding/ConsentDialog'
import { HomePage } from '@/features/home/HomePage'
import { KitchenPage } from '@/features/kitchen/KitchenPage'
import { BathroomPage } from '@/features/bathroom/BathroomPage'
import { HistoryPage } from '@/features/history/HistoryPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { FallConfirmPage } from '@/features/fall/FallConfirmPage'
import { HomeStoreProvider, useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useApplyTheme } from '@/hooks/useApplyTheme'
import { useWakeLock } from '@/hooks/useWakeLock'

/**
 * 두 종류의 화면:
 *  - /fall/:id  보호자 휴대폰에서 문자 링크로 여는 단독 모바일 페이지 (항상 라이트 — 야외 가독성)
 *  - 그 외      가정용 대시보드 (월패드 1280×720 이상 한 화면, 그보다 작으면 세로 스크롤)
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
  const { mode, resolvedTheme, consentAnswered } = usePreferences()
  useApplyTheme(resolvedTheme)
  useWakeLock()   // 월패드처럼 켜 두는 화면 — 꺼지지 않게
  if (mode === null) return <ModeSelect />
  // 대시보드 데이터·시뮬레이터는 대시보드에서만 띄운다 (보호자 페이지 탭과 분리)
  return (
    <HomeStoreProvider>
      <DashboardRoutes />
      {!consentAnswered && <ConsentDialog />}
      <Toaster position="bottom-right" richColors theme={resolvedTheme} duration={3000} />
    </HomeStoreProvider>
  )
}

function DashboardRoutes() {
  const { ready, loadError, retryLoad } = useHome()
  if (!ready && loadError) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-[1.25rem] font-semibold text-ink">서버에 연결하지 못했어요</p>
        <p className="max-w-md text-[0.9375rem] text-ink-2">{loadError}</p>
        <button type="button" onClick={retryLoad} className="press mt-2 min-h-11 rounded-[12px] bg-brand px-5 font-semibold text-white">다시 시도</button>
      </div>
    )
  }
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
