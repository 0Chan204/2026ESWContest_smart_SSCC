import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Bath, ChevronRight, MapPin, ShieldAlert, ShieldCheck, UserRound, UtensilsCrossed } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, CardTitle } from '@/components/ui/Card'
import { StatusText } from '@/components/ui/StatusDot'
import { DeviceTile } from '@/features/devices/DeviceTile'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { EventRow } from '@/features/history/EventRow'
import { EventDetailSheet } from '@/features/history/EventDetailSheet'
import { HomeMap } from './HomeMap'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { HERO_TITLE, describeBathroom, describeKitchen } from '@/lib/rooms'
import { LOCATION_LABEL, RISK_TONE, isRecord } from '@/lib/labels'
import { maskPhone } from '@/lib/phone'
import { cn } from '@/lib/cn'

export function HomePage() {
  const { elderly } = usePreferences()
  return elderly ? <HomeElderly /> : <HomeNormal />
}

function useRoomLines() {
  const { kitchenPhase, induction, presence, fall } = useHome()
  return { kitchen: describeKitchen(kitchenPhase, induction, presence.kitchen), bathroom: describeBathroom(fall, presence.bathroom) }
}

/* ── 일반 모드 ──────────────────────────────────────────────────────────── */
function HomeNormal() {
  const navigate = useNavigate()
  const { overallRisk, devices, events, contacts, location } = useHome()
  // 상단 상태 배너가 떠 있으면(위험·연결 끊김) 세로 공간이 줄어드므로 기록을 2건만 보여준다
  const bannerShown = overallRisk !== 'normal' || devices.some((d) => !d.online)
  const lines = useRoomLines()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [eventId, setEventId] = useState<string | null>(null)
  const records = events.filter(isRecord).slice(0, bannerShown ? 2 : 3)
  const safe = overallRisk === 'normal'
  const HeroIcon = safe ? ShieldCheck : ShieldAlert

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="우리 집" subtitle={safe ? '모든 공간과 기기가 정상이에요' : '확인이 필요한 공간이 있어요'} />

      <div className="grid min-h-0 flex-1 gap-4 px-8 pt-5 pb-7" style={{ gridTemplateRows: 'minmax(172px,1fr) auto auto' }}>
        {/* 1행: 전체 상태 + 지금 위치 */}
        <div className="grid min-h-0 grid-cols-12 gap-5">
          <Card className={cn('col-span-7 flex min-h-0 flex-col justify-between px-7 py-6', !safe && RISK_TONE[overallRisk].soft)}>
            <div className="flex items-center gap-4">
              <span className={cn('flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl', safe ? 'bg-ok-soft' : 'bg-surface')}>
                <HeroIcon className={cn('h-6 w-6', RISK_TONE[overallRisk].text)} aria-hidden="true" />
              </span>
              <h2 className="text-[1.75rem] leading-tight font-bold text-ink">{HERO_TITLE[overallRisk]}</h2>
            </div>
            <ul className="mt-3">
              <RoomLine Icon={UtensilsCrossed} name="주방" text={lines.kitchen.text} risk={lines.kitchen.risk} onClick={() => navigate('/kitchen')} />
              <RoomLine Icon={Bath} name="욕실" text={lines.bathroom.text} risk={lines.bathroom.risk} onClick={() => navigate('/bathroom')} />
            </ul>
          </Card>

          <Card className="col-span-5 flex min-h-0 flex-col px-6 py-5">
            <CardTitle title="지금 위치" action={
              <span className="flex items-center gap-1 text-[0.9375rem] font-semibold text-brand">
                <MapPin className="h-4 w-4" aria-hidden="true" />{LOCATION_LABEL[location]}
              </span>
            } />
            <div className="flex min-h-0 flex-1 flex-col justify-center"><HomeMap height={112} /></div>
          </Card>
        </div>

        {/* 2행: 기기 */}
        <section>
          <h2 className="mb-2.5 text-[0.9375rem] font-semibold text-ink">기기 <span className="font-normal text-ink-3">{devices.length}</span></h2>
          <div className="grid grid-cols-4 gap-4" style={{ gridAutoRows: '158px' }}>
            {devices.map((d) => <DeviceTile key={d.id} device={d} onOpen={() => setDeviceId(d.id)} />)}
          </div>
        </section>

        {/* 3행: 최근 안전 기록 + 보호자 알림 */}
        <div className="grid grid-cols-12 gap-5">
          <Card className="col-span-8 px-3 py-2.5">
            <div className="flex items-center justify-between px-3 pt-1 pb-1">
              <h2 className="text-[0.9375rem] font-semibold text-ink">최근 안전 기록</h2>
              <button type="button" onClick={() => navigate('/history')} className="flex items-center text-sm font-semibold text-brand">
                전체 보기<ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            {records.map((e) => <EventRow key={e.eventId} event={e} compact onClick={() => setEventId(e.eventId)} />)}
          </Card>
          <GuardianCard className="col-span-4" guardian={contacts.guardian} onRegister={() => navigate('/settings?section=contacts')} />
        </div>
      </div>

      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <EventDetailSheet eventId={eventId} onClose={() => setEventId(null)} />
    </div>
  )
}

