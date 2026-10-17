import { useHome } from '@/store/HomeStore'
import { LOCATION_LABEL, ROOM_LABEL } from '@/lib/labels'
import type { RoomId, Risk } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 집 평면도. 전시 부스(침실 · 거실 · 욕실 · 주방)를 실제 집처럼 배치한다.
 * 벽은 얇은 선, 지금 있는 방에 파란 점(퍼지는 원), 위험한 방은 상태색 바탕.
 * 위치는 각 공간의 Wi-Fi 센싱 결과를 중앙제어가 종합한 값.
 */
const LAYOUT: Record<RoomId, string> = {
  bedroom: 'col-start-1 col-span-2 row-start-1',
  bathroom: 'col-start-1 col-span-2 row-start-2',
  living: 'col-start-3 col-span-3 row-start-1',
  kitchen: 'col-start-3 col-span-3 row-start-2',
}

export function HomeMap({ className }: { className?: string }) {
  const { location, kitchenRisk, bathroomRisk } = useHome()
  const risk: Record<RoomId, Risk> = { bedroom: 'normal', living: 'normal', kitchen: kitchenRisk, bathroom: bathroomRisk }
  return (
    <div role="img" aria-label={`집 평면도 · 현재 위치 ${LOCATION_LABEL[location]}`}
      className={cn('grid grid-cols-5 grid-rows-2 gap-[2px] overflow-hidden rounded-xl bg-line p-[2px]', className)}>
      {(Object.keys(LAYOUT) as RoomId[]).map((id) => {
        const here = location === id
        const r = risk[id]
        const bg = r === 'danger' ? 'bg-danger-soft' : r === 'warning' ? 'bg-warn-soft' : r === 'caution' ? 'bg-caution-soft' : 'bg-surface'
        return (
          <div key={id} className={cn('relative min-h-14 p-2.5', LAYOUT[id], bg, id === 'bedroom' && 'rounded-tl-[10px]',
            id === 'living' && 'rounded-tr-[10px]', id === 'bathroom' && 'rounded-bl-[10px]', id === 'kitchen' && 'rounded-br-[10px]')}>
            <span className={cn('text-[0.75rem] font-medium',
              r === 'danger' ? 'text-danger' : r === 'warning' ? 'text-warn' : r === 'caution' ? 'text-caution' : 'text-ink-3')}>
              {ROOM_LABEL[id]}
            </span>
            {here && (
              <span className="locate absolute top-1/2 left-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full text-brand ring-[3px] ring-surface"
                style={{ background: 'currentColor' }} aria-hidden="true" />
            )}
          </div>
        )
      })}
    </div>
  )
}
