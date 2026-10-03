import { Link } from 'react-router'
import { AlertTriangle, ChevronRight, Flame, UserX, WifiOff } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { useNow } from '@/hooks/useNow'
import { formatCountdown, formatDuration } from '@/lib/format'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

/**
 * 모든 화면 상단에 걸리는 한 줄 상태 안내. 가장 급한 것 하나만 보여준다.
 * 우선순위: 낙상(응답 대기) > 과열 > 자동 차단 > 화력 저감 > 이탈 관찰 > 기기 연결 끊김
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
  let text = ''
  let action: { label: string; to?: string; onClick?: () => void } | null = null

  if (fall?.status === 'pending' && !fallAlertOpen) {
    tone = 'danger'; Icon = AlertTriangle
    const left = (new Date(fall.autoReportAt).getTime() - now) / 1000
    text = `욕실에서 낙상이 감지됐어요 · 보호자 응답이 없으면 ${formatCountdown(left)} 후 자동 신고돼요`
    action = { label: '자세히', onClick: () => setFallAlert(true) }
  } else if (kitchenPhase === 'overheat') {
    tone = 'danger'; Icon = Flame
    text = `인덕션이 과열됐어요 (${Math.round(induction?.burner.temperature ?? 0)}°C) · 식을 때까지 켤 수 없어요`
    action = { label: '주방 보기', to: '/kitchen' }
  } else if (kitchenPhase === 'auto_off') {
    tone = 'danger'; Icon = Flame
    text = '주방을 오래 비우셔서 인덕션 전원을 껐어요'
    action = { label: '주방 보기', to: '/kitchen' }
  } else if (kitchenPhase === 'auto_reduced') {
    tone = 'warn'; Icon = UserX
    text = `인덕션 화력을 ${policy.reduceToLevel}단으로 낮췄어요 · 부재 ${formatDuration(k.absentSec)} — ${Math.round((policy.offAfterSec * mult) / 60)}분이 되면 전원을 꺼요`
    action = { label: '주방 보기', to: '/kitchen' }
  } else if (kitchenPhase === 'absence_watch') {
    tone = 'caution'; Icon = UserX
    text = `주방에 아무도 없어요 · 부재 ${formatDuration(k.absentSec)} — ${Math.round((policy.reduceAfterSec * mult) / 60)}분이 되면 화력을 자동으로 낮춰요`
    action = { label: '주방 보기', to: '/kitchen' }
  } else if (offline.length > 0) {
    tone = 'muted'; Icon = WifiOff
    text = `${offline.map((d) => d.name).join(', ')} 연결이 끊겼어요 · 기기 전원과 Wi-Fi 를 확인해 주세요`
  }

  if (!tone) return null
  const cls = {
    danger: 'bg-danger text-white',
    warn: 'bg-warn-soft text-[#9a4a00]',
    caution: 'bg-caution-soft text-[#7a5600]',
    muted: 'bg-[#e9ebee] text-ink-2',
  }[tone]

  return (
    <div role="status" aria-live="polite" className={cn('mx-8 mt-5 flex shrink-0 items-center gap-3 rounded-2xl px-5', elderly ? 'min-h-16 text-lg' : 'min-h-12 text-[0.9375rem]', cls)}>
      <Icon className={cn('shrink-0', elderly ? 'h-6 w-6' : 'h-5 w-5', tone === 'danger' && 'soft-pulse')} aria-hidden="true" />
      <p className="min-w-0 flex-1 font-semibold">{text}</p>
      {action && (action.to ? (
        <Link to={action.to} className="flex shrink-0 items-center gap-0.5 rounded-lg px-2 py-2 font-semibold opacity-90 hover:opacity-100">
          {action.label}<ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      ) : (
        <button type="button" onClick={action.onClick} className="flex shrink-0 items-center gap-0.5 rounded-lg px-2 py-2 font-semibold">
          {action.label}<ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
