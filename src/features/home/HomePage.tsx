import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Bath, ChevronRight, MapPin, Phone, PersonStanding, Radar, ShieldAlert, ShieldCheck, UtensilsCrossed, Wifi, WifiOff } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, SectionTitle } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { Tile } from '@/components/ui/Tile'
import { ListGroup } from '@/components/ui/List'
import { FitList } from '@/components/ui/FitList'
import { DeviceTile } from '@/features/devices/DeviceTile'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { EventRow } from '@/features/history/EventRow'
import { EventDetailSheet } from '@/features/history/EventDetailSheet'
import { HomeMap } from './HomeMap'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { describeBathroom, describeKitchen } from '@/lib/rooms'
import { LOCATION_LABEL, RISK_LABEL, isRecord } from '@/lib/labels'
import { formatCountdown, formatDuration } from '@/lib/format'
import type { Presence, Risk } from '@/types'
import { cn } from '@/lib/cn'

export function HomePage() {
  const { elderly } = usePreferences()
  return elderly ? <HomeElderly /> : <HomeNormal />
}

const riskTone = (r: Risk) => (r === 'danger' ? 'danger' : r === 'warning' || r === 'caution' ? 'warn' : r === 'uncertain' ? 'muted' : undefined)

/** 맨 위 요약 칩 줄 — 전체 상태 · 위치 · 기기 연결 · 보호자 */
function SummaryChips({ big = false }: { big?: boolean }) {
  const navigate = useNavigate()
  const { overallRisk, kitchenRisk, location, devices, onlineCount, contacts, refresh } = useHome()
  const [checking, setChecking] = useState(false)
  const safe = overallRisk === 'normal'
  const allOnline = onlineCount === devices.length
  const check = async () => {
    setChecking(true)
    try { await refresh() } finally { setChecking(false) }
  }
  const chipTone = overallRisk === 'danger' ? 'danger' : overallRisk === 'warning' ? 'warn' : overallRisk === 'caution' ? 'caution' : 'muted'
  return (
    <div className="-mx-5 flex shrink-0 gap-2 overflow-x-auto px-5 pb-1 md:-mx-8 md:px-8 [scrollbar-width:none]">
      {safe
        ? <Chip big={big} icon={ShieldCheck} tone="ok" label="모두 안전" />
        : <Chip big={big} icon={ShieldAlert} tone={chipTone} alert label={RISK_LABEL[overallRisk]}
            value={kitchenRisk !== 'normal' ? '주방' : '욕실'} onClick={() => navigate(kitchenRisk !== 'normal' ? '/kitchen' : '/bathroom')} />}
      <Chip big={big} icon={MapPin} tone="brand" label="위치" value={LOCATION_LABEL[location]} />
      <Chip big={big} icon={allOnline ? Wifi : WifiOff} tone={allOnline ? 'muted' : 'warn'} alert={!allOnline} label="기기"
        value={checking ? '확인 중…' : `${onlineCount}/${devices.length} 연결`} onClick={checking ? undefined : check} />
      <Chip big={big} icon={Phone} tone={contacts.guardian ? 'muted' : 'warn'} alert={!contacts.guardian} label="보호자"
        value={contacts.guardian ? contacts.guardian.name : '등록 필요'} onClick={() => navigate('/settings?section=contacts')} />
    </div>
  )
}

function presenceText(p: Presence | undefined) {
  if (!p) return '확인 중'
  return p.present ? '사람 있음' : `비어 있음${p.absentSec > 0 ? ` · ${formatDuration(p.absentSec)}` : ''}`
}

/* ── 일반 모드 ──────────────────────────────────────────────────────────────
   왼쪽: 방별 기기 타일 (iPad 홈 앱) / 오른쪽: 평면도 위치 · 최근 기록.
   월패드에서는 한 화면 고정, 그보다 작은 화면에서는 위에서부터 쌓는다.
   ───────────────────────────────────────────────────────────────────────── */
