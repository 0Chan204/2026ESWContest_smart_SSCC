import { useState } from 'react'
import { PersonStanding, Radar, TriangleAlert, User } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, SectionTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { FitList } from '@/components/ui/FitList'
import { Tile } from '@/components/ui/Tile'
import { ListGroup } from '@/components/ui/List'
import { DeviceTile } from '@/features/devices/DeviceTile'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { EventRow } from '@/features/history/EventRow'
import { EventDetailSheet } from '@/features/history/EventDetailSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { FALL_STATUS_LABEL } from '@/lib/labels'
import { formatAgo, formatCountdown, formatDuration, formatWhen } from '@/lib/format'
import { cn } from '@/lib/cn'

export function BathroomPage() {
  const { fall, presence, devices, events, setFallAlert, contacts } = useHome()
  const { elderly } = usePreferences()
  const now = useNow()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [eventId, setEventId] = useState<string | null>(null)
  const p = presence.bathroom
  const pending = fall?.status === 'pending'
  const lights = devices.filter((d) => d.room === 'bathroom')
  const recent = events.filter((e) => e.room === 'bathroom').slice(0, 8)
  const lastFall = events.find((e) => e.type === 'fall_detected')
  const Icon = pending ? TriangleAlert : p?.present ? User : PersonStanding

  const title = pending ? '낙상 감지' : p?.present ? '사용 중' : '비어 있음'
  const detail = pending
    ? `보호자 응답이 없으면 ${formatCountdown((new Date(fall!.autoReportAt).getTime() - now) / 1000)} 후 자동 신고`
    : fall ? `최근 낙상 · ${FALL_STATUS_LABEL[fall.status]}`
    : p?.present ? `움직임 정상 · ${formatAgo(p.observedAt)} 확인` : '들어오면 조명이 자동으로 켜져요'

  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="욕실" />
      <div className="grid grid-cols-1 gap-6 px-5 pt-5 pb-6 md:px-8 wall:min-h-0 wall:flex-1 wall:grid-cols-12 wall:pb-7 wall:short:gap-4 wall:short:pt-4 wall:short:pb-5">
        <div className="flex flex-col gap-4 wall:col-span-8 wall:min-h-0">
          <Card className={cn('flex min-h-64 flex-col gap-6 p-6 md:flex-row md:p-7 wall:min-h-0 wall:flex-1', pending && 'bg-danger-soft')}>
            <div className="flex min-w-0 flex-1 flex-col justify-between gap-6">
              <Icon className={cn(elderly ? 'h-14 w-14' : 'h-11 w-11', pending ? 'soft-pulse text-danger' : p?.present ? 'text-brand-ink' : 'text-ink-3')}
                strokeWidth={1.6} aria-hidden="true" />
              <div>
                <p className={cn('font-bold tracking-[-0.02em]', elderly ? 'text-[3.25rem]' : 'text-[2.75rem]', 'leading-tight', pending ? 'text-danger' : 'text-ink')}>{title}</p>
                <p className={cn('mt-1', elderly ? 'text-2xl' : 'text-[1.0625rem]', pending ? 'font-semibold text-danger' : 'text-ink-2')}>{detail}</p>
                {pending && <Button variant="danger" size={elderly ? 'xl' : 'lg'} className="mt-5" onClick={() => setFallAlert(true)}>자세히 보기</Button>}
              </div>
            </div>
            {!elderly && !pending && (
              <dl className="inset-list w-full shrink-0 self-end text-[0.9375rem] md:w-72">
                <Info k="감지" v={p ? `${p.present ? '사람 있음' : '비어 있음'} · ${Math.round(p.confidence * 100)}%` : '확인 중'} />
                <Info k="최근 낙상" v={lastFall ? formatWhen(lastFall.occurredAt) : '없음'} />
                <Info k="보호자 알림" v={contacts.guardian ? contacts.guardian.name : '미등록'} warn={!contacts.guardian} />
              </dl>
            )}
          </Card>

          <div className={cn('grid shrink-0 gap-3', elderly ? 'grid-cols-2 auto-rows-[160px]' : 'grid-cols-2 auto-rows-[156px] md:grid-cols-4 wall:short:auto-rows-[132px]')}>
            {lights.map((d) => <DeviceTile key={d.id} device={d} big={elderly} onOpen={() => setDeviceId(d.id)} />)}
            <Tile big={elderly} icon={Radar} glyph="text-brand-ink" name="재실 감지" on={!!p?.present}
              state={!p ? '확인 중' : p.present ? '사람 있음' : `비어 있음${p.absentSec > 0 ? ` · ${formatDuration(p.absentSec)}` : ''}`} />
            {!elderly && (
              <ListGroup className="col-span-2" bodyClassName="h-full">
                <Stage t="5초" d="누운 뒤 움직임 없음 → 낙상 확인" />
                <Stage t="10초" d="화면·음성 경고, 보호자 문자" />
                <Stage t="30초" d="응답 없으면 자동 신고" />
              </ListGroup>
            )}
          </div>
        </div>

        <section className="flex flex-col wall:col-span-4 wall:min-h-0">
          <SectionTitle>욕실 기록</SectionTitle>
          <ListGroup className="flex flex-col wall:min-h-0 wall:flex-1" bodyClassName="wall:min-h-0 wall:flex-1">
            <FitList className="wall:h-full" items={recent} getKey={(e) => e.eventId}
              render={(e) => <EventRow event={e} compact big={elderly} onClick={() => setEventId(e.eventId)} />}
              empty={<p className="px-4 py-4 text-[0.9375rem] text-ink-3">기록 없음</p>} />
          </ListGroup>
        </section>
      </div>
      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <EventDetailSheet eventId={eventId} onClose={() => setEventId(null)} />
    </div>
  )
}

function Info({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div>
      <div className="row-sep flex justify-between gap-3 py-2.5">
        <dt className="text-ink-2">{k}</dt>
        <dd className={cn('text-right font-medium', warn ? 'text-warn' : 'text-ink')}>{v}</dd>
      </div>
    </div>
  )
}

/** 낙상 대응 단계 한 줄 */
function Stage({ t, d }: { t: string; d: string }) {
  return (
    <div className="flex h-1/3 items-center gap-3 pl-4">
      <span className="tabular w-10 shrink-0 text-[0.9375rem] font-semibold text-ink">{t}</span>
      <span className="row-sep flex h-full min-w-0 flex-1 items-center truncate pr-4 text-[0.875rem] text-ink-2">{d}</span>
    </div>
  )
}
