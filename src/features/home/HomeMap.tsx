import { Lightbulb } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { LOCATION_LABEL, ROOM_LABEL } from '@/lib/labels'
import { brightnessLabel, savingLevel } from '@/lib/device'
import { roomPresence } from '@/lib/sensing'
import type { HouseRoom, LightDevice } from '@/types'
import { cn } from '@/lib/cn'
import { RISK_BG, RISK_INK, useRooms } from './rooms'

/**
 * 집 평면도. 전시 부스처럼 주방 | 침실 | 욕실 세 공간을 나란히 붙여 그린다.
 * 벽은 얇은 선, 지금 있는 방에 파란 점(퍼지는 원)과 재실 신뢰도, 위험한 방은 상태색 바탕.
 * 위치는 각 공간의 Wi-Fi 센싱 결과를 재실 판단 담당이 종합한 값.
 * 조명은 평면도에서 바로 켜고 끈다 (방마다 전구 버튼, 켜진 방은 따뜻한 색).
 */
/** 바깥 모서리만 둥글게 (가로 배치 기준) */
const CORNER: Record<HouseRoom, string> = {
  kitchen: 'rounded-l-[10px]', bedroom: '', bathroom: 'rounded-r-[10px]',
}

/** 홈 화면 칸의 작은 평면도 */
export function HomeMap({ className }: { className?: string }) {
  const { location, rooms } = useRooms()
  const { latestSensing } = useHome()
  return (
    <div role="group" aria-label={`집 평면도 · 현재 위치 ${LOCATION_LABEL[location]}`}
      className={cn('grid grid-cols-[1.12fr_1.12fr_1fr] gap-[2px] overflow-hidden rounded-xl bg-line p-[2px]', className)}>
      {rooms.map(({ id, risk, here, lights }) => {
        const lit = lights.some((l) => l.online && l.on)
        const p = roomPresence(latestSensing, id)
        const live = p.freshness === 'live'
        const status = !latestSensing ? (here ? '사람 있음' : '확인 중')
          : !live ? '확인 중'
          : p.present ? (p.activity ?? '사람 있음') : '비어 있음'
        return (
          <div key={id} className={cn('@container relative flex min-h-20 min-w-0 flex-col justify-between p-2.5', CORNER[id],
            RISK_BG[risk] ?? (lit ? 'bg-glyph-light/15' : 'bg-surface'))}>
            <span className={cn('text-[0.8125rem] font-semibold', RISK_INK[risk] ?? (here ? 'text-brand-ink' : 'text-ink-2'))}>{ROOM_LABEL[id]}</span>
            {here && (
              <span className="absolute top-1/2 left-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1.5">
                <span className="locate relative h-3.5 w-3.5 rounded-full text-brand ring-[3px] ring-surface @[14rem]:h-4 @[14rem]:w-4"
                  style={{ background: 'currentColor' }} aria-label="지금 위치" role="img" />
                {live && p.percent !== null && (
                  <span className="tabular text-[0.75rem] font-semibold text-brand-ink @[14rem]:text-[0.9375rem]" aria-label={`재실 신뢰도 ${p.percent}%`}>{p.percent}%</span>
                )}
              </span>
            )}
            <span className={cn('truncate text-[0.75rem]', p.present && live ? 'font-medium text-ink' : 'text-ink-3')}>{status}</span>
            {lights.length > 0 && (
              <div className="absolute top-0.5 right-0.5 flex">
                {lights.map((l) => <LightButton key={l.id} light={l} />)}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** 평면도 칸 안 전구 버튼: 누르면 켜기/끄기. 켜져 있으면 밝기를 작게 함께 보여준다 */
function LightButton({ light: l }: { light: LightDevice }) {
  const { controlDevice } = useHome()
  const on = l.online && l.on
  return (
    <button type="button" disabled={!l.online} aria-pressed={on}
      aria-label={`${l.name} ${!l.online ? '응답 없음' : on ? `${brightnessLabel(l.brightness, savingLevel(l))} · 끄기` : '꺼짐 · 켜기'}`}
      onClick={() => void controlDevice(l.id, { on: !l.on })}
      className="press flex h-11 min-w-11 items-center justify-center gap-1 rounded-[10px] px-2 disabled:opacity-40">
      {on && <span className="tabular hidden text-[0.75rem] font-semibold text-ink-2 @[8.5rem]:inline">{l.saving ? '절전' : `${l.brightness}%`}</span>}
      <Lightbulb className={cn('h-6 w-6', on ? 'fill-glyph-light/40 text-glyph-light' : 'text-ink-3', l.blinking && 'soft-pulse')}
        strokeWidth={1.9} aria-hidden="true" />
    </button>
  )
}
