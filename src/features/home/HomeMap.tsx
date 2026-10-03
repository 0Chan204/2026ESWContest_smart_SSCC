import { User } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { LOCATION_LABEL, RISK_TONE, ROOM_LABEL } from '@/lib/labels'
import type { RoomId, Risk } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 집 평면 약도. 전시 부스 배치(침실 · 거실 · 주방 · 욕실)를 그대로 따른다.
 * 사용자가 있는 방에 사람 표시, 위험한 방은 상태 색으로 강조한다.
 * 위치는 각 공간의 Wi-Fi 센싱 노드 결과를 중앙제어가 종합한 값.
 */
export function HomeMap({ height = 132 }: { height?: number }) {
  const { location, kitchenRisk, bathroomRisk } = useHome()
  const rooms: { id: RoomId; flex: number; risk: Risk }[] = [
    { id: 'bedroom', flex: 1.05, risk: 'normal' },
    { id: 'living', flex: 1.2, risk: 'normal' },
    { id: 'kitchen', flex: 1.35, risk: kitchenRisk },
    { id: 'bathroom', flex: 0.85, risk: bathroomRisk },
  ]
  return (
    <div>
      <div className="flex gap-1.5" style={{ height }} role="img"
        aria-label={`집 약도 · 현재 위치 ${LOCATION_LABEL[location]}`}>
        {rooms.map((r) => {
          const here = location === r.id
          const alert = r.risk !== 'normal'
          return (
            <div key={r.id} style={{ flex: r.flex }}
              className={cn('relative flex flex-col justify-between rounded-2xl p-3',
                alert ? RISK_TONE[r.risk].soft : here ? 'bg-brand-soft' : 'bg-sunken')}>
              <span className={cn('text-[0.8125rem] font-semibold', alert ? RISK_TONE[r.risk].text : here ? 'text-brand' : 'text-ink-2')}>
                {ROOM_LABEL[r.id]}
              </span>
              {here && (
                <span className="flex h-9 w-9 items-center justify-center self-center rounded-full bg-brand text-white shadow-[0_2px_6px_rgba(47,107,237,0.35)]">
                  <User className="h-5 w-5" aria-hidden="true" />
                </span>
              )}
              {alert && <span className={cn('absolute top-3 right-3 h-2.5 w-2.5 rounded-full', RISK_TONE[r.risk].strong, r.risk === 'danger' && 'soft-pulse')} />}
              <span />
            </div>
          )
        })}
      </div>
      {(location === 'outside' || location === 'unknown') && (
        <p className="mt-2 text-[0.8125rem] text-ink-2">{location === 'outside' ? '집 밖으로 나가신 것 같아요.' : '센서 신호가 약해 위치를 확인하고 있어요.'}</p>
      )}
    </div>
  )
}
