import { formatTime } from '@/lib/format'
import type { CookingSession } from '@/types'
import { cn } from '@/lib/cn'

const DOT: Record<string, string> = {
  cooking_started: 'bg-ok', cooking_ended: 'bg-ink-3', user_returned: 'bg-ok',
  absence_detected: 'bg-caution', auto_power_reduced: 'bg-warn', auto_power_off: 'bg-danger',
  overheat_detected: 'bg-danger', overheat_cleared: 'bg-ok',
}

/** 한 번의 조리 흐름 (시나리오 5막: 정상 조리 → 이탈 → 자동 저감 → 복귀 → 종료) */
export function SessionTimeline({ session, max, big = false }: { session: CookingSession; max?: number; big?: boolean }) {
  const entries = max ? session.timeline.slice(-max) : session.timeline
  return (
    <ol>
      {entries.map((e, i) => (
        <li key={`${e.at}-${e.type}`} className="flex gap-3">
          <div className="flex flex-col items-center pt-1.5">
            <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', DOT[e.type] ?? 'bg-ink-3')} aria-hidden="true" />
            {i < entries.length - 1 && <span className="my-1 w-px flex-1 bg-line" aria-hidden="true" />}
          </div>
          <div className={cn('flex flex-1 gap-3', big ? 'pb-4' : 'pb-3')}>
            <span className={cn('tabular w-12 shrink-0 text-ink-3', big ? 'text-base' : 'text-[0.8125rem]')}>{formatTime(e.at)}</span>
            <span className={cn('text-ink', big ? 'text-lg' : 'text-[0.875rem]')}>{e.summary}</span>
          </div>
        </li>
      ))}
    </ol>
  )
}
