import { ChevronRight, Droplet, Flame, PersonStanding } from 'lucide-react'
import { EVENT_TITLE, ROOM_LABEL, eventCategory } from '@/lib/labels'
import { formatWhen } from '@/lib/format'
import type { SafetyEvent } from '@/types'
import { cn } from '@/lib/cn'

const ICON = { fire: Flame, fall: PersonStanding, routine: Droplet } as const

export function EventIcon({ event, size = 'md' }: { event: SafetyEvent; size?: 'md' | 'lg' }) {
  const Icon = ICON[eventCategory(event.type)]
  const tone = event.severity === 'danger' ? 'bg-danger-soft text-danger'
    : event.severity === 'warning' ? 'bg-warn-soft text-warn' : 'bg-sunken text-ink-2'
  return (
    <span className={cn('flex shrink-0 items-center justify-center rounded-full', size === 'lg' ? 'h-12 w-12' : 'h-10 w-10', tone)}>
      <Icon className={size === 'lg' ? 'h-6 w-6' : 'h-5 w-5'} aria-hidden="true" />
    </span>
  )
}

/** 안전 기록 한 줄 (설정 화면 리스트와 같은 구성: 아이콘 / 제목 · 설명 / 시각) */
export function EventRow({ event, onClick, big = false, compact = false }: {
  event: SafetyEvent
  onClick: () => void
  big?: boolean
  compact?: boolean
}) {
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full items-center gap-4 rounded-2xl text-left transition-colors hover:bg-sunken', compact ? 'px-3 py-2.5' : 'px-4 py-3.5')}>
      <EventIcon event={event} size={big ? 'lg' : 'md'} />
      <span className="min-w-0 flex-1">
        <span className={cn('block truncate font-semibold text-ink', big ? 'text-xl' : 'text-[0.9375rem]')}>{EVENT_TITLE[event.type]}</span>
        <span className={cn('block truncate text-ink-2', big ? 'text-base' : 'text-[0.8125rem]')}>
          {compact ? formatWhen(event.occurredAt) : ROOM_LABEL[event.room]}{event.action ? ` · ${event.action}` : ''}
        </span>
      </span>
      {!compact && <span className={cn('tabular shrink-0 text-ink-3', big ? 'text-base' : 'text-[0.8125rem]')}>{formatWhen(event.occurredAt)}</span>}
      <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" aria-hidden="true" />
    </button>
  )
}
