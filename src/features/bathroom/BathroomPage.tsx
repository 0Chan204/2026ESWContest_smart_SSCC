import { useState } from 'react'
import { PersonStanding, ShieldCheck, TriangleAlert, User } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, CardTitle } from '@/components/ui/Card'
import { StatusText } from '@/components/ui/StatusDot'
import { Button } from '@/components/ui/Button'
import { DeviceTile } from '@/features/devices/DeviceTile'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { EventRow } from '@/features/history/EventRow'
import { EventDetailSheet } from '@/features/history/EventDetailSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { describeBathroom } from '@/lib/rooms'
import { FALL_STATUS_LABEL } from '@/lib/labels'
import { formatAgo, formatCountdown, formatWhen } from '@/lib/format'
import { cn } from '@/lib/cn'

export function BathroomPage() {
  const { fall, presence, devices, events, setFallAlert, contacts } = useHome()
  const { elderly } = usePreferences()
  const now = useNow()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [eventId, setEventId] = useState<string | null>(null)
  const p = presence.bathroom
  const line = describeBathroom(fall, p)
  const pending = fall?.status === 'pending'
  const lights = devices.filter((d) => d.room === 'bathroom')
  const recent = events.filter((e) => e.room === 'bathroom').slice(0, elderly ? 3 : 5)
  const lastFall = events.find((e) => e.type === 'fall_detected')

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="욕실" subtitle={<StatusText risk={line.risk}>{line.text}</StatusText>} />
      <div className="grid min-h-0 flex-1 grid-cols-12 gap-5 px-8 pt-5 pb-7">
        <div className="col-span-8 grid min-h-0 gap-5" style={{ gridTemplateRows: 'minmax(0,1fr) auto' }}>
          <Card className={cn('flex flex-col justify-between p-8', pending && 'bg-danger-soft ring-2 ring-danger')}>
            <span className={cn('flex h-16 w-16 items-center justify-center rounded-2xl', pending ? 'bg-danger' : p?.present ? 'bg-ok-soft' : 'bg-sunken')}>
              {pending ? <TriangleAlert className="soft-pulse h-8 w-8 text-white" aria-hidden="true" />
                : p?.present ? <User className="h-8 w-8 text-ok" aria-hidden="true" /> : <PersonStanding className="h-8 w-8 text-ink-3" aria-hidden="true" />}
            </span>
            <div className="flex items-end justify-between gap-8">
            <div className="min-w-0">
              <p className={cn('font-bold', elderly ? 'text-5xl' : 'text-4xl', pending ? 'text-danger' : 'text-ink')}>
                {pending ? '낙상이 감지됐어요' : p?.present ? '욕실을 사용 중이에요' : '욕실이 비어 있어요'}
              </p>
              <p className={cn('mt-2 text-ink-2', elderly ? 'text-2xl' : 'text-lg')}>
                {pending
                  ? `보호자 응답이 없으면 ${formatCountdown((new Date(fall!.autoReportAt).getTime() - now) / 1000)} 후 자동으로 신고돼요`
                  : fall && fall.status !== 'pending'
                    ? `최근 낙상 — ${FALL_STATUS_LABEL[fall.status]} (${formatWhen(fall.detectedAt)})`
                    : p?.present ? `움직임 정상 · ${formatAgo(p.observedAt)} 확인` : '들어오시면 조명이 자동으로 켜져요'}
              </p>
            </div>
            {!elderly && !pending && (
              <dl className="w-72 shrink-0 divide-y divide-line rounded-2xl bg-sunken px-4 text-[0.875rem]">
                <Info k="감지 상태" v={p ? `${p.present ? '사람 있음' : '비어 있음'} · 정확도 ${Math.round(p.confidence * 100)}%` : '확인 중'} />
                <Info k="최근 낙상" v={lastFall ? formatWhen(lastFall.occurredAt) : '없음'} />
                <Info k="보호자 알림" v={contacts.guardian ? `${contacts.guardian.name} · 등록됨` : '미등록'} warn={!contacts.guardian} />
              </dl>
            )}
            </div>
            {pending && <Button variant="danger" size={elderly ? 'xl' : 'lg'} className="self-start" onClick={() => setFallAlert(true)}>자세히 보기</Button>}
          </Card>

          <div className="grid grid-cols-3 gap-4" style={{ gridAutoRows: '164px' }}>
            {lights.map((d) => <DeviceTile key={d.id} device={d} showRoom={false} onOpen={() => setDeviceId(d.id)} />)}
            {!elderly && (
              <Card className="col-span-2 flex flex-col justify-center p-6">
                <p className="flex items-center gap-2 text-[0.9375rem] font-semibold text-ink">
                  <ShieldCheck className="h-5 w-5 text-ok" aria-hidden="true" />낙상은 이렇게 판단해요
                </p>
                <ol className="mt-3 grid grid-cols-3 gap-3 text-[0.8125rem] leading-snug">
                  <Stage t="5초" d="누운 뒤 움직임 없음 → 낙상 확인" />
                  <Stage t="10초" d="화면·음성 경고, 보호자 문자" />
                  <Stage t="30초" d="응급 단계 · 응답 없으면 자동 신고" />
                </ol>
              </Card>
            )}
          </div>
        </div>

        <Card className="col-span-4 flex min-h-0 flex-col p-6">
          <CardTitle title="욕실 기록" />
          <div className="-mx-3 min-h-0 flex-1 overflow-hidden">
            {recent.map((e) => <EventRow key={e.eventId} event={e} compact big={elderly} onClick={() => setEventId(e.eventId)} />)}
          </div>
          {!elderly && (
            <p className="mt-3 rounded-2xl bg-sunken px-4 py-3 text-[0.8125rem] leading-relaxed text-ink-2">
              오래 가만히 있는 것만으로는 낙상으로 판단하지 않아요. 센서가 끊겨도 위험 상태를 임의로 해제하지 않아요.
            </p>
          )}
        </Card>
      </div>
      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <EventDetailSheet eventId={eventId} onClose={() => setEventId(null)} />
    </div>
  )
}

function Info({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="flex justify-between gap-3 py-2.5">
      <dt className="text-ink-3">{k}</dt>
      <dd className={cn('text-right font-medium', warn ? 'text-warn' : 'text-ink')}>{v}</dd>
    </div>
  )
}

function Stage({ t, d }: { t: string; d: string }) {
  return (
    <li className="rounded-xl bg-sunken px-3 py-2.5">
      <p className="tabular text-[0.9375rem] font-bold text-ink">{t}</p>
      <p className="mt-0.5 text-ink-2">{d}</p>
    </li>
  )
}
