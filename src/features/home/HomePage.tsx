import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Bath, ChevronRight, MapPin, Maximize2, Phone, RefreshCw, ShieldAlert, ShieldCheck, UtensilsCrossed, type LucideIcon } from 'lucide-react'
import { PageHeader } from '@/app/PageHeader'
import { Card, SectionTitle } from '@/components/ui/Card'
import { Tile } from '@/components/ui/Tile'
import { DeviceCard } from '@/features/devices/DeviceCard'
import { DeviceSheet } from '@/features/devices/DeviceSheet'
import { HomeMap } from './HomeMap'
import { LocationSheet } from './LocationSheet'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { HERO_TITLE, describeBathroom, describeKitchen } from '@/lib/rooms'
import { LOCATION_LABEL } from '@/lib/labels'
import { formatDuration } from '@/lib/format'
import type { Presence, Risk } from '@/types'
import { cn } from '@/lib/cn'

export function HomePage() {
  const { elderly } = usePreferences()
  return elderly ? <HomeElderly /> : <HomeNormal />
}

const riskTone = (r: Risk) => (r === 'danger' ? 'danger' : r === 'warning' || r === 'caution' ? 'warn' : r === 'uncertain' ? 'muted' : undefined)
const RISK_TEXT: Record<Risk, string> = { normal: 'text-ok', caution: 'text-caution', warning: 'text-warn', danger: 'text-danger', uncertain: 'text-ink-2' }
const RISK_BG: Record<Risk, string> = { normal: '', caution: 'bg-caution-soft', warning: 'bg-warn-soft', danger: 'bg-danger-soft', uncertain: '' }

function presenceText(p: Presence | undefined) {
  if (!p) return '확인 중'
  return p.present ? '사람 있음' : `비어 있음${p.absentSec > 0 ? ` · ${formatDuration(p.absentSec)}` : ''}`
}

/* ── 일반 모드 ──────────────────────────────────────────────────────────────
   v2 배치: 1행 = 집 상태 | 위치(누르면 크게 보기), 2행 = 기기 카드 한 줄.
   최근 기록은 기록 탭에서만 본다.
   ───────────────────────────────────────────────────────────────────────── */
function HomeNormal() {
  const navigate = useNavigate()
  const { overallRisk, devices, presence, location, kitchenPhase, induction, fall, contacts, refresh } = useHome()
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [mapOpen, setMapOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const k = describeKitchen(kitchenPhase, induction, presence.kitchen)
  const b = describeBathroom(fall, presence.bathroom)
  const HeroIcon = overallRisk === 'normal' ? ShieldCheck : ShieldAlert
  const check = async () => {
    setChecking(true)
    try { await refresh() } finally { setChecking(false) }
  }

  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="우리 집" />

      <div className={cn(
        'flex flex-col gap-6 px-5 pt-5 pb-6 md:px-8',
        'wall:grid wall:min-h-0 wall:flex-1 wall:grid-rows-[minmax(0,1fr)_auto] wall:pb-7 wall:short:gap-4 wall:short:pt-4 wall:short:pb-5',
      )}>
        {/* 1행: 집 상태 + 위치 */}
        <div className="grid grid-cols-1 gap-5 md:grid-cols-12 wall:min-h-0">
          <Card className={cn('flex flex-col justify-between gap-5 p-6 md:col-span-7 wall:min-h-0 wall:short:p-5', RISK_BG[overallRisk])}>
            <div className="flex items-center gap-3">
              <HeroIcon className={cn('h-8 w-8 shrink-0', RISK_TEXT[overallRisk])} strokeWidth={1.8} aria-hidden="true" />
              <h2 className="text-[1.75rem] leading-tight font-bold tracking-[-0.01em] text-ink">{HERO_TITLE[overallRisk]}</h2>
            </div>
            <ul className="inset-list">
              <StatusRow icon={UtensilsCrossed} name="주방" value={k.short} risk={k.risk} onClick={() => navigate('/kitchen')} />
              <StatusRow icon={Bath} name="욕실" value={b.short} risk={b.risk} onClick={() => navigate('/bathroom')} />
              <StatusRow icon={Phone} name="보호자" value={contacts.guardian ? contacts.guardian.name : '등록 필요'}
                risk={contacts.guardian ? 'normal' : 'warning'} neutral={!!contacts.guardian} onClick={() => navigate('/settings?section=contacts')} />
            </ul>
          </Card>

          <button type="button" onClick={() => setMapOpen(true)} aria-label={`지금 위치 ${LOCATION_LABEL[location]} · 크게 보기`}
            className="press flex flex-col rounded-2xl bg-surface p-5 text-left md:col-span-5 wall:min-h-0 wall:short:p-4">
            <span className="flex w-full items-center justify-between gap-3">
              <span className="text-[1.0625rem] font-semibold text-ink">지금 위치</span>
              <span className="flex items-center gap-2 text-[0.9375rem] font-semibold text-brand-ink">
                {LOCATION_LABEL[location]}<Maximize2 className="h-4 w-4 text-ink-3" aria-hidden="true" />
              </span>
            </span>
            <HomeMap className="mt-3 h-40 w-full md:h-auto md:min-h-36 md:flex-1 wall:min-h-0" />
            <span className="mt-3 grid w-full grid-cols-2 gap-x-3 text-[0.8125rem]">
              <span className="min-w-0"><span className="block text-ink-3">주방</span><span className="block truncate font-medium text-ink">{presenceText(presence.kitchen)}</span></span>
              <span className="min-w-0"><span className="block text-ink-3">욕실</span><span className="block truncate font-medium text-ink">{presenceText(presence.bathroom)}</span></span>
            </span>
          </button>
        </div>

        {/* 2행: 기기 카드 (v2 형태) */}
        <section>
          <SectionTitle action={
            <button type="button" onClick={check} disabled={checking} className="press flex items-center gap-1.5 text-[0.9375rem] text-brand-ink disabled:opacity-60">
              <RefreshCw className={cn('h-4 w-4', checking && 'spin-slow')} aria-hidden="true" />{checking ? '확인 중…' : '다시 확인'}
            </button>
          }>기기 <span className="font-normal text-ink-3">{devices.length}</span></SectionTitle>
          <div className="grid grid-cols-2 gap-4 auto-rows-[158px] md:grid-cols-4 wall:short:auto-rows-[144px]">
            {devices.map((d) => <DeviceCard key={d.id} device={d} onOpen={() => setDeviceId(d.id)} />)}
          </div>
        </section>
      </div>

      <DeviceSheet deviceId={deviceId} onClose={() => setDeviceId(null)} />
      <LocationSheet open={mapOpen} onClose={() => setMapOpen(false)} />
    </div>
  )
}

