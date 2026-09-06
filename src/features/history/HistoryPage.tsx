import { useMemo, useState } from 'react'
import { Calendar, ClipboardList, Filter, MapPin, Search } from 'lucide-react'
import { Pagination } from '@/components/Pagination'
import { EventDetailModal } from './EventDetailModal'
import { formatDateShort, toDateInput } from '@/lib/format'
import { ROOM_KEY } from '@/lib/appliance'
import { HISTORY_DAY_SPAN } from '@/data/safetyHistory'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import type { RoomId, SafetyLog } from '@/types'
import { cn } from '@/lib/cn'

type RoomFilter = RoomId | 'all'

function defaultRange(): { from: string; to: string } {
  const to = new Date()
  const from = new Date()
  from.setDate(from.getDate() - HISTORY_DAY_SPAN)
  return { from: toDateInput(from), to: toDateInput(to) }
}

/**
 * 처리 이력 화면.
 *
 * - '상태 감지' / '상태 판단' 같은 중간 이벤트는 애초에 데이터에 없다. 안전 처리만 다룬다.
 * - 테이블 컬럼은 시간 / 구분 / 장소 / 내용 4개. '결과'는 상세에서만 확인한다.
 * - 스크롤 대신 페이지네이션. 어르신 모드는 글자가 크므로 페이지당 건수를 줄인다.
 */
export function HistoryPage() {
  const { t, elderly } = usePreferences()
  const { safetyLogs } = useHomeState()

  const initialRange = useMemo(defaultRange, [])
  const [room, setRoom] = useState<RoomFilter>('all')
  const [from, setFrom] = useState(initialRange.from)
  const [to, setTo] = useState(initialRange.to)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<SafetyLog | null>(null)

  const perPage = elderly ? 4 : 5

  // 필터가 바뀌면 항상 1페이지로 되돌린다.
  function update(apply: () => void) {
    apply()
    setPage(1)
  }

  const filtered = useMemo(() => {
    const keyword = search.trim()
    return safetyLogs.filter((log) => {
      if (room !== 'all' && log.room !== room) return false
      if (from && log.datetime < from) return false
      if (to && log.datetime > `${to}T23:59:59`) return false
      if (keyword && !log.content.includes(keyword)) return false
      return true
    })
  }, [safetyLogs, room, from, to, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage))
  const safePage = Math.min(page, totalPages)
  const pageItems = filtered.slice((safePage - 1) * perPage, safePage * perPage)

  function reset() {
    setRoom('all')
    setFrom(initialRange.from)
    setTo(initialRange.to)
    setSearch('')
    setPage(1)
  }

  return (
    <div className="mx-auto flex h-full max-w-[1400px] flex-col gap-4 px-6 py-4">
      <div className="shrink-0">
        <h1 className={cn('mb-0.5 font-bold text-gray-900', elderly ? 'text-3xl' : 'text-xl')}>
          {t('history.title')}
        </h1>
        <p className={cn('text-gray-500', elderly ? 'text-base' : 'text-sm')}>{t('history.subtitle')}</p>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-3">
        <div className="flex min-h-11 items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3">
          <Filter className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
          <select
            value={room}
            onChange={(e) => update(() => setRoom(e.target.value as RoomFilter))}
            aria-label={t('history.filter.allRooms')}
            className="cursor-pointer bg-transparent text-sm text-gray-800 outline-none"
          >
            <option value="all">{t('history.filter.allRooms')}</option>
            <option value="kitchen">{t('room.kitchen')}</option>
            <option value="bathroom">{t('room.bathroom')}</option>
          </select>
        </div>

        <div className="flex min-h-11 items-center gap-2 rounded-xl border border-gray-200 bg-white px-3">
          <Calendar className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
          <input
            type="date"
            value={from}
            max={to}
            onChange={(e) => update(() => setFrom(e.target.value))}
            aria-label="시작 날짜"
            className="tabular cursor-pointer bg-transparent text-sm text-gray-800 outline-none"
          />
          <span className="text-sm text-gray-400">~</span>
          <input
            type="date"
            value={to}
            min={from}
            onChange={(e) => update(() => setTo(e.target.value))}
            aria-label="종료 날짜"
            className="tabular cursor-pointer bg-transparent text-sm text-gray-800 outline-none"
          />
        </div>

        <div className="flex min-h-11 max-w-xs flex-1 items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3">
          <Search className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
          <input
            type="search"
            value={search}
            placeholder={t('history.filter.search')}
            onChange={(e) => update(() => setSearch(e.target.value))}
            aria-label={t('history.filter.search')}
            className="min-w-0 flex-1 bg-transparent text-sm text-gray-800 outline-none"
          />
        </div>

        <button
          type="button"
          onClick={reset}
          className="min-h-11 rounded-xl border border-gray-200 bg-white px-4 text-sm text-gray-700 transition-colors hover:bg-gray-50"
        >
          {t('history.filter.reset')}
        </button>

        <span className="ml-auto text-sm font-medium text-gray-600">
          {t('history.total', { n: filtered.length })}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
        <table className="w-full">
          <caption className="sr-only">{t('history.subtitle')}</caption>
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/70">
              {[t('history.col.time'), t('history.col.type'), t('history.col.place'), t('history.col.content')].map(
                (col) => (
                  <th
                    key={col}
                    scope="col"
                    className="px-5 py-3 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase"
                  >
                    {col}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {pageItems.map((log, i) => (
              <tr
                key={log.id}
                onClick={() => setSelected(log)}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setSelected(log)
                  }
                }}
                className={cn(
                  'cursor-pointer border-b border-gray-50 transition-colors last:border-0 hover:bg-blue-50/60',
                  i % 2 !== 0 && 'bg-gray-50/40',
                )}
              >
                <td className={cn('tabular px-5 text-sm text-gray-600', elderly ? 'py-4' : 'py-3.5')}>
                  {formatDateShort(log.datetime)}
                </td>
                <td className={cn('px-5', elderly ? 'py-4' : 'py-3.5')}>
                  <span className="inline-flex items-center rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
                    {t('history.type')}
                  </span>
                </td>
                <td className={cn('px-5', elderly ? 'py-4' : 'py-3.5')}>
                  <span className="inline-flex items-center gap-1.5 text-sm text-gray-700">
                    <MapPin className="h-3 w-3 text-gray-400" aria-hidden="true" />
                    {t(ROOM_KEY[log.room])}
                  </span>
                </td>
                <td className={cn('px-5 text-sm break-keep text-gray-800', elderly ? 'py-4' : 'py-3.5')}>
                  {log.content}
                </td>
              </tr>
            ))}
            {pageItems.length === 0 && (
              <tr>
                <td colSpan={4} className="px-5 py-12 text-center text-sm text-gray-500">
                  <ClipboardList className="mx-auto mb-2 h-8 w-8 text-gray-300" aria-hidden="true" />
                  {t('history.empty')}
                </td>
              </tr>
            )}
          </tbody>
        </table>

        <div className="mt-auto border-t border-gray-100">
          <Pagination page={safePage} totalPages={totalPages} onChange={setPage} />
        </div>
      </div>

      <EventDetailModal log={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
