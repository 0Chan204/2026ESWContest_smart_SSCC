import { useState } from 'react'
import { CookingPot, Lock, Radar } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card } from '@/components/ui/Card'
import { Segmented } from '@/components/ui/Segmented'
import { FitList } from '@/components/ui/FitList'
import { Sparkline } from '@/components/ui/Sparkline'
import { Tile } from '@/components/ui/Tile'
import { ListGroup, ListRow } from '@/components/ui/List'
import { DeviceTile } from '@/features/devices/DeviceTile'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { SessionTimeline } from '@/features/history/SessionTimeline'
import { EventRow } from '@/features/history/EventRow'
import { EventDetailSheet } from '@/features/history/EventDetailSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { describeKitchen } from '@/lib/rooms'
import { summarize } from '@/lib/device'
import { LOCATION_LABEL } from '@/lib/labels'
import { formatDuration, formatTime } from '@/lib/format'
import type { InductionDevice, Presence } from '@/types'
import { cn } from '@/lib/cn'

const ZONE_LABEL = { kitchen: '주방', near: '주방 근처', far: '멀리', unknown: '확인 중' } as const

export function KitchenPage() {
  const { elderly } = usePreferences()
  return elderly ? <KitchenElderly /> : <KitchenNormal />
}

function KitchenNormal() {
  const { induction, presence, devices, session, events } = useHome()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [eventId, setEventId] = useState<string | null>(null)
  // 같은 자리에서 '이번 조리' 와 '주방 기록' 을 바꿔 본다
  const [tab, setTab] = useState<'session' | 'records'>(session ? 'session' : 'records')
  const others = devices.filter((d) => d.room === 'kitchen' && d.kind !== 'induction')
  const recent = events.filter((e) => e.room === 'kitchen' && e.type !== 'cooking_started').slice(0, 8)

  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="주방" />
      <div className="grid grid-cols-1 gap-6 px-5 pt-5 pb-6 md:px-8 wall:min-h-0 wall:flex-1 wall:grid-cols-12 wall:pb-7 wall:short:gap-4 wall:short:pt-4 wall:short:pb-5">
        <div className="flex flex-col gap-4 wall:col-span-8 wall:min-h-0">
          {induction && <InductionPanel device={induction} onOpen={() => setDeviceId(induction.id)} />}
          <div className="grid shrink-0 grid-cols-2 gap-3 auto-rows-[136px] sm:grid-cols-3 wall:short:auto-rows-[120px]">
            <PresenceTile p={presence.kitchen} />
            {others.map((d) => <DeviceTile key={d.id} device={d} onOpen={() => setDeviceId(d.id)} />)}
          </div>
        </div>

        <div className="flex flex-col wall:col-span-4 wall:min-h-0">
          <Segmented<'session' | 'records'> label="주방 정보" value={tab} onChange={setTab}
            options={[{ value: 'session', label: '이번 조리' }, { value: 'records', label: '주방 기록' }]} />
          <div className="mt-4 flex flex-col wall:min-h-0 wall:flex-1">
            {tab === 'session' && (session ? (
              <>
                <ListGroup>
                  <ListRow title="시작" value={formatTime(session.startedAt)} />
                  <ListRow title="진행" value={formatDuration((Date.now() - new Date(session.startedAt).getTime()) / 1000)} />
                  <ListRow title="최고 온도" value={`${Math.round(session.peakTemperature)}°C`} />
                </ListGroup>
                <ListGroup title="흐름" className="mt-5 flex flex-col wall:min-h-0 wall:flex-1" bodyClassName="px-4 pt-4 wall:min-h-0 wall:flex-1">
                  <SessionTimeline session={session} max={6} />
                </ListGroup>
              </>
            ) : (
              <Card className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center wall:flex-1">
                <CookingPot className="h-8 w-8 text-ink-3" strokeWidth={1.6} aria-hidden="true" />
                <p className="text-[1rem] font-semibold text-ink">조리 중 아님</p>
                <p className="text-[0.875rem] text-ink-3">인덕션을 켜면 흐름이 기록돼요</p>
              </Card>
            ))}
            {tab === 'records' && (
              <ListGroup className="flex flex-col wall:min-h-0 wall:flex-1" bodyClassName="wall:min-h-0 wall:flex-1">
                <FitList className="wall:h-full" items={recent} getKey={(e) => e.eventId}
                  render={(e) => <EventRow event={e} compact onClick={() => setEventId(e.eventId)} />}
                  empty={<p className="px-4 py-4 text-[0.9375rem] text-ink-3">기록 없음</p>} />
              </ListGroup>
            )}
          </div>
        </div>
      </div>
      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <EventDetailSheet eventId={eventId} onClose={() => setEventId(null)} />
    </div>
  )
}

