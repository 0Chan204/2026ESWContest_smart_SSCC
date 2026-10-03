import { Sheet } from '@/components/ui/Sheet'
import { Badge } from '@/components/ui/StatusDot'
import { FeedbackButtons } from '@/features/alerts/FeedbackButtons'
import { SessionTimeline } from './SessionTimeline'
import { EventIcon } from './EventRow'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { CATEGORY_LABEL, EVENT_TITLE, FEEDBACK_TYPES, ROOM_LABEL, eventCategory } from '@/lib/labels'
import { formatDateTime, formatDuration } from '@/lib/format'
import { cn } from '@/lib/cn'

/** 기록 상세: 무슨 일이 있었고, 왜 그렇게 판단했고, 시스템이 무엇을 했는지 */
export function EventDetailSheet({ eventId, onClose }: { eventId: string | null; onClose: () => void }) {
  const { events, sessions } = useHome()
  const { elderly } = usePreferences()
  const e = events.find((x) => x.eventId === eventId)
  if (!e) return null
  const session = e.sessionId ? sessions[e.sessionId] : undefined
  const tone = e.severity === 'danger' ? 'danger' : e.severity === 'warning' ? 'warn' : 'muted'

  return (
    <Sheet open onClose={onClose} variant="side" width={elderly ? 600 : 500} title={EVENT_TITLE[e.type]}
      subtitle={`${ROOM_LABEL[e.room]} · ${formatDateTime(e.occurredAt)}`}>
      <div className="flex items-center gap-3">
        <EventIcon event={e} size="lg" />
        <Badge tone={tone}>{CATEGORY_LABEL[eventCategory(e.type)]}</Badge>
        {e.temperature !== undefined && <Badge>{Math.round(e.temperature)}°C</Badge>}
      </div>

      {e.guidance && (
        <p className={cn('mt-5 rounded-2xl bg-sunken px-5 py-4 leading-relaxed text-ink', elderly ? 'text-xl' : 'text-[1rem]')}>
          “{e.guidance}”
        </p>
      )}

      <dl className={cn('mt-4 divide-y divide-line', elderly ? 'text-lg' : 'text-[0.9375rem]')}>
        {!elderly && e.trigger && <Row k="감지한 것" v={e.trigger} />}
        {e.action && <Row k="한 일" v={e.action} />}
        {!elderly && e.reasoning && <Row k="판단 근거" v={e.reasoning} />}
        {e.feedback && <Row k="피드백" v={e.feedback.verdict === 'approved' ? '적절했어요' : '과했어요'} />}
      </dl>

      {FEEDBACK_TYPES.has(e.type) && <div className="mt-5"><FeedbackButtons event={e} size={elderly ? 'lg' : 'md'} /></div>}

      {session && (
        <section className="mt-7">
          <div className="mb-3 flex items-baseline justify-between">
            <h3 className={cn('font-semibold text-ink', elderly ? 'text-xl' : 'text-[0.9375rem]')}>이번 조리 흐름</h3>
            <span className="text-[0.8125rem] text-ink-3">
              최고 {Math.round(session.peakTemperature)}°C
              {session.endedAt && ` · ${formatDuration((new Date(session.endedAt).getTime() - new Date(session.startedAt).getTime()) / 1000)}`}
            </span>
          </div>
          <SessionTimeline session={session} big={elderly} />
        </section>
      )}
    </Sheet>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-4 py-3.5">
      <dt className="w-24 shrink-0 text-ink-2">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  )
}
