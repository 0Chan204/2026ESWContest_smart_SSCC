import { useState } from 'react'
import { Lock, ShieldCheck, User, UserX } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, CardTitle } from '@/components/ui/Card'
import { Sparkline } from '@/components/ui/Sparkline'
import { StatusText } from '@/components/ui/StatusDot'
import { DeviceIcon } from '@/components/DeviceIcon'
import { DeviceTile } from '@/features/devices/DeviceTile'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { SessionTimeline } from '@/features/history/SessionTimeline'
import { EventRow } from '@/features/history/EventRow'
import { EventDetailSheet } from '@/features/history/EventDetailSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { describeKitchen } from '@/lib/rooms'
import { summarize } from '@/lib/device'
import { BURNER_LABEL, LOCATION_LABEL, RISK_TONE, phaseRisk } from '@/lib/labels'
import { formatAgo, formatDuration, formatTime } from '@/lib/format'
import type { InductionDevice, Presence } from '@/types'
import { cn } from '@/lib/cn'

const ZONE_LABEL = { kitchen: '주방', near: '주방 근처', far: '멀리 있음', unknown: '확인 중' } as const

export function KitchenPage() {
  const { elderly } = usePreferences()
  return elderly ? <KitchenElderly /> : <KitchenNormal />
}

function KitchenNormal() {
  const { induction, presence, devices, session, events, kitchenPhase } = useHome()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [eventId, setEventId] = useState<string | null>(null)
  const others = devices.filter((d) => d.room === 'kitchen' && d.kind !== 'induction')
  const line = describeKitchen(kitchenPhase, induction, presence.kitchen)
  const recent = events.filter((e) => e.room === 'kitchen' && e.type !== 'cooking_started').slice(0, 5)

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="주방" subtitle={<StatusText risk={line.risk}>{line.text}</StatusText>} />
      <div className="grid min-h-0 flex-1 grid-cols-12 gap-5 px-8 pt-5 pb-7">
        <div className="col-span-8 grid min-h-0 gap-5" style={{ gridTemplateRows: 'minmax(0,1fr) auto' }}>
          {induction && <InductionCard device={induction} onOpen={() => setDeviceId(induction.id)} />}
          <div className="grid grid-cols-3 gap-4" style={{ gridAutoRows: '164px' }}>
            <PresenceCard p={presence.kitchen} />
            {others.map((d) => <DeviceTile key={d.id} device={d} showRoom={false} onOpen={() => setDeviceId(d.id)} />)}
          </div>
        </div>

        <Card className="col-span-4 flex min-h-0 flex-col p-6">
          {session ? (
            <>
              <CardTitle title="이번 조리" />
              <dl className="mb-5 grid grid-cols-3 gap-2">
                <MiniStat k="시작" v={formatTime(session.startedAt)} />
                <MiniStat k="진행" v={formatDuration((Date.now() - new Date(session.startedAt).getTime()) / 1000)} />
                <MiniStat k="최고 온도" v={`${Math.round(session.peakTemperature)}°C`} />
              </dl>
              <div className="min-h-0 flex-1 overflow-hidden"><SessionTimeline session={session} max={6} /></div>
            </>
          ) : (
            <>
              <CardTitle title="최근 주방 기록" />
              <div className="-mx-3 min-h-0 flex-1 overflow-hidden">
                {recent.map((e) => <EventRow key={e.eventId} event={e} compact onClick={() => setEventId(e.eventId)} />)}
              </div>
            </>
          )}
          {kitchenPhase === 'normal' && (
            <p className="mt-3 flex items-start gap-2 rounded-2xl bg-sunken px-4 py-3 text-[0.8125rem] leading-relaxed text-ink-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden="true" />
              조리 중 주방을 비우면 1분 뒤 지켜보기 시작하고, 3분이 지나면 화력을 낮춰요.
            </p>
          )}
        </Card>
      </div>
      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <EventDetailSheet eventId={eventId} onClose={() => setEventId(null)} />
    </div>
  )
}

function MiniStat({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-2xl bg-sunken px-3 py-2.5">
      <dt className="text-[0.75rem] text-ink-3">{k}</dt>
      <dd className="tabular mt-0.5 text-[1.0625rem] font-bold text-ink">{v}</dd>
    </div>
  )
}

