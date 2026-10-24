import { Fan, Lightbulb, User } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { BrightnessSlider } from '@/components/ui/BrightnessSlider'
import { Segmented } from '@/components/ui/Segmented'
import { Toggle } from '@/components/ui/Toggle'
import { LOCATION_LABEL, ROOM_LABEL } from '@/lib/labels'
import { brightnessLabel, lightLevel, savingLevel, summarize } from '@/lib/device'
import type { FanDevice, LightDevice, RoomId, Risk } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 집 평면도. 전시 부스(침실 · 거실 · 욕실 · 주방)를 실제 집처럼 배치한다.
 * 벽은 얇은 선, 지금 있는 방에 파란 점(퍼지는 원), 위험한 방은 상태색 바탕.
 * 위치는 각 공간의 Wi-Fi 센싱 결과를 중앙제어가 종합한 값.
 *
 * 조명은 평면도에서 바로 켜고 끈다.
 *  - card  : 홈 화면 칸. 조명이 있는 방에 전구 버튼(누르면 켜기/끄기), 켜진 방은 따뜻한 색
 *  - sheet : 위치 팝업. 방마다 밝기 슬라이더 + 환풍기(스위치 · 약/중/강).
 *            어르신 모드는 큰 스위치만 둔다.
 */
const ORDER: RoomId[] = ['bedroom', 'living', 'bathroom', 'kitchen']
const CARD_LAYOUT: Record<RoomId, string> = {
  bedroom: 'col-start-1 col-span-2 row-start-1',
  bathroom: 'col-start-1 col-span-2 row-start-2',
  living: 'col-start-3 col-span-3 row-start-1',
  kitchen: 'col-start-3 col-span-3 row-start-2',
}
const CORNER: Record<RoomId, string> = {
  bedroom: 'rounded-tl-[10px]', living: 'rounded-tr-[10px]', bathroom: 'rounded-bl-[10px]', kitchen: 'rounded-br-[10px]',
}

const RISK_BG: Partial<Record<Risk, string>> = { danger: 'bg-danger-soft', warning: 'bg-warn-soft', caution: 'bg-caution-soft' }
const RISK_INK: Partial<Record<Risk, string>> = { danger: 'text-danger', warning: 'text-warn', caution: 'text-caution' }

function useRooms() {
  const { location, kitchenRisk, bathroomRisk, devices } = useHome()
  const risk: Record<RoomId, Risk> = { bedroom: 'normal', living: 'normal', kitchen: kitchenRisk, bathroom: bathroomRisk }
  const lights = devices.filter((d): d is LightDevice => d.kind === 'light')
  const fans = devices.filter((d): d is FanDevice => d.kind === 'fan')
  return {
    location,
    rooms: ORDER.map((id) => ({
      id, risk: risk[id], here: location === id,
      lights: lights.filter((d) => d.room === id), fans: fans.filter((d) => d.room === id),
    })),
  }
}

