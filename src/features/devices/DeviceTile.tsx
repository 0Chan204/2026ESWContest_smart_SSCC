import { WifiOff } from 'lucide-react'
import { DeviceIcon } from '@/components/DeviceIcon'
import { Toggle } from '@/components/ui/Toggle'
import { isControllable, summarize } from '@/lib/device'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { ROOM_LABEL } from '@/lib/labels'
import type { Device } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 기기 타일 (SmartThings · ThinQ 기기 카드 구성).
 * 아이콘 / 이름 / 상태 / 보조 설명. 제어 가능한 기기만 오른쪽 위에 전원 스위치가 있다.
 */
export function DeviceTile({ device, onOpen, showRoom = true }: { device: Device; onOpen: () => void; showRoom?: boolean }) {
  const { controlDevice } = useHome()
  const { elderly } = usePreferences()
  const s = summarize(device)
  const switchable = isControllable(device) && device.online && (device.kind === 'fan' || device.kind === 'light')
  const on = device.kind === 'fan' || device.kind === 'light' ? device.on : false
  const danger = s.risk === 'danger'

  return (
    <div className={cn('relative h-full rounded-3xl bg-surface', danger && 'ring-2 ring-danger')}>
      <button
        type="button"
        onClick={onOpen}
        className={cn('flex h-full w-full flex-col items-start rounded-3xl text-left transition-colors hover:bg-[#fafbfc]', elderly ? 'p-6' : 'px-5 py-4')}
      >
        <DeviceIcon kind={device.kind} active={s.active && device.online} size={elderly ? 'lg' : 'md'} />
        <span className="mt-auto block w-full pt-3">
          <span className={cn('block font-semibold text-ink-2', elderly ? 'text-lg' : 'text-[0.9375rem]')}>
            {device.name}{showRoom && !elderly && <span className="font-normal text-ink-3"> · {ROOM_LABEL[device.room]}</span>}
          </span>
          <span className={cn('mt-0.5 flex items-center gap-1.5 font-bold', elderly ? 'text-2xl' : 'text-xl',
            !device.online ? 'text-ink-3' : danger ? 'text-danger' : s.active ? 'text-ink' : 'text-ink-3')}>
            {!device.online && <WifiOff className="h-4 w-4" aria-hidden="true" />}
            {s.status}
          </span>
          {!elderly && <span className="mt-1 block truncate text-[0.8125rem] text-ink-3">{s.detail}</span>}
        </span>
      </button>
      {switchable && (
        <div className="absolute top-4 right-5">
          <Toggle checked={on} label={`${device.name} ${on ? '끄기' : '켜기'}`} size={elderly ? 'lg' : 'md'}
            onChange={(next) => controlDevice(device.id, { on: next })} />
        </div>
      )}
    </div>
  )
}
