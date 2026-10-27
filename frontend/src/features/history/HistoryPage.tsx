import { useEffect, useMemo, useState } from 'react'
import { Calendar, ClipboardList, Search } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, SectionTitle } from '@/components/ui/Card'
import { Segmented } from '@/components/ui/Segmented'
import { Pagination } from '@/components/ui/Pagination'
import { ListGroup, ListRow } from '@/components/ui/List'
import { EventRow } from './EventRow'
import { EventDetailSheet } from './EventDetailSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { CATEGORY_LABEL, EVENT_TITLE, FEEDBACK_TYPES, eventCategory, isRecord, type EventCategory } from '@/lib/labels'
import { toDateInput } from '@/lib/format'
import type { SafetyEvent } from '@/types'
import { cn } from '@/lib/cn'

type CategoryFilter = EventCategory | 'all'
type RoomFilter = 'all' | 'kitchen' | 'bedroom' | 'bathroom'

function defaultRange() {
  const to = new Date(); const from = new Date(); from.setDate(from.getDate() - 6)
  return { from: toDateInput(from), to: toDateInput(to) }
}

/** 로컬 날짜(YYYY-MM-DD) 비교용 — 이벤트 시각은 ISO(UTC) 라 로컬 날짜로 바꿔서 비교한다 */
const localDay = (iso: string) => toDateInput(new Date(iso))

/** 날짜 묶음 제목: 오늘 / 어제 / 10월 15일 수요일 */
function dayTitle(day: string) {
  const today = toDateInput(new Date())
  const y = new Date(); y.setDate(y.getDate() - 1)
  if (day === today) return '오늘'
  if (day === toDateInput(y)) return '어제'
  const [, m, d] = day.split('-').map(Number)
  const w = ['일', '월', '화', '수', '목', '금', '토'][new Date(`${day}T00:00:00`).getDay()]
  return `${m}월 ${d}일 ${w}요일`
}

