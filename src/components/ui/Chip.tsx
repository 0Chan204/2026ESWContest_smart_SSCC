import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/cn'

type IconType = LucideIcon
export type ChipTone = 'ok' | 'caution' | 'warn' | 'danger' | 'brand' | 'muted'

const TONE: Record<ChipTone, string> = {
  ok: 'text-ok', caution: 'text-caution', warn: 'text-warn', danger: 'text-danger', brand: 'text-brand-ink', muted: 'text-ink-3',
}

/** 화면 맨 위 요약 칩 (iPad 홈 앱의 상태 요약 줄). 아이콘 · 이름 · 값 한 줄 */
export function Chip({ icon: Icon, label, value, tone = 'muted', onClick, big = false, alert = false }: {
  icon: IconType
  label: string
  value?: string
  tone?: ChipTone
  onClick?: () => void
  big?: boolean
  /** 주의가 필요한 칩은 바탕을 상태색으로 */
  alert?: boolean
}) {
  const bg = alert ? { danger: 'bg-danger-soft', warn: 'bg-warn-soft', caution: 'bg-caution-soft', ok: 'bg-ok-soft', brand: 'bg-brand-soft', muted: 'bg-surface' }[tone] : 'bg-surface'
  return (
    <button type="button" onClick={onClick} disabled={!onClick}
      className={cn('press inline-flex shrink-0 items-center gap-2 rounded-full pr-4 pl-3 whitespace-nowrap disabled:cursor-default disabled:opacity-100',
        big ? 'h-13 text-[1.125rem]' : 'h-10 text-[0.9375rem]', bg)}>
      <Icon className={cn(big ? 'h-6 w-6' : 'h-[18px] w-[18px]', TONE[tone])} strokeWidth={2} aria-hidden="true" />
      <span className="font-semibold text-ink">{label}</span>
      {value && <span className={alert ? cn('font-medium', TONE[tone]) : 'text-ink-2'}>{value}</span>}
    </button>
  )
}
