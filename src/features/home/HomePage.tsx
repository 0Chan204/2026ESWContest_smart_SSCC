import { useState } from 'react'
import { AlertTriangle, Bath, CheckCircle2, Shield, UtensilsCrossed, Wifi } from 'lucide-react'
import { ApplianceCard } from '@/components/ApplianceCard'
import { ApplianceDetailModal } from '@/features/appliance/ApplianceDetailModal'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import { cn } from '@/lib/cn'

export function HomePage() {
  const { elderly } = usePreferences()
  const [selected, setSelected] = useState<string | null>(null)

  return (
    <>
      {elderly ? <HomeElderly /> : <HomeNormal onSelect={setSelected} />}
      <ApplianceDetailModal applianceId={selected} onClose={() => setSelected(null)} />
    </>
  )
}

/* ── 일반 모드 ─────────────────────────────────────────────────────────────
   상단 12-column Summary(6/3/3) + 가전 그리드 4열.
   '마지막 활동' 카드는 기획서 요구에 따라 두지 않는다.
   ───────────────────────────────────────────────────────────────────────── */
function HomeNormal({ onSelect }: { onSelect: (id: string) => void }) {
  const { t } = usePreferences()
  const { appliances, alertCount, onlineCount } = useHomeState()
  const safe = alertCount === 0

  return (
    <div className="mx-auto flex h-full max-w-[1400px] flex-col gap-5 px-6 py-4">
      <div className="grid shrink-0 grid-cols-12 gap-4">
        <section
          className={cn(
            'col-span-6 flex items-center gap-5 rounded-2xl border p-6',
            safe ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50',
          )}
        >
          <span
            className={cn(
              'flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl',
              safe ? 'bg-emerald-100' : 'bg-amber-100',
            )}
          >
            {safe
              ? <Shield className="h-8 w-8 text-emerald-600" aria-hidden="true" />
              : <AlertTriangle className="h-8 w-8 text-amber-600" aria-hidden="true" />}
          </span>
          <div className="min-w-0">
            <h2
              className={cn(
                'mb-1 text-xs font-semibold tracking-wider uppercase',
                safe ? 'text-emerald-600' : 'text-amber-600',
              )}
            >
              {t('home.summary.overall')}
            </h2>
            <p className={cn('text-2xl leading-tight font-bold', safe ? 'text-emerald-800' : 'text-amber-800')}>
              {t(safe ? 'home.summary.safe' : 'home.summary.attention')}
            </p>
            <p className={cn('mt-0.5 text-sm', safe ? 'text-emerald-700' : 'text-amber-700')}>
              {t(safe ? 'home.summary.safeSub' : 'home.summary.attentionSub')}
            </p>
          </div>
        </section>

        <section className="col-span-3 flex flex-col justify-between rounded-2xl border border-gray-100 bg-white p-5">
          <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50">
            <Wifi className="h-5 w-5 text-blue-600" aria-hidden="true" />
          </span>
          <div>
            <h2 className="mb-0.5 text-xs text-gray-500">{t('home.summary.devices')}</h2>
            <p className="tabular text-2xl font-bold text-gray-900">
              {t('home.summary.count', { n: appliances.length, m: onlineCount })}
            </p>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-emerald-600">
              <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
              {t('home.summary.devicesAllOk')}
            </p>
          </div>
        </section>

        <section
          className={cn(
            'col-span-3 flex flex-col justify-between rounded-2xl border p-5',
            safe ? 'border-gray-100 bg-white' : 'border-amber-200 bg-amber-50',
          )}
        >
          <span
            className={cn(
              'mb-3 flex h-10 w-10 items-center justify-center rounded-xl',
              safe ? 'bg-gray-50' : 'bg-amber-100',
            )}
          >
            <AlertTriangle className={cn('h-5 w-5', safe ? 'text-gray-400' : 'text-amber-600')} aria-hidden="true" />
          </span>
          <div>
            <h2 className="mb-0.5 text-xs text-gray-500">{t('home.summary.alerts')}</h2>
            <p className={cn('tabular text-2xl font-bold', safe ? 'text-gray-900' : 'text-amber-800')}>
              {t('home.summary.cases', { n: alertCount })}
            </p>
            <p className={cn('mt-0.5 text-xs', safe ? 'text-gray-500' : 'text-amber-700')}>
              {t(safe ? 'home.summary.alertsNone' : 'home.summary.alertsSome')}
            </p>
          </div>
        </section>
      </div>

      <section className="flex min-h-0 flex-1 flex-col">
        <div className="mb-3 flex shrink-0 items-center justify-between">
          <h2 className="text-base font-bold text-gray-900">{t('home.appliances')}</h2>
          <span className="text-sm text-gray-500">
            {t('home.appliances.count', { n: appliances.length })}
          </span>
        </div>
        <div className="grid grid-cols-4 gap-4" style={{ gridAutoRows: 'minmax(180px, auto)' }}>
          {appliances.map((appliance) => (
            <ApplianceCard key={appliance.id} appliance={appliance} onClick={() => onSelect(appliance.id)} />
          ))}
        </div>
      </section>
    </div>
  )
}

