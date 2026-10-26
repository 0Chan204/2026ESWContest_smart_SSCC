import { WifiOff } from 'lucide-react'
import { Toggle } from '@/components/ui/Toggle'
import { DEVICE_GLYPH } from '@/components/DeviceIcon'
import { summarize } from '@/lib/device'
import { useHome } from '@/store/HomeStore'
import { ROOM_LABEL } from '@/lib/labels'
import type { Device } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 홈 화면 기기 카드 (v2 구성: 아이콘 / 이름 · 공간 / 상태 / 설명, 켜고 끌 수 있는 기기만 오른쪽 위 스위치).
 * 켜져 동작 중이면 밝은 카드 + 색 아이콘, 꺼졌거나 대기·연결 끊김이면 한 단계 어두운 카드 + 흐린 글자.
 * 인덕션·정수기는 조회 전용이라 스위치가 없다.
 * 공기청정기는 공기질 등급을 크게, 자동으로 켜졌으면 그 이유를 설명 줄에 쓴다.
 */
export function DeviceCard({ device: d, onOpen }: { device: Device; onOpen: () => void }) {
  const { controlDevice } = useHome()
  const s = summarize(d)
  const { Icon, on: glyph } = DEVICE_GLYPH[d.kind]
  const switchable = d.online && (d.kind === 'fan' || d.kind === 'light' || d.kind === 'air')
  const on = d.kind === 'fan' || d.kind === 'light' || d.kind === 'air' ? d.on : false
  const active = d.online && s.active
  const danger = s.risk === 'danger'

  return (
    <div className={cn('relative h-full min-w-0 rounded-2xl',
      danger ? 'bg-danger-soft' : active ? 'bg-card-on shadow-[var(--shadow-tile)]' : 'bg-tile-off ring-1 ring-inset ring-line/70')}>
      <button type="button" onClick={onOpen}
        className="press flex h-full w-full flex-col items-start rounded-2xl px-5 py-4 text-left">
        <Icon className={cn('h-7 w-7', danger ? 'text-danger' : active ? glyph : 'text-ink-3 opacity-70')} strokeWidth={1.75} aria-hidden="true" />
        <span className="mt-auto block w-full min-w-0 pt-3">
          <span className={cn('block truncate text-[0.875rem] font-medium', active || danger ? 'text-ink-2' : 'text-ink-3')}>
            {d.name}<span className="font-normal text-ink-3"> · {ROOM_LABEL[d.room]}</span>
          </span>
          <span className={cn('mt-0.5 flex items-center gap-1.5 truncate text-[1.25rem] font-bold',
            danger ? 'text-danger' : active ? 'text-ink' : 'text-ink-2')}>
            {!d.online && <WifiOff className="h-4 w-4 shrink-0" aria-hidden="true" />}
            {d.online ? s.status : '응답 없음'}
          </span>
          <span className={cn('mt-0.5 block truncate text-[0.8125rem]', active ? 'text-ink-2' : 'text-ink-3')}>{s.detail}</span>
        </span>
      </button>
      {switchable && (
        <div className="absolute top-3.5 right-4">
          <Toggle checked={on} label={`${d.name} ${on ? '끄기' : '켜기'}`} onChange={(next) => controlDevice(d.id, { on: next })} />
        </div>
      )}
    </div>
  )
}
