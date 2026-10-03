import { useEffect } from 'react'
import { Flame, Gauge, Power } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/Button'
import { FeedbackButtons } from './FeedbackButtons'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useSpeech } from '@/hooks/useSpeech'
import { EVENT_TITLE, FEEDBACK_TYPES } from '@/lib/labels'
import { formatTime } from '@/lib/format'
import { cn } from '@/lib/cn'

/**
 * 시스템이 방금 수행한 안전 조치 안내.
 * 백엔드 구조상 조치는 서버가 먼저 수행하고 결과를 통보하므로, 여기서는 "무엇을 왜 했는지" 를 알린다.
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
    <Sheet open onClose={dismissNotice} width={elderly ? 640 : 520} urgent hideClose title={undefined}
      footer={<Button variant="primary" size={elderly ? 'xl' : 'lg'} className="w-full" onClick={dismissNotice}>확인</Button>}>
      <div className="pt-7">
        <span className={cn('mb-4 flex h-14 w-14 items-center justify-center rounded-2xl', danger ? 'bg-danger-soft' : 'bg-warn-soft')}>
          <Icon className={cn('h-7 w-7', danger ? 'text-danger' : 'text-warn')} aria-hidden="true" />
        </span>
        <p className="text-sm font-semibold text-ink-3">주방 · {formatTime(event.occurredAt)}</p>
        <h2 className={cn('mt-1 font-bold text-ink', elderly ? 'text-3xl' : 'text-2xl')}>{EVENT_TITLE[event.type]}</h2>
        {event.guidance && (
          <p className={cn('mt-3 leading-relaxed text-ink', elderly ? 'text-xl' : 'text-[1.0625rem]')}>{event.guidance}</p>
        )}
        {!elderly && (
          <dl className="mt-5 divide-y divide-line rounded-2xl bg-sunken px-4">
            {event.trigger && <Row k="감지" v={event.trigger} />}
            {event.action && <Row k="조치" v={event.action} />}
            {event.reasoning && <Row k="판단 근거" v={event.reasoning} />}
          </dl>
        )}
        {FEEDBACK_TYPES.has(event.type) && <div className="mt-5"><FeedbackButtons event={event} size={elderly ? 'lg' : 'md'} /></div>}
      </div>
    </Sheet>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-4 py-3 text-[0.9375rem]">
      <dt className="w-20 shrink-0 text-ink-3">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  )
}
