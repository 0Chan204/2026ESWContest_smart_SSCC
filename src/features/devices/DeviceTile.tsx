import { Tile } from '@/components/ui/Tile'
import { DEVICE_GLYPH } from '@/components/DeviceIcon'
import { useHome } from '@/store/HomeStore'
import { summarize } from '@/lib/device'
import type { Device } from '@/types'

/**
 * 기기 타일. 홈 앱처럼
 *  - 조명·환풍기: 타일을 누르면 켜고 끈다, 오른쪽 아래 … 로 상세
 *  - 인덕션·정수기: 조회 전용 — 누르면 상세
 *  - 연결 끊김: 누르면 상세(다시 연결)
 */
export function DeviceTile({ device: d, onOpen, wide = false, big = false, className }: {
  device: Device
  onOpen: () => void
  wide?: boolean
  big?: boolean
  className?: string
}) {
  const { controlDevice } = useHome()
  const { Icon, on: glyph } = DEVICE_GLYPH[d.kind]
  const s = summarize(d)

  if (!d.online) {
    return <Tile icon={Icon} name={d.name} state="응답 없음" tone="muted" onPress={onOpen} wide={wide} big={big} className={className} />
  }
  if (d.kind === 'fan' || d.kind === 'light') {
    return (
      <Tile icon={Icon} glyph={glyph} name={d.name} state={d.on ? s.status : '꺼짐'} on={d.on} wide={wide} big={big} className={className}
        onPress={() => void controlDevice(d.id, { on: !d.on })} onMore={onOpen} moreLabel={`${d.name} 설정`} />
    )
  }
  if (d.kind === 'induction') {
    const hot = d.burner.deviceState === 'overheated'
    const cooking = d.burner.deviceState === 'on'
    return (
      <Tile icon={Icon} glyph={glyph} name={d.name} state={s.status} on={cooking} tone={hot ? 'danger' : undefined}
        value={wide ? `${Math.round(d.burner.temperature)}°` : undefined} onPress={onOpen} wide={wide} big={big} className={className} />
    )
  }
  return <Tile icon={Icon} glyph={glyph} name={d.name} state={s.status} on={d.dispensing} onPress={onOpen} wide={wide} big={big} className={className} />
}
