import type { TimelineEvent } from '@/types'
import { cn } from '@/lib/cn'

const DOT: Record<TimelineEvent['kind'], string> = {
  normal: 'bg-emerald-500',
  warning: 'bg-amber-500',
  danger: 'bg-red-500',
  info: 'bg-blue-400',
}

/**
 * 최근 이벤트 타임라인.
 * 월패드에서 화면이 늘어나지 않도록 표시 건수를 반드시 제한한다.
 */
export function EventTimeline({
  events, max = 4, dense,
}: {
  events: TimelineEvent[]
  max?: number
  dense?: boolean
}) {
  const visible = events.slice(0, max)
  return (
    <ol className="min-w-0">
      {visible.map((event, i) => (
        <li key={`${event.time}-${event.text}`} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', DOT[event.kind])} aria-hidden="true" />
            {i < visible.length - 1 && <div className="my-1 w-px flex-1 bg-gray-100" />}
          </div>
          <div className={cn('flex-1 min-w-0', dense ? 'pb-2' : 'pb-3')}>
            <div className="flex items-start gap-2.5">
              <span className="tabular mt-0.5 shrink-0 text-xs text-gray-400">{event.time}</span>
              <span className="text-sm break-keep text-gray-700">{event.text}</span>
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}