export function HistoryPage() {
  const { events } = useHome()
  const { elderly } = usePreferences()
  const initial = useMemo(defaultRange, [])
  const [category, setCategory] = useState<CategoryFilter>('all')
  const [room, setRoom] = useState<RoomFilter>('all')
  const [from, setFrom] = useState(initial.from)
  const [to, setTo] = useState(initial.to)
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  // 세로가 짧은 월패드(1280×720)에서 어르신 글자가 크면 한 쪽에 3건만 (목록 안 스크롤이 생기지 않도록)
  const [short, setShort] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.('(max-height: 760px)').matches)
  useEffect(() => {
    const mq = window.matchMedia?.('(max-height: 760px)')
    if (!mq) return
    const on = (e: MediaQueryListEvent) => setShort(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  const perPage = elderly ? (short ? 3 : 4) : 6

  const records = useMemo(() => events.filter(isRecord), [events])
  const filtered = useMemo(() => {
    const kw = q.trim()
    return records.filter((e) => {
      if (category !== 'all' && eventCategory(e.type) !== category) return false
      if (room !== 'all' && e.room !== room) return false
      const day = localDay(e.occurredAt)
      if (from && day < from) return false
      if (to && day > to) return false
      if (kw && !`${EVENT_TITLE[e.type]} ${e.action ?? ''} ${e.trigger ?? ''}`.includes(kw)) return false
      return true
    })
  }, [records, category, room, from, to, q])

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage))
  const current = Math.min(page, totalPages)
  const items = filtered.slice((current - 1) * perPage, current * perPage)
  const update = (fn: () => void) => { fn(); setPage(1) }   // 필터가 바뀌면 1페이지로

  // 이 페이지의 기록을 날짜별로 묶는다
  const groups = useMemo(() => {
    const map = new Map<string, SafetyEvent[]>()
    for (const e of items) {
      const day = localDay(e.occurredAt)
      map.set(day, [...(map.get(day) ?? []), e])
    }
    return [...map.entries()]
  }, [items])

  const counts = useMemo(() => {
    const week = records.filter((e) => localDay(e.occurredAt) >= initial.from)
    return {
      fire: week.filter((e) => eventCategory(e.type) === 'fire').length,
      fall: week.filter((e) => e.type === 'fall_detected').length,
      routine: week.filter((e) => eventCategory(e.type) === 'routine').length,
      feedback: records.filter((e) => FEEDBACK_TYPES.has(e.type) && !e.feedback).length,
    }
  }, [records, initial.from])

  const field = 'flex min-h-10 items-center gap-2 rounded-[10px] bg-fill px-3 text-[0.9375rem] text-ink'

  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="안전 기록" />

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-5 pt-5 md:px-8 wall:short:pt-4">
        <div className="w-full md:w-[360px]">
          <Segmented<CategoryFilter> label="분류" value={category} onChange={(v) => update(() => setCategory(v))}
            options={[{ value: 'all', label: '전체' }, { value: 'fire', label: CATEGORY_LABEL.fire }, { value: 'fall', label: CATEGORY_LABEL.fall }, { value: 'routine', label: CATEGORY_LABEL.routine }]} />
        </div>
        <label className={field}>
          <span className="sr-only">공간</span>
          <select value={room} onChange={(e) => update(() => setRoom(e.target.value as RoomFilter))} className="cursor-pointer bg-transparent outline-none">
            <option value="all">모든 공간</option><option value="kitchen">주방</option><option value="bedroom">침실</option><option value="bathroom">욕실</option>
          </select>
        </label>
        <div className={field}>
          <Calendar className="h-4 w-4 text-ink-3" aria-hidden="true" />
          <input type="date" value={from} max={to} aria-label="시작 날짜" onChange={(e) => update(() => setFrom(e.target.value))} className="tabular bg-transparent outline-none" />
          <span className="text-ink-3">–</span>
          <input type="date" value={to} min={from} aria-label="종료 날짜" onChange={(e) => update(() => setTo(e.target.value))} className="tabular bg-transparent outline-none" />
        </div>
        <label className={cn(field, 'min-w-44 flex-1')}>
          <Search className="h-4 w-4 shrink-0 text-ink-3" aria-hidden="true" />
          <input type="search" value={q} placeholder="검색" aria-label="내용 검색" onChange={(e) => update(() => setQ(e.target.value))} className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-ink-3" />
        </label>
        <button type="button" onClick={() => { setCategory('all'); setRoom('all'); setFrom(initial.from); setTo(initial.to); setQ(''); setPage(1) }}
          className="press min-h-10 px-2 text-[0.9375rem] text-brand-ink">초기화</button>
      </div>

      <div className="grid grid-cols-1 gap-6 px-5 pt-5 pb-6 md:px-8 wall:min-h-0 wall:flex-1 wall:grid-cols-12 wall:pb-7 wall:short:pt-4 wall:short:pb-5">
        <div className="flex flex-col wall:col-span-8 wall:min-h-0">
          <div className="flex flex-col gap-5 wall:min-h-0 wall:flex-1 wall:overflow-y-auto">
            {groups.map(([day, list]) => (
              <ListGroup key={day} title={dayTitle(day)}>
                {list.map((e) => <EventRow key={e.eventId} event={e} big={elderly} timeOnly onClick={() => setSelected(e.eventId)} />)}
              </ListGroup>
            ))}
            {items.length === 0 && (
              <Card className="flex flex-col items-center justify-center gap-2 py-12 text-ink-3 wall:flex-1">
                <ClipboardList className="h-8 w-8" strokeWidth={1.6} aria-hidden="true" />
                <p className="text-[0.9375rem]">조건에 맞는 기록 없음</p>
              </Card>
            )}
          </div>
          <div className="flex shrink-0 items-center justify-between pt-3">
            <span className="text-[0.8125rem] text-ink-3">{filtered.length}건</span>
            <Pagination page={current} totalPages={totalPages} onChange={setPage} />
            <span className="w-8" />
          </div>
        </div>

        <section className="wall:col-span-4">
          <SectionTitle>최근 7일</SectionTitle>
          <ListGroup footer={counts.feedback > 0 && !elderly ? '자동 조치가 적절했는지 알려주시면 판단 기준을 다듬는 데 쓰여요.' : undefined}>
            <ListRow big={elderly} title="화재 예방 조치" value={`${counts.fire}건`} />
            <ListRow big={elderly} title="낙상 감지" value={`${counts.fall}건`} />
            <ListRow big={elderly} title="아침 자동 출수" value={`${counts.routine}건`} />
            {counts.feedback > 0 && !elderly && <ListRow title="피드백 대기" value={<span className="font-semibold text-brand-ink">{counts.feedback}건</span>} />}
          </ListGroup>
        </section>
      </div>

      <EventDetailSheet eventId={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