/** 홈 화면 칸의 작은 평면도 */
export function HomeMap({ className }: { className?: string }) {
  const { location, rooms } = useRooms()
  return (
    <div role="group" aria-label={`집 평면도 · 현재 위치 ${LOCATION_LABEL[location]}`}
      className={cn('grid grid-cols-5 grid-rows-2 gap-[2px] overflow-hidden rounded-xl bg-line p-[2px]', className)}>
      {rooms.map(({ id, risk, here, lights }) => {
        const lit = lights.some((l) => l.online && l.on)
        return (
          <div key={id} className={cn('@container relative min-h-14 p-2.5', CARD_LAYOUT[id], CORNER[id],
            RISK_BG[risk] ?? (lit ? 'bg-glyph-light/15' : 'bg-surface'))}>
            <span className={cn('text-[0.75rem] font-medium', RISK_INK[risk] ?? 'text-ink-3')}>{ROOM_LABEL[id]}</span>
            {here && (
              <span className="locate absolute top-1/2 left-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full text-brand ring-[3px] ring-surface"
                style={{ background: 'currentColor' }} aria-label="지금 위치" role="img" />
            )}
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
      <Lightbulb className={cn('h-6 w-6', on ? 'fill-glyph-light/40 text-glyph-light' : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
    </button>
  )
}

const SHEET_CORNER: Record<RoomId, string> = {
  bedroom: 'rounded-t-[10px] sm:rounded-tr-none', living: 'sm:rounded-tr-[10px]',
  bathroom: 'sm:rounded-bl-[10px]', kitchen: 'rounded-b-[10px] sm:rounded-bl-none',
}

/** 위치 팝업의 큰 평면도 — 방마다 조명 · 환풍기 조작 (휴대폰 폭에서는 방을 한 줄씩) */
export function HomeMapControls({ className }: { className?: string }) {
  const { location, rooms } = useRooms()
  const { controlDevice } = useHome()
  const { elderly } = usePreferences()
  return (
    <div role="group" aria-label={`집 평면도 · 현재 위치 ${LOCATION_LABEL[location]}`}
      className={cn('grid grid-cols-1 gap-[2px] overflow-hidden rounded-xl bg-line p-[2px] sm:grid-cols-2 sm:grid-rows-2', className)}>
      {rooms.map(({ id, risk, here, lights, fans }) => (
        <section key={id} aria-label={ROOM_LABEL[id]}
          className={cn('@container flex min-w-0 flex-col gap-2 p-4', elderly && 'short:gap-1.5 short:p-3', SHEET_CORNER[id],
            RISK_BG[risk] ?? (here ? 'bg-brand-soft' : 'bg-surface'))}>
          <div className="flex min-h-10 items-center justify-between gap-3">
            <h3 className={cn('font-semibold', elderly ? 'text-[1.375rem]' : 'text-[1.0625rem]',
              RISK_INK[risk] ?? (here ? 'text-brand-ink' : 'text-ink-2'))}>{ROOM_LABEL[id]}</h3>
            {here && (
              <span className="locate relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand text-brand" role="img" aria-label="지금 여기 계세요">
                <span className="relative flex"><User className="h-5 w-5 text-white" aria-hidden="true" /></span>
              </span>
            )}
          </div>
          {(lights.length > 0 || fans.length > 0) && (
            <div className="mt-auto flex flex-col gap-2">
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
            </div>
          )}
        </section>
      ))}
    </div>
  )
}

/** 환풍기 한 줄: 아이콘 · 이름 · 약/중/강 · 스위치 (슬라이더와 같은 알약 모양) */
function FanRow({ fan: f }: { fan: FanDevice }) {
  const { controlDevice } = useHome()
  const on = f.online && f.on
  return (
    <div className={cn('flex h-16 items-center gap-2.5 rounded-2xl bg-fill pr-2.5 pl-4', !f.online && 'opacity-40')}>
      <Fan className={cn('h-6 w-6 shrink-0', on ? 'text-glyph-fan' : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
      <span className="hidden min-w-0 flex-1 truncate text-[1rem] font-semibold text-ink @[21rem]:block">환풍기</span>
      {/* 꺼져 있어도 마지막 풍량을 보여준다. 풍량을 고르면 그 풍량으로 켜진다 */}
      <Segmented label={`${f.name} 풍량`} value={f.speed} size="touch" className="ml-auto w-[10rem] shrink-0"
        options={[{ value: 1, label: '약' }, { value: 2, label: '중' }, { value: 3, label: '강' }]}
        onChange={(v) => { if (f.online) void controlDevice(f.id, { speed: v }) }} />
      <span className="flex h-11 shrink-0 items-center px-1">
        <Toggle checked={on} disabled={!f.online} label={`${f.name} ${on ? '끄기' : '켜기'}`} onChange={(next) => void controlDevice(f.id, { on: next })} />
      </span>
    </div>
  )
}

/** 어르신 모드: 이름과 큰 스위치만 */
function SwitchRow({ icon: Icon, glyph, name, device: d, onChange }: {
  icon: typeof Fan; glyph: string; name: string; device: LightDevice | FanDevice; onChange: (on: boolean) => void
}) {
  const on = d.online && d.on
  const s = summarize(d)
  return (
    <div className={cn('flex min-h-16 items-center gap-3 rounded-2xl bg-fill px-4 short:min-h-14', !d.online && 'opacity-40')}>
      <Icon className={cn('h-7 w-7 shrink-0', on ? glyph : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[1.25rem] font-semibold text-ink">{name}</span>
        <span className="block truncate text-[1rem] text-ink-2">{d.online ? s.status : '응답 없음'}</span>
      </span>
      <Toggle size="lg" checked={on} disabled={!d.online} label={`${d.name} ${on ? '끄기' : '켜기'}`} onChange={onChange} />
    </div>
  )
}
