import type { ReactNode } from 'react'
import { MoreHorizontal } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/cn'

type IconType = LucideIcon

/**
 * 기기·상태 타일 (iPad '홈' 앱 액세서리 타일 방식).
 *  - on: 켜짐/활성 → 밝게 반전된 타일 + 색 있는 아이콘
 *  - off: 어두운 타일 + 회색 아이콘
 *  - danger / warn: 위험·주의 상태는 연한 상태색 바탕
 * 아이콘에 동그라미 배경을 두지 않는다. 상태 글자는 한 줄로 짧게.
 */
export function Tile({
  icon: Icon, glyph, name, state, on = false, tone, value, onPress, onMore, moreLabel, wide = false, big = false, className,
}: {
  icon: IconType
  /** 켜졌을 때 아이콘 색 클래스 (예: 'text-glyph-light') */
  glyph?: string
  name: string
  state: ReactNode
  on?: boolean
  tone?: 'danger' | 'warn' | 'muted'
  /** 넓은 타일 오른쪽 위에 크게 보일 값 (예: 98°) */
  value?: ReactNode
  onPress?: () => void
  /** 오른쪽 위 '더 보기' 버튼 — 타일을 눌러 켜고 끄는 기기의 상세 열기 */
  onMore?: () => void
  moreLabel?: string
  wide?: boolean
  big?: boolean
  className?: string
}) {
  const bg = tone === 'danger' ? 'bg-danger-soft' : tone === 'warn' ? 'bg-warn-soft' : on ? 'bg-tile-on shadow-[var(--shadow-tile)]' : 'bg-tile-off'
  const iconColor = tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : on ? (glyph ?? 'text-brand-ink') : 'text-ink-3'
  const nameColor = tone ? 'text-ink' : on ? 'text-tile-on-ink' : 'text-ink'
  const stateColor = tone === 'danger' ? 'text-danger font-semibold' : tone === 'warn' ? 'text-warn font-semibold'
    : on ? 'text-tile-on-ink-2' : 'text-ink-2'

  return (
    <div className={cn('relative min-w-0', wide && 'col-span-2', className)}>
      <button type="button" onClick={onPress} disabled={!onPress}
        className={cn('press flex h-full w-full flex-col justify-between rounded-2xl text-left disabled:cursor-default disabled:opacity-100',
          big ? 'p-5' : 'p-4', bg)}>
        <span className="flex items-start justify-between gap-3">
          <Icon className={cn(big ? 'h-9 w-9' : 'h-7 w-7', iconColor)} strokeWidth={1.75} aria-hidden="true" />
          {value !== undefined && (
            <span className={cn('tabular leading-none font-light tracking-[-0.03em]', big ? 'text-[3.25rem]' : 'text-[2.5rem]',
              tone === 'danger' ? 'text-danger' : on ? 'text-tile-on-ink' : 'text-ink')}>{value}</span>
          )}
        </span>
        <span className={cn('block min-w-0', onMore && 'pr-8')}>
          <span className={cn('block truncate font-semibold', big ? 'text-[1.375rem]' : 'text-[0.9375rem]', nameColor)}>{name}</span>
          <span className={cn('block truncate', big ? 'text-[1.125rem]' : 'text-[0.8125rem]', stateColor)}>{state}</span>
        </span>
      </button>
      {onMore && (
        <button type="button" onClick={onMore} aria-label={moreLabel ?? `${name} 자세히`}
          className={cn('press absolute right-2 bottom-2 flex h-10 w-10 items-center justify-center rounded-full',
            on ? 'text-tile-on-ink-2' : 'text-ink-3')}>
          <MoreHorizontal className="h-5 w-5" aria-hidden="true" />
        </button>
      )}
    </div>
  )
}
