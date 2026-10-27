import { Sheet } from '@/components/ui/Sheet'
import { ListGroup, ListRow } from '@/components/ui/List'
import { FeedbackButtons } from '@/features/alerts/FeedbackButtons'
import { SessionTimeline } from './SessionTimeline'
import { EventIcon } from './EventRow'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { CATEGORY_LABEL, EVENT_TITLE, FEEDBACK_TYPES, ROOM_LABEL, eventCategory } from '@/lib/labels'
import { formatDateTime, formatDuration } from '@/lib/format'
import { cn } from '@/lib/cn'

/** 기록 상세: 무슨 일이 있었고, 왜 그렇게 판단했고, 무엇을 했는지 */
export function EventDetailSheet({ eventId, onClose }: { eventId: string | null; onClose: () => void }) {
  const { events, sessions } = useHome()
  const { elderly } = usePreferences()
  const e = events.find((x) => x.eventId === eventId)
  if (!e) return null
  const session = e.sessionId ? sessions[e.sessionId] : undefined

  return (
    <Sheet open onClose={onClose} variant="side" width={elderly ? 600 : 480} title={EVENT_TITLE[e.type]}
      subtitle={`${ROOM_LABEL[e.room]} · ${formatDateTime(e.occurredAt)}`}>
      {e.guidance && (
        <div className="flex gap-3 rounded-2xl bg-surface p-4">
          <EventIcon event={e} />
          <p className={cn('leading-relaxed text-ink', elderly ? 'text-xl' : 'text-[1rem]')}>{e.guidance}</p>
        </div>
      )}

      <ListGroup className="mt-6">
        <ListRow big={elderly} title="분류" value={CATEGORY_LABEL[eventCategory(e.type)]} />
        {e.temperature !== undefined && <ListRow big={elderly} title="온도" value={`${Math.round(e.temperature)}°C`} />}
        {e.feedback && <ListRow big={elderly} title="피드백" value={e.feedback.verdict === 'approved' ? '적절했어요' : '과했어요'} />}
      </ListGroup>

      {(e.action || (!elderly && (e.trigger || e.reasoning))) && (
        <ListGroup className="mt-6">
          {!elderly && e.trigger && <Para k="감지" v={e.trigger} />}
          {e.action && <Para k="조치" v={e.action} big={elderly} />}
          {!elderly && e.reasoning && <Para k="판단 근거" v={e.reasoning} />}
        </ListGroup>
      )}

      {FEEDBACK_TYPES.has(e.type) && <div className="mt-6"><FeedbackButtons event={e} size={elderly ? 'lg' : 'md'} /></div>}

      {session && (
        <ListGroup className="mt-6" bodyClassName="px-4 pt-4"
          title={`조리 흐름 · 최고 ${Math.round(session.peakTemperature)}°C${session.endedAt ? ` · ${formatDuration((new Date(session.endedAt).getTime() - new Date(session.startedAt).getTime()) / 1000)}` : ''}`}>
          <SessionTimeline session={session} big={elderly} />
        </ListGroup>
      )}
    </Sheet>
  )
}

/** 긴 글 한 칸 (제목 위, 내용 아래) */
function Para({ k, v, big = false }: { k: string; v: string; big?: boolean }) {
  return (
    <div className="pl-4">
      <div className="row-sep py-3 pr-4">
        <p className="text-[0.8125rem] text-ink-3">{k}</p>
        <p className={cn('mt-0.5 leading-relaxed text-ink', big ? 'text-xl' : 'text-[0.9375rem]')}>{v}</p>
      </div>
    </div>
  )
}