function RoomLine({ Icon, name, text, risk, onClick }: {
  Icon: typeof Bath; name: string; text: string; risk: Parameters<typeof StatusText>[0]['risk']; onClick: () => void
}) {
  return (
    <li>
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3 rounded-xl py-1.5 text-left hover:opacity-80">
        <Icon className="h-5 w-5 shrink-0 text-ink-2" aria-hidden="true" />
        <span className="w-12 shrink-0 text-[1.0625rem] font-semibold text-ink">{name}</span>
        <StatusText risk={risk} className="min-w-0 flex-1 truncate text-[1rem]">{text}</StatusText>
        <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" aria-hidden="true" />
      </button>
    </li>
  )
}

function GuardianCard({ guardian, onRegister, className }: {
  guardian: { name: string; phone: string } | null; onRegister: () => void; className?: string
}) {
  if (!guardian) {
    return (
      <Card className={cn('flex flex-col justify-between bg-warn-soft p-6', className)}>
        <div>
          <p className="text-[0.9375rem] font-semibold text-[#9a4a00]">보호자 연락처가 없어요</p>
          <p className="mt-1 text-[0.875rem] leading-relaxed text-[#9a4a00]/85">등록하면 낙상이 감지될 때 보호자에게 바로 문자로 알려드려요.</p>
        </div>
        <button type="button" onClick={onRegister}
          className="mt-4 min-h-11 rounded-xl bg-surface text-[0.9375rem] font-semibold text-ink hover:bg-sunken">
          보호자 등록하기
        </button>
      </Card>
    )
  }
  return (
    <Card className={cn('flex flex-col justify-between p-6', className)}>
      <p className="text-[0.9375rem] font-semibold text-ink">위급할 때 알림</p>
      <div className="mt-3 flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-sunken"><UserRound className="h-5 w-5 text-ink-2" aria-hidden="true" /></span>
        <div>
          <p className="text-[1rem] font-semibold text-ink">보호자 {guardian.name}</p>
          <p className="tabular text-[0.875rem] text-ink-2">{maskPhone(guardian.phone)}</p>
        </div>
      </div>
      <p className="mt-3 text-[0.8125rem] text-ink-3">낙상이 감지되면 이 번호로 확인 문자를 보내요.</p>
    </Card>
  )
}

/* ── 어르신 모드: 정보는 줄이고 크게 ───────────────────────────────────── */
function HomeElderly() {
  const navigate = useNavigate()
  const { overallRisk, location, contacts } = useHome()
  const lines = useRoomLines()
  const safe = overallRisk === 'normal'

  const cards = [
    { key: 'kitchen', Icon: UtensilsCrossed, name: '주방', short: lines.kitchen.short, risk: lines.kitchen.risk, to: '/kitchen' },
    { key: 'bathroom', Icon: Bath, name: '욕실', short: lines.bathroom.short, risk: lines.bathroom.risk, to: '/bathroom' },
    { key: 'where', Icon: MapPin, name: '지금 위치', short: LOCATION_LABEL[location], risk: 'normal' as const, to: '/home' },
  ]

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="우리 집" />
      <div className="flex min-h-0 flex-1 flex-col gap-5 px-8 pt-5 pb-7">
        <Card className={cn('flex shrink-0 items-center gap-5 px-8 py-7', !safe && RISK_TONE[overallRisk].soft)}>
          {safe ? <ShieldCheck className="h-12 w-12 text-ok" aria-hidden="true" /> : <ShieldAlert className={cn('h-12 w-12', RISK_TONE[overallRisk].text)} aria-hidden="true" />}
          <p className="text-4xl font-bold text-ink">{safe ? '✓ ' : '! '}{HERO_TITLE[overallRisk]}</p>
        </Card>
        <div className="grid min-h-0 flex-1 grid-cols-3 gap-5">
          {cards.map(({ key, Icon, name, short, risk, to }) => (
            <button key={key} type="button" onClick={() => navigate(to)}
              className={cn('flex flex-col items-center justify-center gap-4 rounded-3xl p-6 text-center', risk === 'normal' ? 'bg-surface' : RISK_TONE[risk].soft)}>
              <Icon className="h-14 w-14 text-ink-2" strokeWidth={1.6} aria-hidden="true" />
              <span className="text-3xl font-bold text-ink">{name}</span>
              <StatusText risk={risk} className="text-2xl">{short}</StatusText>
            </button>
          ))}
        </div>
        {!contacts.guardian && (
          <button type="button" onClick={() => navigate('/settings?section=contacts')}
            className="flex min-h-16 shrink-0 items-center justify-between rounded-3xl bg-warn-soft px-7 text-xl font-semibold text-[#9a4a00]">
            보호자 연락처를 등록해 주세요<ChevronRight className="h-6 w-6" aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  )
}
