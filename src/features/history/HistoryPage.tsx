import { useMemo, useState } from 'react'
import { Calendar, ClipboardList, Search } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card } from '@/components/ui/Card'
import { Pagination } from '@/components/ui/Pagination'
import { EventRow } from './EventRow'
import { EventDetailSheet } from './EventDetailSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { CATEGORY_LABEL, EVENT_TITLE, FEEDBACK_TYPES, eventCategory, isRecord, type EventCategory } from '@/lib/labels'
import { toDateInput } from '@/lib/format'
import { cn } from '@/lib/cn'

type CategoryFilter = EventCategory | 'all'
type RoomFilter = 'all' | 'kitchen' | 'bathroom'

function defaultRange() {
  const to = new Date(); const from = new Date(); from.setDate(from.getDate() - 6)
  return { from: toDateInput(from), to: toDateInput(to) }
}

/** 로컬 날짜(YYYY-MM-DD) 비교용 — 이벤트 시각은 ISO(UTC) 라 로컬 날짜로 바꿔서 비교한다 */
const localDay = (iso: string) => toDateInput(new Date(iso))

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
  const perPage = elderly ? 4 : 6

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

  const counts = useMemo(() => {
    const week = records.filter((e) => localDay(e.occurredAt) >= initial.from)
    return {
      fire: week.filter((e) => eventCategory(e.type) === 'fire').length,
      fall: week.filter((e) => eventCategory(e.type) === 'fall' && e.type === 'fall_detected').length,
      routine: week.filter((e) => eventCategory(e.type) === 'routine').length,
      feedback: records.filter((e) => FEEDBACK_TYPES.has(e.type) && !e.feedback).length,
    }
  }, [records, initial.from])

  const field = 'flex min-h-11 items-center gap-2 rounded-xl bg-surface px-3.5 text-[0.9375rem] text-ink'

  return (
    <div className="flex h-full flex-col">
      <PageHeader title={elderly ? '안전 기록' : '안전 기록'} subtitle="HomeVIS 가 감지하고 조치한 일을 모아 보여드려요" />

      <div className="flex shrink-0 flex-wrap items-center gap-2.5 px-8 pt-5">
        <div className="flex rounded-xl bg-surface p-1" role="radiogroup" aria-label="분류">
          {(['all', 'fire', 'fall', 'routine'] as const).map((c) => (
            <button key={c} type="button" role="radio" aria-checked={category === c}
              onClick={() => update(() => setCategory(c))}
              className={cn('min-h-9 rounded-lg px-3.5 text-[0.875rem] font-semibold', category === c ? 'bg-ink text-white' : 'text-ink-2 hover:text-ink')}>
              {c === 'all' ? '전체' : CATEGORY_LABEL[c]}
            </button>
          ))}
        </div>
        <label className={field}>
          <span className="sr-only">공간</span>
          <select value={room} onChange={(e) => update(() => setRoom(e.target.value as RoomFilter))} className="cursor-pointer bg-transparent outline-none">
            <option value="all">모든 공간</option><option value="kitchen">주방</option><option value="bathroom">욕실</option>
          </select>
        </label>
        <div className={field}>
          <Calendar className="h-4 w-4 text-ink-3" aria-hidden="true" />
          <input type="date" value={from} max={to} aria-label="시작 날짜" onChange={(e) => update(() => setFrom(e.target.value))} className="tabular bg-transparent outline-none" />
          <span className="text-ink-3">~</span>
          <input type="date" value={to} min={from} aria-label="종료 날짜" onChange={(e) => update(() => setTo(e.target.value))} className="tabular bg-transparent outline-none" />
        </div>
        <label className={cn(field, 'min-w-0 flex-1')}>
          <Search className="h-4 w-4 shrink-0 text-ink-3" aria-hidden="true" />
          <input type="search" value={q} placeholder="내용 검색" aria-label="내용 검색" onChange={(e) => update(() => setQ(e.target.value))} className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-ink-3" />
        </label>
        <button type="button" onClick={() => { setCategory('all'); setRoom('all'); setFrom(initial.from); setTo(initial.to); setQ(''); setPage(1) }}
          className="min-h-11 rounded-xl px-3 text-[0.875rem] font-semibold text-ink-2 hover:bg-surface">초기화</button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-12 gap-5 px-8 pt-4 pb-7">
        <Card className="col-span-8 flex min-h-0 flex-col p-3">
          <p className="px-3 pt-2 pb-1 text-[0.8125rem] font-semibold text-ink-3">{filtered.length}건</p>
          <div className="min-h-0 flex-1">
            {items.map((e) => <EventRow key={e.eventId} event={e} big={elderly} onClick={() => setSelected(e.eventId)} />)}
            {items.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-ink-3">
                <ClipboardList className="h-9 w-9" aria-hidden="true" />
                <p className="text-[0.9375rem]">조건에 맞는 기록이 없어요</p>
              </div>
            )}
          </div>
          <div className="pt-2"><Pagination page={current} totalPages={totalPages} onChange={setPage} /></div>
        </Card>

        <div className="col-span-4 flex flex-col gap-4">
          <Card className="p-6">
            <h2 className="text-[0.9375rem] font-semibold text-ink">최근 7일</h2>
            <dl className="mt-3 space-y-3">
              <Stat k="화재 예방 조치" v={counts.fire} />
              <Stat k="낙상 감지" v={counts.fall} />
              <Stat k="아침 자동 출수" v={counts.routine} />
            </dl>
          </Card>
          {counts.feedback > 0 && !elderly && (
            <Card className="bg-brand-soft p-6">
              <p className="text-[0.9375rem] font-semibold text-[#2a4a8f]">피드백을 기다리는 조치 {counts.feedback}건</p>
              <p className="mt-1 text-[0.875rem] leading-relaxed text-[#2a4a8f]/80">자동 조치가 적절했는지 알려주시면 판단 기준을 다듬는 데 쓰여요.</p>
            </Card>
          )}
        </div>
      </div>

      <EventDetailSheet eventId={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

function Stat({ k, v }: { k: string; v: number }) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-[0.9375rem] text-ink-2">{k}</dt>
      <dd className="tabular text-2xl font-bold text-ink">{v}<span className="ml-0.5 text-[0.875rem] font-medium text-ink-3">건</span></dd>
    </div>
  )
}
