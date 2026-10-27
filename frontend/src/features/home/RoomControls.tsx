import { AirVent, Fan, Lightbulb } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { BrightnessSlider } from '@/components/ui/BrightnessSlider'
import { Segmented } from '@/components/ui/Segmented'
import { Toggle } from '@/components/ui/Toggle'
import { airAutoReason, lightLevel, pm25Text, savingLevel, summarize } from '@/lib/device'
import { AIR_LEVEL_LABEL } from '@/lib/labels'
import type { AirPurifierDevice, FanDevice, LightDevice } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 한 공간의 조작 줄: 조명 밝기 슬라이더 · 환풍기(약/중/강 · 스위치) · 공기청정기(스위치).
 * 어르신 모드는 이름과 큰 스위치만 둔다.
 */
export function RoomControls({ lights, fans, airs }: { lights: LightDevice[]; fans: FanDevice[]; airs: AirPurifierDevice[] }) {
  const { controlDevice } = useHome()
  const { elderly } = usePreferences()
  if (lights.length + fans.length + airs.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {lights.map((l) => elderly
        ? <SwitchRow key={l.id} icon={Lightbulb} glyph="text-glyph-light" name="조명" device={l}
            onChange={(on) => void controlDevice(l.id, { on })} />
        : <BrightnessSlider key={l.id} size="lg" name="조명" label={`${l.name} 밝기`} disabled={!l.online}
            value={lightLevel(l)} steps={l.brightnessSteps} savingLevel={savingLevel(l)}
            onToggle={() => void controlDevice(l.id, { on: !l.on })}
            onCommit={(v) => void controlDevice(l.id, v <= 0 ? { on: false } : { brightness: v })} />)}
      {fans.map((f) => elderly
        ? <SwitchRow key={f.id} icon={Fan} glyph="text-glyph-fan" name="환풍기" device={f}
            onChange={(on) => void controlDevice(f.id, { on })} />
        : <FanRow key={f.id} fan={f} />)}
      {airs.map((a) => elderly
        ? <SwitchRow key={a.id} icon={AirVent} glyph="text-glyph-air" name="공기청정기" device={a}
            onChange={(on) => void controlDevice(a.id, { on })} />
        : <AirRow key={a.id} air={a} />)}
    </div>
  )
}

/** 환풍기 한 줄: 아이콘 · 이름 · 약/중/강 · 스위치 (슬라이더와 같은 알약 모양) */
function FanRow({ fan: f }: { fan: FanDevice }) {
  const { controlDevice } = useHome()
  const on = f.online && f.on
  return (
    <div className={cn('@container flex h-16 items-center gap-2.5 rounded-2xl bg-fill pr-2.5 pl-4', !f.online && 'opacity-40')}>
      <Fan className={cn('h-6 w-6 shrink-0', on ? 'text-glyph-fan' : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
      <span className="hidden min-w-0 flex-1 truncate text-[1rem] font-semibold text-ink @[21rem]:block">환풍기</span>
      {/* 꺼져 있어도 마지막 풍량을 보여준다. 풍량을 고르면 그 풍량으로 켜진다 */}
      <Segmented label={`${f.name} 풍량`} value={f.speed} size="touch" className="ml-auto max-w-[10rem] min-w-0 flex-1"
        options={[{ value: 1, label: '약' }, { value: 2, label: '중' }, { value: 3, label: '강' }]}
        onChange={(v) => { if (f.online) void controlDevice(f.id, { speed: v }) }} />
      <span className="flex h-11 shrink-0 items-center px-1">
        <Toggle checked={on} disabled={!f.online} label={`${f.name} ${on ? '끄기' : '켜기'}`} onChange={(next) => void controlDevice(f.id, { on: next })} />
      </span>
    </div>
  )
}

/** 공기청정기 한 줄: 아이콘 · 이름 · 공기질 · 스위치. 자동으로 켜졌으면 이유를 보여준다 */
function AirRow({ air: a }: { air: AirPurifierDevice }) {
  const { controlDevice } = useHome()
  const on = a.online && a.on
  const level = a.airQuality?.level
  const line = (on && airAutoReason(a, true)) || `${level ? `공기 ${AIR_LEVEL_LABEL[level]} · ` : ''}${pm25Text(a)}`
  return (
    <div className={cn('flex h-16 items-center gap-2.5 rounded-2xl bg-fill pr-2.5 pl-4', !a.online && 'opacity-40')}>
      <AirVent className={cn('h-6 w-6 shrink-0', on ? 'text-glyph-air' : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[1rem] font-semibold text-ink">공기청정기</span>
        <span className="block truncate text-[0.8125rem] text-ink-2">{a.online ? line : '응답 없음'}</span>
      </span>
      <span className="flex h-11 shrink-0 items-center px-1">
        <Toggle checked={on} disabled={!a.online} label={`${a.name} ${on ? '끄기' : '켜기'}`} onChange={(next) => void controlDevice(a.id, { on: next })} />
      </span>
    </div>
  )
}

/** 어르신 모드: 이름과 큰 스위치만 */
function SwitchRow({ icon: Icon, glyph, name, device: d, onChange }: {
  icon: typeof Fan; glyph: string; name: string; device: LightDevice | FanDevice | AirPurifierDevice; onChange: (on: boolean) => void
}) {
  const on = d.online && d.on
  const s = summarize(d)
  return (
    <div className={cn('flex min-h-16 items-center gap-3 rounded-2xl bg-fill px-4 short:min-h-14', !d.online && 'opacity-40')}>
      <Icon className={cn('h-7 w-7 shrink-0', on ? glyph : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[1.25rem] font-semibold text-ink">{name}</span>
        <span className="block truncate text-[1rem] text-ink-2">{d.online ? (on || d.kind === 'air' ? s.status : '꺼짐') : '응답 없음'}</span>
      </span>
      <Toggle size="lg" checked={on} disabled={!d.online} label={`${d.name} ${on ? '끄기' : '켜기'}`} onChange={onChange} />
    </div>
  )
}
