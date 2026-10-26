import { NavLink } from 'react-router'
import { Bath, ClipboardList, FlaskConical, House, Mic, Settings, UtensilsCrossed } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { RISK_TONE } from '@/lib/labels'
import type { Risk } from '@/types'
import { cn } from '@/lib/cn'

interface NavProps {
  onVoice: () => void
  voiceActive: boolean
  /** 호출어 대기 중 (마이크 켜짐) — 마이크 버튼에 주황 점과 글자로 알린다 */
  wakeListening: boolean
  onDemo: () => void
}

function useNavItems() {
  const { elderly } = usePreferences()
  const { kitchenRisk, bathroomRisk } = useHome()
  const items: { to: string; label: string; Icon: typeof House; risk?: Risk }[] = [
    { to: '/home', label: '홈', Icon: House },
    { to: '/kitchen', label: '주방', Icon: UtensilsCrossed, risk: kitchenRisk },
    { to: '/bathroom', label: '욕실', Icon: Bath, risk: bathroomRisk },
    { to: '/history', label: elderly ? '안전 기록' : '기록', Icon: ClipboardList },
    { to: '/settings', label: '설정', Icon: Settings },
  ]
  return items
}

function RiskDot({ risk, label }: { risk?: Risk; label: string }) {
  if (!risk || risk === 'normal') return null
  return (
    <span className={cn('absolute -top-0.5 -right-1 h-2.5 w-2.5 rounded-full ring-2 ring-canvas', RISK_TONE[risk].strong, risk === 'danger' && 'soft-pulse')}
      aria-label={`${label} 확인 필요`} />
  )
}

/**
 * 왼쪽 메뉴 (태블릿·월패드, 768px 이상). iPad 탭 막대처럼 선택된 항목만 파란 글자.
 * 음성 버튼은 아래에 고정해 콘텐츠를 가리지 않는다.
 */
export function NavRail({ onVoice, voiceActive, wakeListening, onDemo }: NavProps) {
  const { elderly } = usePreferences()
  const { source } = useHome()
  const items = useNavItems()

  return (
    <nav aria-label="주요 메뉴"
      className={cn('hidden h-full shrink-0 flex-col items-center border-r border-line bg-canvas pt-6 pb-5 md:flex', elderly ? 'w-[112px]' : 'w-[88px]')}>
      <p className="mb-5 text-[0.8125rem] font-bold tracking-[-0.01em] text-ink">HomeVIS</p>

      <ul className="flex w-full flex-1 flex-col gap-1.5 px-2">
        {items.map(({ to, label, Icon, risk }) => (
          <li key={to}>
            <NavLink to={to}
              className={({ isActive }) => cn('press flex w-full flex-col items-center gap-1 rounded-xl py-2.5',
                isActive ? 'bg-surface text-brand-ink' : 'text-ink-3 hover:text-ink')}>
              {({ isActive }) => (
                <>
                  <span className="relative">
                    <Icon className={elderly ? 'h-7 w-7' : 'h-6 w-6'} strokeWidth={isActive ? 2.2 : 1.8} aria-hidden="true" />
                    <RiskDot risk={risk} label={label} />
                  </span>
                  <span className={cn('font-medium', elderly ? 'text-base' : 'text-[0.75rem]')}>{label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="flex flex-col items-center gap-3">
        {source.demo && (
          <button type="button" onClick={onDemo} aria-label="시연 도구"
            className="press flex h-10 w-10 items-center justify-center rounded-full text-ink-3 hover:bg-fill">
            <FlaskConical className="h-5 w-5" aria-hidden="true" />
          </button>
        )}
        <VoiceButton onVoice={onVoice} voiceActive={voiceActive} wakeListening={wakeListening} elderly={elderly} />
        {wakeListening && <span className={cn('-mt-1 font-medium text-ink-3', elderly ? 'text-[0.875rem]' : 'text-[0.6875rem]')} aria-hidden="true">호출어 대기</span>}
      </div>
    </nav>
  )
}

function VoiceButton({ onVoice, voiceActive, wakeListening, elderly, compact = false }: {
  onVoice: () => void; voiceActive: boolean; wakeListening: boolean; elderly: boolean; compact?: boolean
}) {
  return (
    <button type="button" onClick={onVoice} aria-label={wakeListening ? '음성으로 말하기 · 호출어 대기 중' : '음성으로 말하기'} aria-expanded={voiceActive}
      className={cn('press relative flex items-center justify-center rounded-full text-white',
        compact ? 'h-12 w-12' : elderly ? 'h-[68px] w-[68px]' : 'h-14 w-14',
        voiceActive ? 'bg-brand-dark' : 'bg-brand')}>
      <Mic className={elderly && !compact ? 'h-7 w-7' : 'h-6 w-6'} strokeWidth={2} aria-hidden="true" />
      {/* iOS 처럼 마이크가 켜져 있으면 주황 점 */}
      {wakeListening && <span className="absolute top-0.5 right-0.5 h-3 w-3 rounded-full bg-sym-orange ring-2 ring-canvas" aria-hidden="true" />}
    </button>
  )
}

/** 휴대폰 폭(768px 미만) 하단 탭 막대. 음성 버튼은 오른쪽 끝. */
export function BottomBar({ onVoice, voiceActive, wakeListening, onDemo }: NavProps) {
  const { elderly } = usePreferences()
  const { source } = useHome()
  const items = useNavItems()
  return (
    <nav aria-label="주요 메뉴"
      className="fixed inset-x-0 bottom-0 z-30 flex items-center gap-1 border-t border-line bg-canvas/95 px-2 pt-1.5 pb-[max(6px,env(safe-area-inset-bottom))] backdrop-blur md:hidden">
      <ul className="flex min-w-0 flex-1 justify-around">
        {items.map(({ to, label, Icon, risk }) => (
          <li key={to} className="flex-1">
            <NavLink to={to} className={({ isActive }) => cn('press flex flex-col items-center gap-0.5 py-1', isActive ? 'text-brand-ink' : 'text-ink-3')}>
              <span className="relative">
                <Icon className="h-6 w-6" aria-hidden="true" />
                <RiskDot risk={risk} label={label} />
              </span>
              <span className="text-[0.625rem] font-medium">{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      {source.demo && (
        <button type="button" onClick={onDemo} aria-label="시연 도구" className="press flex h-11 w-11 items-center justify-center rounded-full text-ink-3">
          <FlaskConical className="h-5 w-5" aria-hidden="true" />
        </button>
      )}
      <VoiceButton onVoice={onVoice} voiceActive={voiceActive} wakeListening={wakeListening} elderly={elderly} compact />
    </nav>
  )
}
