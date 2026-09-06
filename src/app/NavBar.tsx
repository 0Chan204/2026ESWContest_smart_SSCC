import { NavLink } from 'react-router'
import { Bath, ClipboardList, Home, Settings, Sun, UtensilsCrossed } from 'lucide-react'
import { FontScaleControl } from '@/features/settings/FontScaleControl'
import { useClock } from '@/hooks/useClock'
import { formatClock } from '@/lib/format'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'
import type { TKey } from '@/i18n'

const TABS: { to: string; labelKey: TKey; elderlyLabelKey: TKey; Icon: typeof Home }[] = [
  { to: '/home', labelKey: 'nav.home', elderlyLabelKey: 'nav.home', Icon: Home },
  { to: '/kitchen', labelKey: 'nav.kitchen', elderlyLabelKey: 'nav.kitchen', Icon: UtensilsCrossed },
  { to: '/bathroom', labelKey: 'nav.bathroom', elderlyLabelKey: 'nav.bathroom', Icon: Bath },
  { to: '/history', labelKey: 'nav.history', elderlyLabelKey: 'nav.history.elderly', Icon: ClipboardList },
]

/**
 * 상단 글로벌 네비게이션.
 * 공간 탭은 배열만 늘리면 침실/거실 등으로 확장된다.
 */
export function NavBar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { t, elderly } = usePreferences()
  const now = useClock()

  return (
    <header
      className="shrink-0 border-b border-gray-200/80 bg-white shadow-sm"
      style={{ height: 'var(--nav-h)' }}
    >
      <div className="mx-auto flex h-full max-w-[1400px] items-center justify-between gap-4 px-6">
        <div className="flex min-w-[110px] items-center gap-2.5">
          <span className="bg-brand flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
            <Home className="h-3.5 w-3.5 text-white" aria-hidden="true" />
          </span>
          <span className={cn('text-brand font-bold tracking-tight', elderly ? 'text-xl' : 'text-lg')}>
            HomeVIS
          </span>
        </div>

        <nav aria-label="주요 화면" className="flex items-center gap-0.5 rounded-xl bg-gray-100 p-1">
          {TABS.map(({ to, labelKey, elderlyLabelKey, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-1.5 rounded-lg font-medium transition-all',
                  elderly ? 'min-h-14 px-5 text-base' : 'min-h-11 px-4 text-sm',
                  isActive ? 'text-brand bg-white shadow-sm' : 'text-gray-600 hover:text-gray-900',
                )
              }
            >
              <Icon className={elderly ? 'h-5 w-5' : 'h-4 w-4'} aria-hidden="true" />
              {t(elderly ? elderlyLabelKey : labelKey)}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center justify-end gap-3">
          {!elderly && (
            <>
              <span className="flex items-center gap-1.5 text-sm text-gray-600">
                <Sun className="h-4 w-4 text-yellow-500" aria-hidden="true" />
                {t('nav.weather')}
              </span>
              <span className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-700">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" aria-hidden="true" />
                {t('nav.connected')}
              </span>
            </>
          )}

          {elderly && <FontScaleControl compact />}

          <span className="tabular text-sm font-semibold text-gray-700">{formatClock(now)}</span>

          <button
            type="button"
            onClick={onOpenSettings}
            aria-label={t('nav.settings')}
            className="flex h-11 w-11 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800"
          >
            <Settings className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  )
}
