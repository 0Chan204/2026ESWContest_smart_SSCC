import { Link } from 'react-router'
import { AlertTriangle, ChevronRight, Flame, UserX, WifiOff } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { useNow } from '@/hooks/useNow'
import { formatCountdown, formatDuration } from '@/lib/format'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

/**
 * 모든 화면 상단에 걸리는 한 줄 알림. 가장 급한 것 하나만 보여준다.
 * 우선순위: 낙상(응답 대기) > 과열 > 자동 차단 > 화력 저감 > 이탈 관찰 > 기기 연결 끊김
 * 위험(빨강)만 채운 막대, 나머지는 흰 막대에 색 아이콘 (iOS 알림 배너 방식).
 */
export function StatusBanner() {
  const { fall, fallAlertOpen, setFallAlert, kitchenPhase, presence, policy, induction, devices } = useHome()
  const { elderly } = usePreferences()
  const now = useNow()

  const k = presence.kitchen
  const mult = k?.zone === 'near' ? policy.nearZoneMultiplier : 1
  const offline = devices.filter((d) => !d.online)

  let tone: 'danger' | 'warn' | 'caution' | 'muted' | null = null
  let Icon = AlertTriangle
  let title = ''
  let detail = ''
  let action: { label: string; to?: string; onClick?: () => void } | null = null

  if (fall?.status === 'pending' && !fallAlertOpen) {
    tone = 'danger'; Icon = AlertTriangle
    title = '욕실 낙상 감지'
    detail = `보호자 응답이 없으면 ${formatCountdown((new Date(fall.autoReportAt).getTime() - now) / 1000)} 후 자동 신고`
    action = { label: '자세히', onClick: () => setFallAlert(true) }
  } else if (kitchenPhase === 'overheat') {
    tone = 'danger'; Icon = Flame
    title = `인덕션 과열 ${Math.round(induction?.burner.temperature ?? 0)}°C`
    detail = '식을 때까지 켤 수 없어요'
    action = { label: '주방', to: '/kitchen' }
  } else if (kitchenPhase === 'auto_off') {
    tone = 'danger'; Icon = Flame
    title = '인덕션 전원 자동 차단'
    detail = '주방을 오래 비우셨어요'
    action = { label: '주방', to: '/kitchen' }
  } else if (kitchenPhase === 'auto_reduced') {
    tone = 'warn'; Icon = UserX
    title = `화력 ${policy.reduceToLevel}단으로 낮춤`
    detail = `부재 ${formatDuration(k.absentSec)} · ${Math.round((policy.offAfterSec * mult) / 60)}분이 되면 전원을 꺼요`
    action = { label: '주방', to: '/kitchen' }
  } else if (kitchenPhase === 'absence_watch') {
    tone = 'caution'; Icon = UserX
    title = '조리 중 주방 비어 있음'
    detail = `부재 ${formatDuration(k.absentSec)} · ${Math.round((policy.reduceAfterSec * mult) / 60)}분이 되면 화력을 낮춰요`
    action = { label: '주방', to: '/kitchen' }
  } else if (offline.length > 0) {
    tone = 'muted'; Icon = WifiOff
    title = `${offline.map((d) => d.name).join(', ')} 응답 없음`
    detail = '전원과 Wi-Fi 를 확인해 주세요'
  }

  if (!tone) return null
  const danger = tone === 'danger'
  const iconColor = { danger: 'text-white', warn: 'text-warn', caution: 'text-caution', muted: 'text-ink-3' }[tone]

  return (
    <div role="status" aria-live="polite"
      className={cn('mx-5 mt-3 flex shrink-0 items-center gap-3 rounded-xl pr-2 pl-4 md:mx-8',
        elderly ? 'min-h-16 text-lg' : 'min-h-12 text-[0.9375rem]',
        danger ? 'bg-danger-fill text-white' : 'bg-surface text-ink')}>
      <Icon className={cn('shrink-0', elderly ? 'h-6 w-6' : 'h-5 w-5', iconColor, danger && 'soft-pulse')} strokeWidth={2.2} aria-hidden="true" />
      <p className="min-w-0 flex-1 truncate">
        <span className="font-semibold">{title}</span>
        <span className={danger ? 'text-white/85' : 'text-ink-2'}> · {detail}</span>
      </p>
      {action && (action.to ? (
        <Link to={action.to} className={cn('press flex min-h-10 shrink-0 items-center gap-0.5 rounded-lg px-2 font-semibold', danger ? 'text-white' : 'text-brand-ink')}>
          {action.label}<ChevronRight className="h-4 w-4" strokeWidth={2.4} aria-hidden="true" />
        </Link>
      ) : (
        <button type="button" onClick={action.onClick} className={cn('press flex min-h-10 shrink-0 items-center gap-0.5 rounded-lg px-2 font-semibold', danger ? 'text-white' : 'text-brand-ink')}>
          {action.label}<ChevronRight className="h-4 w-4" strokeWidth={2.4} aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