/** 인덕션 — 조회 전용. 큰 온도 숫자 + 최근 3분 그래프(과열 기준선) */
function InductionPanel({ device, onOpen }: { device: InductionDevice; onOpen: () => void }) {
  const { policy } = useHome()
  const s = summarize(device)
  const b = device.burner
  const hot = b.deviceState === 'overheated'
  const cooking = b.deviceState === 'on'
  return (
    <Card className={cn('flex flex-col p-5 md:p-6 wall:min-h-0 wall:flex-1', hot && 'bg-danger-soft')}>
      <button type="button" onClick={onOpen} className="press flex items-start justify-between gap-4 text-left">
        <span>
          <span className="block text-[1.0625rem] font-semibold text-ink">인덕션</span>
          <span className={cn('block text-[0.9375rem]', hot ? 'font-semibold text-danger' : 'text-ink-2')}>
            {s.status}{cooking && ` · ${formatDuration(b.activeSec)}째`}
          </span>
        </span>
        <span className="flex items-center gap-1 text-[0.8125rem] text-ink-3">
          <Lock className="h-3.5 w-3.5" aria-hidden="true" />조회 전용
        </span>
      </button>

      <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-8 wall:min-h-0 wall:flex-1">
        <p className={cn('tabular shrink-0 text-[5rem] leading-[0.9] font-extralight tracking-[-0.04em] wall:short:text-[4rem]',
          hot ? 'text-danger' : cooking ? 'text-ink' : 'text-ink-2')}>
          {Math.round(b.temperature)}<span className="align-top text-[2rem] font-light text-ink-3">°C</span>
        </p>
        <div className="relative flex h-36 min-w-0 flex-1 flex-col sm:h-auto sm:self-stretch sm:min-h-32 wall:min-h-0">
          <span className="absolute top-0 right-0 text-[0.75rem] text-danger">과열 {policy.overheatEnterC}°</span>
          <div className="min-h-0 flex-1 pt-5">
            <Sparkline values={device.tempHistory} max={Math.max(170, policy.overheatEnterC + 15)} threshold={policy.overheatEnterC}
              color={hot ? 'var(--color-danger)' : 'var(--color-glyph-heat)'} label="최근 3분 온도 추이" />
          </div>
          <span className="mt-1 flex justify-between text-[0.75rem] text-ink-3"><span>3분 전</span><span>지금</span></span>
        </div>
      </div>
    </Card>
  )
}

function PresenceTile({ p }: { p: Presence | undefined }) {
  const { location } = useHome()
  const here = !!p?.present
  const state = !p ? '확인 중'
    : here ? `사람 있음 · ${Math.round(p.confidence * 100)}%`
    : `${formatDuration(p.absentSec)} 비어 있음 · ${p.zone === 'unknown' ? LOCATION_LABEL[location] : ZONE_LABEL[p.zone]}`
  return <Tile icon={Radar} glyph="text-brand-ink" name="재실 감지" state={state} on={here} />
}

/* ── 어르신 모드 ───────────────────────────────────────────────────────── */
function KitchenElderly() {
  const { induction, presence, kitchenPhase } = useHome()
  const line = describeKitchen(kitchenPhase, induction, presence.kitchen)
  const b = induction?.burner
  const hot = b?.deviceState === 'overheated'
  const here = !!presence.kitchen?.present
  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="주방" />
      <div className="grid grid-cols-1 gap-4 px-5 pt-5 pb-7 auto-rows-[220px] md:grid-cols-2 md:px-8 wall:min-h-0 wall:flex-1 wall:auto-rows-auto wall:grid-rows-[minmax(0,1fr)]">
        <Tile big icon={CookingPot} glyph="text-glyph-heat" name="인덕션" state={line.short}
          on={b?.deviceState === 'on'} tone={hot ? 'danger' : line.risk === 'warning' || line.risk === 'caution' ? 'warn' : undefined}
          value={b ? `${Math.round(b.temperature)}°` : undefined} />
        <Tile big icon={Radar} glyph="text-brand-ink" name="주방에" on={here} tone={here ? undefined : line.risk !== 'normal' ? 'warn' : undefined}
          state={here ? '사람이 있어요' : `아무도 없어요 · ${formatDuration(presence.kitchen?.absentSec ?? 0)}`} />
      </div>
    </div>
  )
}
