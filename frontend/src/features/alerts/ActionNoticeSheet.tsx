import { useEffect } from 'react'
import { Flame, Gauge, Power } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/Button'
import { ListGroup } from '@/components/ui/List'
import { FeedbackButtons } from './FeedbackButtons'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useSpeech } from '@/hooks/useSpeech'
import { EVENT_TITLE, FEEDBACK_TYPES } from '@/lib/labels'
import { formatTime } from '@/lib/format'
import { cn } from '@/lib/cn'

/**
 * 시스템이 방금 수행한 안전 조치 안내.
 * 조치는 서버가 먼저 수행하고 결과를 통보하므로, 여기서는 "무엇을 왜 했는지" 를 알린다.
 */
export function ActionNoticeSheet() {
  const { notice, dismissNotice, events } = useHome()
  const { elderly } = usePreferences()
  const speak = useSpeech()
  // 피드백 반영을 위해 최신 이벤트 객체를 다시 찾는다
  const event = notice ? events.find((e) => e.eventId === notice.eventId) ?? notice : null

  useEffect(() => { if (notice) speak(notice.guidance) }, [notice, speak])
  if (!event) return null

  const danger = event.severity === 'danger'
  const Icon = event.type === 'overheat_detected' ? Flame : event.type === 'auto_power_off' ? Power : Gauge

  return (
    <Sheet open onClose={dismissNotice} width={elderly ? 620 : 480} urgent hideClose
      footer={<Button variant="primary" size={elderly ? 'xl' : 'lg'} className="w-full" onClick={dismissNotice}>확인</Button>}>
      <div className="flex flex-col items-center pt-6 text-center">
        <Icon className={cn(elderly ? 'h-14 w-14' : 'h-12 w-12', danger ? 'text-danger' : 'text-warn')} strokeWidth={1.6} aria-hidden="true" />
        <h2 className={cn('mt-3 font-bold text-ink', elderly ? 'text-3xl' : 'text-[1.5rem]')}>{EVENT_TITLE[event.type]}</h2>
        <p className="mt-0.5 text-[0.875rem] text-ink-3">주방 · {formatTime(event.occurredAt)}</p>
        {event.guidance && <p className={cn('mt-4 leading-relaxed text-ink', elderly ? 'text-xl' : 'text-[1.0625rem]')}>{event.guidance}</p>}
      </div>
      {!elderly && (event.trigger || event.action || event.reasoning) && (
        <ListGroup className="mt-6">
          {event.trigger && <Row k="감지" v={event.trigger} />}
          {event.action && <Row k="조치" v={event.action} />}
          {event.reasoning && <Row k="판단 근거" v={event.reasoning} />}
        </ListGroup>
      )}
      {FEEDBACK_TYPES.has(event.type) && <div className="mt-6"><FeedbackButtons event={event} size={elderly ? 'lg' : 'md'} /></div>}
    </Sheet>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="pl-4">
      <div className="row-sep flex gap-4 py-3 pr-4 text-[0.9375rem]">
        <span className="w-20 shrink-0 text-ink-2">{k}</span>
        <span className="text-ink">{v}</span>
      </div>
    </div>
  )
}
