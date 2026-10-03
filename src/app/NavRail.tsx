import { NavLink } from 'react-router'
import { Bath, ClipboardList, FlaskConical, House, Mic, Settings, UtensilsCrossed } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { RISK_TONE } from '@/lib/labels'
import type { Risk } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 왼쪽 내비게이션 레일 (One UI 태블릿 · 월패드 방식).
 * 가로 화면에서 세로 공간을 아끼고, 음성 버튼을 레일 하단에 고정해 콘텐츠를 가리지 않는다.
 */
export function NavRail({ onVoice, voiceActive, onDemo }: { onVoice: () => void; voiceActive: boolean; onDemo: () => void }) {
  const { elderly } = usePreferences()
  const { kitchenRisk, bathroomRisk, source } = useHome()

  const items: { to: string; label: string; Icon: typeof House; risk?: Risk }[] = [
    { to: '/home', label: '홈', Icon: House },
    { to: '/kitchen', label: '주방', Icon: UtensilsCrossed, risk: kitchenRisk },
    { to: '/bathroom', label: '욕실', Icon: Bath, risk: bathroomRisk },
    { to: '/history', label: elderly ? '안전 기록' : '기록', Icon: ClipboardList },
    { to: '/settings', label: '설정', Icon: Settings },
  ]

  return (
    <nav
      aria-label="주요 메뉴"
      className={cn('flex h-full shrink-0 flex-col items-center bg-surface py-5', elderly ? 'w-[124px]' : 'w-[100px]')}
    >
      <div className="mb-6 flex h-10 w-10 items-center justify-center rounded-xl bg-ink" aria-label="HomeVIS">
        <House className="h-5 w-5 text-white" strokeWidth={2.2} aria-hidden="true" />
      </div>

      <ul className="flex w-full flex-1 flex-col gap-1 px-2.5">
        {items.map(({ to, label, Icon, risk }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) => cn(
                'group flex w-full flex-col items-center gap-1 rounded-2xl py-2.5 transition-colors',
                isActive ? 'text-brand' : 'text-ink-2 hover:text-ink',
              )}
            >
              {({ isActive }) => (
                <>
                  <span className={cn(
                    'relative flex items-center justify-center rounded-full transition-colors',
                    elderly ? 'h-11 w-16' : 'h-9 w-14',
                    isActive ? 'bg-brand-soft' : 'group-hover:bg-sunken',
                  )}>
                    <Icon className={elderly ? 'h-6 w-6' : 'h-[22px] w-[22px]'} strokeWidth={isActive ? 2.2 : 1.8} aria-hidden="true" />
                    {risk && risk !== 'normal' && (
                      <span className={cn('absolute top-1 right-2.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface', RISK_TONE[risk].strong)}
                        aria-label={`${label} 확인 필요`} />
                    )}
                  </span>
                  <span className={cn('font-semibold', elderly ? 'text-base' : 'text-[0.8125rem]')}>{label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="flex flex-col items-center gap-2 px-2.5">
        {source.demo && (
          <button type="button" onClick={onDemo} aria-label="시연 도구"
            className="flex flex-col items-center gap-1 rounded-2xl px-2 py-2 text-ink-3 hover:bg-sunken hover:text-ink-2">
            <FlaskConical className="h-5 w-5" aria-hidden="true" />
            <span className="text-[0.6875rem] font-semibold">시연</span>
          </button>
        )}
        <button
          type="button"
          onClick={onVoice}
          aria-label="음성으로 말하기"
          aria-expanded={voiceActive}
          className={cn(
            'flex flex-col items-center justify-center gap-1 rounded-2xl text-white transition-colors',
            elderly ? 'h-[76px] w-[88px]' : 'h-16 w-16',
            voiceActive ? 'bg-brand-dark' : 'bg-brand hover:bg-brand-dark',
          )}
        >
          <Mic className={elderly ? 'h-7 w-7' : 'h-6 w-6'} aria-hidden="true" />
          {elderly && <span className="text-sm font-bold">말하기</span>}
        </button>
      </div>
    </nav>
  )
}