/** 인덕션 — 조회 전용. 온도 추이와 과열 기준선을 함께 보여준다. */
function InductionCard({ device, onOpen }: { device: InductionDevice; onOpen: () => void }) {
  const { kitchenPhase, policy } = useHome()
  const s = summarize(device)
  const b = device.burner
  const risk = phaseRisk(kitchenPhase)
  const hot = b.deviceState === 'overheated'
  return (
    <Card className={cn('flex min-h-0 flex-col p-7', hot && 'ring-2 ring-danger')}>
      <button type="button" onClick={onOpen} className="flex items-start justify-between gap-4 text-left">
        <div className="flex items-center gap-4">
          <DeviceIcon kind="induction" active={s.active && device.online} size="lg" />
          <div>
            <p className="text-[0.9375rem] font-semibold text-ink-2">인덕션 · 화구 1</p>
            <p className={cn('text-2xl font-bold', hot ? 'text-danger' : s.active ? 'text-ink' : 'text-ink-3')}>
              {b.deviceState === 'on' ? `화력 ${b.level}단` : BURNER_LABEL[b.deviceState]}
              {b.deviceState === 'on' && <span className="ml-2 text-[1rem] font-medium text-ink-2">{formatDuration(b.activeSec)}째 조리 중</span>}
            </p>
          </div>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-sunken px-3 py-1.5 text-[0.8125rem] font-semibold text-ink-2">
          <Lock className="h-3.5 w-3.5" aria-hidden="true" />조회 전용
        </span>
      </button>

      <div className="mt-5 flex min-h-0 flex-1 gap-8">
        <div className="flex shrink-0 flex-col justify-end pb-1">
          <p className={cn('tabular text-[3.5rem] leading-none font-bold tracking-tight', hot ? 'text-danger' : 'text-ink')}>
            {Math.round(b.temperature)}<span className="text-3xl font-semibold text-ink-3">°C</span>
          </p>
          <p className="mt-2 text-[0.875rem] text-ink-3">표면 온도 · 과열 기준 {policy.overheatEnterC}°C</p>
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 rounded-2xl bg-sunken px-3 pt-3">
            <Sparkline values={device.tempHistory} max={Math.max(170, policy.overheatEnterC + 15)} threshold={policy.overheatEnterC}
              color={hot ? '#dc3a3a' : '#2f6bed'} label="최근 3분 온도 추이" />
          </div>
          <p className="mt-2 flex items-center justify-end gap-4 text-[0.75rem] text-ink-3">
            <span className="flex items-center gap-1.5"><span className={cn('h-0.5 w-4 rounded', hot ? 'bg-danger' : 'bg-brand')} />온도 (최근 3분)</span>
            <span className="flex items-center gap-1.5"><span className="h-0 w-4 border-t border-dashed border-danger" />과열 기준 {policy.overheatEnterC}°C</span>
          </p>
        </div>
      </div>

      {risk !== 'normal' && (
        <p className={cn('mt-5 rounded-2xl px-4 py-3 text-[0.9375rem] font-semibold', RISK_TONE[risk].soft, RISK_TONE[risk].text)}>
          {kitchenPhase === 'overheat' && `과열 잠금 중 — ${policy.overheatExitC}°C 이하로 식으면 다시 켤 수 있어요`}
          {kitchenPhase === 'absence_watch' && '주방에 사람이 없어 지켜보는 중이에요'}
          {kitchenPhase === 'auto_reduced' && `사람이 없어 화력을 ${policy.reduceToLevel}단으로 자동으로 낮췄어요`}
          {kitchenPhase === 'auto_off' && '오래 비우셔서 전원을 자동으로 껐어요'}
        </p>
      )}
    </Card>
  )
}

function PresenceCard({ p }: { p: Presence | undefined }) {
  const { location } = useHome()
  if (!p) return <Card className="p-5">{null}</Card>
  const here = p.present
  return (
    <Card className="flex h-full flex-col p-5">
      <span className={cn('flex h-11 w-11 items-center justify-center rounded-full', here ? 'bg-ok-soft' : 'bg-caution-soft')}>
        {here ? <User className="h-[22px] w-[22px] text-ok" aria-hidden="true" /> : <UserX className="h-[22px] w-[22px] text-caution" aria-hidden="true" />}
      </span>
      <div className="mt-auto pt-4">
        <p className="text-[0.9375rem] font-semibold text-ink-2">재실 감지</p>
        <p className={cn('text-xl font-bold', here ? 'text-ink' : 'text-caution')}>{here ? '사람 있음' : `비어 있음 ${formatDuration(p.absentSec)}`}</p>
        <p className="mt-1 truncate text-[0.8125rem] text-ink-3">
          {here ? `감지 정확도 ${Math.round(p.confidence * 100)}% · ${formatAgo(p.observedAt)}` : `${ZONE_LABEL[p.zone]} · ${LOCATION_LABEL[location]}에 계세요`}
        </p>
      </div>
    </Card>
  )
}

/* ── 어르신 모드 ───────────────────────────────────────────────────────── */
function KitchenElderly() {
  const { induction, presence, kitchenPhase } = useHome()
  const line = describeKitchen(kitchenPhase, induction, presence.kitchen)
  const b = induction?.burner
  const hot = b?.deviceState === 'overheated'
  const here = presence.kitchen?.present
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="주방" />
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-5 px-8 pt-5 pb-7">
        <Card className={cn('flex flex-col justify-between p-8', line.risk !== 'normal' && RISK_TONE[line.risk].soft)}>
          <p className="text-2xl font-semibold text-ink-2">인덕션</p>
          <div>
            <p className={cn('text-5xl font-bold', hot ? 'text-danger' : 'text-ink')}>
              {b?.deviceState === 'on' ? `켜져 있어요` : b ? BURNER_LABEL[b.deviceState] : '-'}
            </p>
            {b && <p className="tabular mt-3 text-3xl font-semibold text-ink-2">{Math.round(b.temperature)}°C{b.deviceState === 'on' && ` · 화력 ${b.level}단`}</p>}
          </div>
          <StatusText risk={line.risk} className="text-2xl">{line.short}</StatusText>
        </Card>
        <Card className={cn('flex flex-col justify-between p-8', !here && 'bg-caution-soft')}>
          <p className="text-2xl font-semibold text-ink-2">주방에</p>
          <p className="text-5xl font-bold text-ink">{here ? '사람이 있어요' : '아무도 없어요'}</p>
          <p className="text-2xl text-ink-2">{here ? '✓ 잘 감지되고 있어요' : `${formatDuration(presence.kitchen?.absentSec ?? 0)} 비어 있어요`}</p>
        </Card>
      </div>
    </div>
  )
}
