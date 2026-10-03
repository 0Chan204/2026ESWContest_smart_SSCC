import type { ReactNode } from 'react'
import { Minus, Plus, Wifi, WifiOff } from 'lucide-react'
import { useNow } from '@/hooks/useNow'
import { formatClock, formatToday } from '@/lib/format'
import { useHome } from '@/store/HomeStore'
import {
  FONT_SCALE_MAX, FONT_SCALE_MIN, FONT_SCALE_STEP, usePreferences,
} from '@/store/PreferencesContext'
import { StatusBanner } from '@/features/alerts/StatusBanner'
import { cn } from '@/lib/cn'

/** 각 화면 상단: 제목 + 날짜·시각 + 기기 연결 상태 (어르신 모드는 글자 크기 조절 추가) */
export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  const { elderly } = usePreferences()
  const now = useNow(10_000)
  const { devices, onlineCount } = useHome()
  const allOnline = onlineCount === devices.length

  return (
    <>
    <header className="flex shrink-0 items-end justify-between gap-6 px-8 pt-6">
      <div className="min-w-0">
        <h1 className={cn('font-bold tracking-tight text-ink', elderly ? 'text-4xl' : 'text-[1.75rem]')}>{title}</h1>
        {subtitle && <p className={cn('mt-1 text-ink-2', elderly ? 'text-lg' : 'text-[0.9375rem]')}>{subtitle}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-5">
        {right}
        {elderly && <FontScaleControl />}
        <div className="text-right">
          <p className={cn('tabular font-semibold text-ink', elderly ? 'text-2xl' : 'text-xl')}>{formatClock(new Date(now))}</p>
          <p className="text-[0.8125rem] text-ink-3">{formatToday(new Date(now))}</p>
        </div>
        <span className={cn(
          'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[0.8125rem] font-semibold',
          allOnline ? 'bg-sunken text-ink-2' : 'bg-warn-soft text-warn',
        )}>
          {allOnline ? <Wifi className="h-4 w-4" aria-hidden="true" /> : <WifiOff className="h-4 w-4" aria-hidden="true" />}
          기기 {onlineCount}/{devices.length}
        </span>
      </div>
    </header>
    <StatusBanner />
    </>
  )
}

export function FontScaleControl() {
  const { fontScale, setFontScale } = usePreferences()
  const btn = 'flex h-11 w-11 items-center justify-center rounded-full text-ink hover:bg-line disabled:opacity-30'
  return (
    <div className="flex items-center gap-1 rounded-full bg-sunken p-1" role="group" aria-label="글자 크기">
      <button type="button" className={btn} aria-label="글자 작게" disabled={fontScale <= FONT_SCALE_MIN}
        onClick={() => setFontScale(fontScale - FONT_SCALE_STEP)}>
        <Minus className="h-4 w-4" aria-hidden="true" />
      </button>
      <span className="tabular min-w-16 px-1 text-center text-sm font-bold whitespace-nowrap text-ink">가 {fontScale}%</span>
      <button type="button" className={btn} aria-label="글자 크게" disabled={fontScale >= FONT_SCALE_MAX}
        onClick={() => setFontScale(fontScale + FONT_SCALE_STEP)}>
        <Plus className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  )
}