function HomeNormal() {
  const navigate = useNavigate()
  const { devices, events, presence, fall, setFallAlert } = useHome()
  const now = useNow()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [eventId, setEventId] = useState<string | null>(null)
  const records = events.filter(isRecord).slice(0, 6)
  const kitchen = devices.filter((d) => d.room === 'kitchen')
  const bath = devices.filter((d) => d.room === 'bathroom')
  const pending = fall?.status === 'pending'
  const bp = presence.bathroom

  const grid = 'grid grid-cols-2 gap-3 auto-rows-[136px] md:grid-cols-4 wall:min-h-0 wall:flex-1 wall:grid-rows-[minmax(0,1fr)] wall:auto-rows-auto'

  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="우리 집" />
      <div className="px-5 pt-4 md:px-8 wall:short:pt-3"><SummaryChips /></div>

      <div className={cn(
        'grid grid-cols-1 gap-6 px-5 pt-5 pb-6 md:px-8',
        'wall:min-h-0 wall:flex-1 wall:grid-cols-12 wall:gap-6 wall:pb-7 wall:short:gap-4 wall:short:pt-3.5 wall:short:pb-5',
      )}>
        <div className="flex flex-col gap-6 wall:col-span-8 wall:min-h-0 wall:short:gap-4">
          <section className="flex flex-col wall:min-h-0 wall:flex-1">
            <SectionTitle action={<RoomLink onClick={() => navigate('/kitchen')} />}>주방</SectionTitle>
            <div className={grid}>
              {kitchen.map((d) => <DeviceTile key={d.id} device={d} wide={d.kind === 'induction'} onOpen={() => setDeviceId(d.id)} />)}
            </div>
          </section>
          <section className="flex flex-col wall:min-h-0 wall:flex-1">
            <SectionTitle action={<RoomLink onClick={() => navigate('/bathroom')} />}>욕실</SectionTitle>
            <div className={grid}>
              {bath.map((d) => <DeviceTile key={d.id} device={d} onOpen={() => setDeviceId(d.id)} />)}
              <Tile icon={Radar} glyph="text-brand-ink" name="재실 감지" state={presenceText(bp)} on={!!bp?.present} onPress={() => navigate('/bathroom')} />
              <Tile icon={PersonStanding} glyph="text-ok" name="낙상 감지" wide on={!pending}
                tone={pending ? 'danger' : undefined}
                state={pending ? '보호자 응답 대기 중' : '감시 중 · 이상 없음'}
                value={pending ? formatCountdown((new Date(fall!.autoReportAt).getTime() - now) / 1000) : undefined}
                onPress={() => (pending ? setFallAlert(true) : navigate('/bathroom'))} />
            </div>
          </section>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 wall:col-span-4 wall:flex wall:min-h-0 wall:flex-col wall:short:gap-4">
          <section className="flex flex-col">
            <SectionTitle>위치</SectionTitle>
            <Card className="p-3">
              <HomeMap className="h-40 wall:h-[150px] wall:short:h-[118px]" />
              <dl className="mt-2.5 grid grid-cols-2 gap-x-3 px-1 text-[0.8125rem]">
                <div><dt className="text-ink-3">주방 재실</dt><dd className="truncate font-medium text-ink">{presenceText(presence.kitchen)}</dd></div>
                <div><dt className="text-ink-3">욕실 재실</dt><dd className="truncate font-medium text-ink">{presenceText(bp)}</dd></div>
              </dl>
            </Card>
          </section>

          <section className="flex flex-col wall:min-h-0 wall:flex-1">
            <SectionTitle action={
              <button type="button" onClick={() => navigate('/history')} className="press text-[0.9375rem] text-brand-ink">전체 보기</button>
            }>최근 기록</SectionTitle>
            <ListGroup className="flex flex-col wall:min-h-0 wall:flex-1" bodyClassName="wall:min-h-0 wall:flex-1">
              <FitList className="wall:h-full" items={records} getKey={(e) => e.eventId}
                render={(e) => <EventRow event={e} compact onClick={() => setEventId(e.eventId)} />}
                empty={<p className="px-4 py-4 text-[0.9375rem] text-ink-3">기록 없음</p>}
                none={<button type="button" onClick={() => navigate('/history')} className="w-full px-4 py-3 text-left text-[0.9375rem] text-brand-ink">기록 {records.length}건 보기</button>} />
            </ListGroup>
          </section>
        </div>
      </div>

      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <EventDetailSheet eventId={eventId} onClose={() => setEventId(null)} />
    </div>
  )
}

function RoomLink({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="press flex items-center text-[0.9375rem] text-brand-ink">
      자세히<ChevronRight className="h-4 w-4" strokeWidth={2.4} aria-hidden="true" />
    </button>
  )
}

/* ── 어르신 모드: 큰 타일 네 개 ─────────────────────────────────────────── */
function HomeElderly() {
  const navigate = useNavigate()
  const { kitchenPhase, induction, presence, fall, location, contacts } = useHome()
  const k = describeKitchen(kitchenPhase, induction, presence.kitchen)
  const b = describeBathroom(fall, presence.bathroom)
  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="우리 집" />
      <div className="px-5 pt-4 md:px-8"><SummaryChips big /></div>
      <div className="grid grid-cols-1 gap-4 px-5 pt-5 pb-7 auto-rows-[180px] md:grid-cols-2 md:px-8 wall:min-h-0 wall:flex-1 wall:auto-rows-auto wall:grid-rows-2">
        <Tile big icon={UtensilsCrossed} glyph="text-glyph-heat" name="주방" state={k.short} on={k.risk === 'normal'} tone={riskTone(k.risk)} onPress={() => navigate('/kitchen')} />
        <Tile big icon={Bath} glyph="text-glyph-water" name="욕실" state={b.short} on={b.risk === 'normal'} tone={riskTone(b.risk)} onPress={() => navigate('/bathroom')} />
        <Tile big icon={MapPin} glyph="text-brand-ink" name="지금 위치" state={LOCATION_LABEL[location]} on />
        <Tile big icon={Phone} glyph="text-ok" name="보호자" state={contacts.guardian ? contacts.guardian.name : '등록해 주세요'}
          on={!!contacts.guardian} tone={contacts.guardian ? undefined : 'warn'} onPress={() => navigate('/settings?section=contacts')} />
      </div>
    </div>
  )
}
