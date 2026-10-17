import { useState, type ReactNode } from 'react'
import { Minus, Plus } from 'lucide-react'
import { useNow } from '@/hooks/useNow'
import { formatClock, formatToday } from '@/lib/format'
import {
  FONT_SCALE_MAX, FONT_SCALE_MIN, FONT_SCALE_STEP, usePreferences,
} from '@/store/PreferencesContext'
import { StatusBanner } from '@/features/alerts/StatusBanner'
import { useHome } from '@/store/HomeStore'
import { weatherIcon } from '@/components/WeatherIcon'
import { WeatherSheet } from '@/features/weather/WeatherSheet'
import { cn } from '@/lib/cn'

/** 화면 상단: 큰 제목(iOS Large Title) + 월패드 시계. 어르신 모드는 글자 크기 조절 추가 */
export function PageHeader({ title, right }: { title: string; right?: ReactNode }) {
  const { elderly } = usePreferences()
  const now = new Date(useNow(10_000))

  return (
    <>
      <header className="flex shrink-0 items-end justify-between gap-6 px-5 pt-5 md:px-8 md:pt-6 wall:short:pt-4">
        <div className="min-w-0">
          <p className={cn('font-semibold text-ink-3', elderly ? 'text-lg' : 'text-[0.8125rem]')}>{formatToday(now)}</p>
          <h1 className={cn('font-bold tracking-[-0.02em] text-ink', elderly ? 'text-[2.5rem]' : 'text-[2.125rem]', 'leading-tight')}>{title}</h1>
        </div>
        <div className="flex shrink-0 items-center gap-4 md:gap-6">
          {right}
          {elderly && <FontScaleControl />}
          <WeatherNow hour={now.getHours()} />
          <p className={cn('tabular leading-none font-light tracking-[-0.03em] text-ink', elderly ? 'text-[3.25rem]' : 'text-[2.75rem]')}
            aria-label={`현재 시각 ${formatClock(now)}`}>
            {formatClock(now)}
          </p>
        </div>
      </header>
      <StatusBanner />
    </>
  )
}

/** 시계 옆 날씨: 아이콘 · 기온 · 상태(최고/최저). 누르면 자세히. 받아 둔 날씨가 없으면 안 보인다 */
function WeatherNow({ hour }: { hour: number }) {
  const { weather } = useHome()
  const { elderly } = usePreferences()
  const [open, setOpen] = useState(false)
  if (!weather) return null
  const { Icon, color } = weatherIcon(weather.code, hour)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title={weather.text}
        aria-label={`날씨 ${weather.location} ${weather.condition} ${Math.round(weather.temperature)}도 · 자세히 보기`}
        className="press -mx-2 flex items-center gap-2.5 rounded-xl px-2 py-1 text-left hover:bg-fill">
        <Icon className={cn('shrink-0', elderly ? 'h-10 w-10' : 'h-8 w-8', color)} strokeWidth={1.6} aria-hidden="true" />
        <span className="block leading-tight">
          <span className={cn('tabular block font-light tracking-[-0.02em] text-ink', elderly ? 'text-[2rem]' : 'text-[1.75rem]')}>
            {Math.round(weather.temperature)}°
          </span>
          <span className={cn('hidden whitespace-nowrap text-ink-3 sm:block', elderly ? 'text-base' : 'text-[0.8125rem]')}>
            {weather.condition}
            {!elderly && weather.max !== undefined && weather.min !== undefined && ` · ${Math.round(weather.max)}° / ${Math.round(weather.min)}°`}
            {weather.stale && ' · 지난 정보'}
          </span>
        </span>
      </button>
      <WeatherSheet open={open} onClose={() => setOpen(false)} />
    </>
  )
}

export function FontScaleControl() {
  const { fontScale, setFontScale } = usePreferences()
  const btn = 'press flex h-11 w-11 items-center justify-center rounded-full text-ink disabled:opacity-30'
  return (
    <div className="flex items-center gap-1 rounded-full bg-fill p-1" role="group" aria-label="글자 크기">
      <button type="button" className={btn} aria-label="글자 작게" disabled={fontScale <= FONT_SCALE_MIN}
        onClick={() => setFontScale(fontScale - FONT_SCALE_STEP)}>
        <Minus className="h-4 w-4" strokeWidth={2.4} aria-hidden="true" />
      </button>
      <span className="tabular min-w-16 px-1 text-center text-sm font-semibold whitespace-nowrap text-ink">가 {fontScale}%</span>
      <button type="button" className={btn} aria-label="글자 크게" disabled={fontScale >= FONT_SCALE_MAX}
        onClick={() => setFontScale(fontScale + FONT_SCALE_STEP)}>
        <Plus className="h-4 w-4" strokeWidth={2.4} aria-hidden="true" />
      </button>
    </div>
  )
}