/** 집 상태 카드의 한 줄: 아이콘 · 이름 · 상태 · › */
function StatusRow({ icon: Icon, name, value, risk, neutral = false, onClick }: {
  icon: LucideIcon; name: string; value: string; risk: Risk; neutral?: boolean; onClick: () => void
}) {
  return (
    <li>
      <button type="button" onClick={onClick} className="press flex w-full items-center gap-3 text-left">
        <Icon className="h-5 w-5 shrink-0 text-ink-3" aria-hidden="true" />
        <span className="row-sep flex min-h-12 flex-1 items-center gap-3 wall:short:min-h-11">
          <span className="w-16 shrink-0 text-[1.0625rem] font-semibold text-ink">{name}</span>
          <span className={cn('min-w-0 flex-1 truncate text-[1rem] font-medium', neutral ? 'text-ink-2' : RISK_TEXT[risk])}>{value}</span>
          <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" strokeWidth={2.4} aria-hidden="true" />
        </span>
      </button>
    </li>
  )
}

/* ── 어르신 모드: 상태 한 줄 + 큰 타일 네 개 ──────────────────────────── */
function HomeElderly() {
  const navigate = useNavigate()
  const { kitchenPhase, induction, presence, fall, location, contacts, overallRisk } = useHome()
  const [mapOpen, setMapOpen] = useState(false)
  const k = describeKitchen(kitchenPhase, induction, presence.kitchen)
  const b = describeBathroom(fall, presence.bathroom)
  const HeroIcon = overallRisk === 'normal' ? ShieldCheck : ShieldAlert
  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="우리 집" />
      <p className="flex items-center gap-3 px-5 pt-4 text-[1.75rem] font-bold text-ink md:px-8">
        <HeroIcon className={cn('h-9 w-9 shrink-0', RISK_TEXT[overallRisk])} strokeWidth={1.8} aria-hidden="true" />{HERO_TITLE[overallRisk]}
      </p>
      <div className="grid grid-cols-1 gap-4 px-5 pt-4 pb-7 auto-rows-[180px] md:grid-cols-2 md:px-8 wall:min-h-0 wall:flex-1 wall:auto-rows-auto wall:grid-rows-2">
        <Tile big icon={UtensilsCrossed} glyph="text-glyph-heat" name="주방" state={k.short} on={k.risk === 'normal'} tone={riskTone(k.risk)} onPress={() => navigate('/kitchen')} />
        <Tile big icon={Bath} glyph="text-glyph-water" name="욕실" state={b.short} on={b.risk === 'normal'} tone={riskTone(b.risk)} onPress={() => navigate('/bathroom')} />
        <Tile big icon={MapPin} glyph="text-brand-ink" name="지금 위치" state={LOCATION_LABEL[location]} on onPress={() => setMapOpen(true)} />
        <Tile big icon={Phone} glyph="text-ok" name="보호자" state={contacts.guardian ? contacts.guardian.name : '등록해 주세요'}
          on={!!contacts.guardian} tone={contacts.guardian ? undefined : 'warn'} onPress={() => navigate('/settings?section=contacts')} />
      </div>
      <LocationSheet open={mapOpen} onClose={() => setMapOpen(false)} />
    </div>
  )
}