/* ── 어르신 모드 ───────────────────────────────────────────────────────────
   정보를 늘리지 않는다. 큰 상태 문구 + 큰 카드 3개만.
   전문 용어(AI 신뢰도, 센서, API)를 쓰지 않는다.
   ───────────────────────────────────────────────────────────────────────── */
function HomeElderly() {
  const { t } = usePreferences()
  const { alertCount, presence } = useHomeState()
  const safe = alertCount === 0
  const bathroomInUse = presence.bathroom?.detected ?? false

  const cards = [
    {
      key: 'kitchen',
      label: t('room.kitchen'),
      value: `✓ ${t('home.elderly.kitchenSafe')}`,
      tone: 'emerald' as const,
      Icon: UtensilsCrossed,
    },
    {
      key: 'bathroom',
      label: t('room.bathroom'),
      value: bathroomInUse ? t('home.elderly.bathroomInUse') : `✓ ${t('home.elderly.kitchenSafe')}`,
      tone: bathroomInUse ? ('blue' as const) : ('emerald' as const),
      Icon: Bath,
    },
    {
      key: 'connection',
      label: t('home.elderly.connection'),
      value: `✓ ${t('home.elderly.connectionOk')}`,
      tone: 'emerald' as const,
      Icon: Wifi,
    },
  ]

  const TONES = {
    emerald: 'bg-emerald-50 border-emerald-200 text-emerald-700',
    blue: 'bg-blue-50 border-blue-200 text-blue-700',
  }

  return (
    <div className="mx-auto flex h-full max-w-[1000px] flex-col px-6 py-6">
      <div className="mb-6 shrink-0 text-center">
        <p
          className={cn(
            'inline-flex items-center gap-3 rounded-2xl border px-7 py-4',
            safe ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50',
          )}
        >
          <CheckCircle2
            className={cn('h-7 w-7 shrink-0', safe ? 'text-emerald-600' : 'text-amber-600')}
            aria-hidden="true"
          />
          <span className={cn('text-2xl font-bold', safe ? 'text-emerald-700' : 'text-amber-700')}>
            {t(safe ? 'home.summary.safe' : 'home.summary.attention')}
          </span>
        </p>
      </div>

      <div className="grid flex-1 grid-cols-3 gap-5">
        {cards.map(({ key, label, value, tone, Icon }) => (
          <div
            key={key}
            className={cn(
              'flex flex-col items-center justify-center rounded-2xl border-2 p-6 text-center',
              TONES[tone],
            )}
          >
            <span className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-white shadow-sm">
              <Icon className="h-8 w-8 text-gray-600" aria-hidden="true" />
            </span>
            <p className="mb-2 text-2xl font-bold text-gray-900">{label}</p>
            <p className="text-lg font-semibold break-keep">{value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
