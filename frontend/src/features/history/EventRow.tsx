import { Droplet, Flame, PersonStanding } from 'lucide-react'
import { ListRow, SymbolIcon } from '@/components/ui/List'
import { EVENT_TITLE, ROOM_LABEL, eventCategory } from '@/lib/labels'
import { formatTime, formatWhen } from '@/lib/format'
import type { SafetyEvent } from '@/types'

const ICON = { fire: Flame, fall: PersonStanding, routine: Droplet } as const

/** 기록 아이콘: iOS 알림 목록처럼 색 사각형 (위험 빨강 · 경고 주황 · 생활 파랑 · 그 외 회색) */
export function EventIcon({ event }: { event: SafetyEvent }) {
  const cat = eventCategory(event.type)
  const color = event.severity === 'danger' ? 'red' : event.severity === 'warning' ? 'orange' : cat === 'routine' ? 'blue' : 'gray'
  return <SymbolIcon icon={ICON[cat]} color={color} />
}

/** 안전 기록 한 줄. compact = 좁은 칸(홈·주방 오른쪽)용 */
export function EventRow({ event, onClick, big = false, compact = false, timeOnly = false }: {
  event: SafetyEvent
  onClick: () => void
  big?: boolean
  compact?: boolean
  /** 날짜별로 묶인 목록에서는 시각만 */
  timeOnly?: boolean
}) {
  const when = timeOnly ? formatTime(event.occurredAt) : formatWhen(event.occurredAt)
  return (
    <ListRow big={big} onClick={onClick} chevron
      leading={<EventIcon event={event} />}
      title={EVENT_TITLE[event.type]}
      titleClass="font-medium"
      subtitle={compact ? `${when}${event.action ? ` · ${event.action}` : ''}` : `${ROOM_LABEL[event.room]}${event.action ? ` · ${event.action}` : ''}`}
      value={compact ? undefined : when} />
  )
}
