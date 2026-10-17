import { Sheet } from '@/components/ui/Sheet'
import { ListGroup, ListRow } from '@/components/ui/List'
import { weatherIcon } from '@/components/WeatherIcon'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import type { HourlyWeather } from '@/types'
import { cn } from '@/lib/cn'

/** 이 확률 이상이면 '비 소식' 으로 보고 파란 글자로 표시 */
const RAIN_PCT = 30

/** 오후 3시 / 오전 9시 */
function koreanHour(iso: string): string {
  const h = new Date(iso).getHours()
  return `${h < 12 ? '오전' : '오후'} ${h % 12 === 0 ? 12 : h % 12}시`
}

/** 시간대별 예보로 만든 안내 한 줄: 언제부터 비가 오는지 (없으면 null) */
function rainLine(hourly: HourlyWeather[] | undefined): string | null {
  if (!hourly) return null
  const first = hourly.find((h) => (h.rainChance ?? 0) >= RAIN_PCT)
  if (!first) return null
  const soon = new Date(first.time).getTime() - Date.now() < 60 * 60_000
  return soon ? '지금 비 소식이 있어요. 외출할 때 우산을 챙기세요.' : `${koreanHour(first.time)}부터 비 소식이 있어요. 외출할 때 우산을 챙기세요.`
}

/**
 * 날씨 자세히 — 시계 옆 날씨를 누르면 열린다.
 * 지금 날씨 · 안내 한 줄(언제부터 비가 오는지) · 시간대별 예보 띠 · 체감/습도/강수. 그래프는 쓰지 않는다.
 * 어르신 모드는 시간대 띠 없이 큰 글씨 안내만.
 */
export function WeatherSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { weather } = useHome()
  const { elderly } = usePreferences()
  if (!open || !weather) return null
  const { Icon, color } = weatherIcon(weather.code, new Date().getHours())
  const deg = (v: number | undefined) => (v === undefined ? '–' : `${Math.round(v)}°`)
  const big = elderly
  const line = rainLine(weather.hourly) ?? weather.text

  return (
    <Sheet open onClose={onClose} width={elderly ? 600 : 520} title="날씨" subtitle={weather.location || undefined}>
      <div className="flex items-center gap-5 rounded-2xl bg-surface p-5">
        <Icon className={cn('h-16 w-16 shrink-0', color)} strokeWidth={1.4} aria-hidden="true" />
        <div className="min-w-0">
          <p className="tabular text-[3.5rem] leading-none font-extralight tracking-[-0.04em] text-ink">{Math.round(weather.temperature)}°</p>
          <p className={cn('mt-1 text-ink-2', big ? 'text-xl' : 'text-[1.0625rem]')}>
            {weather.condition}{weather.max !== undefined && weather.min !== undefined && ` · 최고 ${deg(weather.max)} 최저 ${deg(weather.min)}`}
          </p>
        </div>
      </div>

      {line && <p className={cn('mt-4 px-1 leading-relaxed text-ink', big ? 'text-2xl font-semibold' : 'text-[1rem]')}>{line}</p>}

      {/* 시간대별 예보 (가로 띠). 비 소식(30% 이상)만 파란 강수 확률 표시 */}
      {!elderly && weather.hourly && weather.hourly.length > 1 && (
        <div className="mt-6 overflow-x-auto rounded-xl bg-surface" role="list" aria-label="시간대별 예보">
          <div className="flex min-w-max px-2 py-3">
            {weather.hourly.map((h, i) => {
              const hour = new Date(h.time).getHours()
              const { Icon: HIcon, color: hColor } = weatherIcon(h.code, hour)
              const rainy = (h.rainChance ?? 0) >= RAIN_PCT
              return (
                <div key={h.time} role="listitem" className="flex w-[52px] flex-col items-center gap-1.5">
                  <span className={cn('text-[0.8125rem]', i === 0 ? 'font-semibold text-ink' : 'text-ink-3')}>{i === 0 ? '지금' : `${hour}시`}</span>
                  <HIcon className={cn('h-6 w-6', hColor)} strokeWidth={1.7} aria-hidden="true" />
                  <span className="tabular text-[1rem] text-ink">{Math.round(h.temperature)}°</span>
                  <span className={cn('tabular text-[0.75rem] font-medium text-brand-ink', !rainy && 'invisible')}>{Math.round(h.rainChance ?? 0)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <ListGroup className="mt-6"
        footer={weather.stale ? '인터넷 연결이 끊겨 마지막으로 받은 날씨를 보여주고 있어요.' : undefined}>
        <ListRow big={big} title="체감 온도" value={deg(weather.feels)} />
        <ListRow big={big} title="습도" value={weather.humidity === undefined ? '–' : `${Math.round(weather.humidity)}%`} />
        <ListRow big={big} title="오늘 비 올 확률" value={weather.rainChance === undefined ? '–' : `${Math.round(weather.rainChance)}%`} />
      </ListGroup>
    </Sheet>
  )
}
