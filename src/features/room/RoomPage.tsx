import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { ApplianceCard } from '@/components/ApplianceCard'
import { EnvCard } from '@/components/EnvCard'
import { EventTimeline } from '@/components/EventTimeline'
import { PresenceCard } from '@/components/PresenceCard'
import { ApplianceDetailModal } from '@/features/appliance/ApplianceDetailModal'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import type { RoomId } from '@/types'
import type { TKey } from '@/i18n'
import { cn } from '@/lib/cn'

interface RoomConfig {
  titleKey: TKey
  subtitleKey: TKey
  envKey: TKey
  eventsKey: TKey
  /** 위험 상황 시뮬레이션 버튼 노출 여부 */
  canSimulate: boolean
  /** 어르신 모드 본문 구성 */
  elderlyBody: 'appliances' | 'environment'
  envColumns: string
}

const CONFIG: Record<RoomId, RoomConfig> = {
  kitchen: {
    titleKey: 'kitchen.title',
    subtitleKey: 'kitchen.subtitle',
    envKey: 'kitchen.env',
    eventsKey: 'kitchen.events',
    canSimulate: true,
    elderlyBody: 'appliances',
    envColumns: 'grid-cols-4',
  },
  bathroom: {
    titleKey: 'bathroom.title',
    subtitleKey: 'bathroom.subtitle',
    envKey: 'bathroom.env',
    eventsKey: 'bathroom.events',
    canSimulate: false,
    elderlyBody: 'environment',
    envColumns: 'grid-cols-3',
  },
}

/**
 * 주방 / 화장실 공통 화면.
 * 같은 레이아웃 시스템·카드 스타일·간격을 쓰기 때문에 한 컴포넌트로 관리한다.
 * (화장실만 별개 서비스처럼 보이지 않게 하라는 요구사항)
 */
export function RoomPage({ room }: { room: RoomId }) {
  const { elderly } = usePreferences()
  const [selected, setSelected] = useState<string | null>(null)

  return (
    <>
      {elderly
        ? <RoomElderly room={room} onSelect={setSelected} />
        : <RoomNormal room={room} onSelect={setSelected} />}
      <ApplianceDetailModal applianceId={selected} onClose={() => setSelected(null)} />
    </>
  )
}

function RoomNormal({ room, onSelect }: { room: RoomId; onSelect: (id: string) => void }) {
  const { t } = usePreferences()
  const { appliances, presence, environment, roomEvents, triggerIncident } = useHomeState()
  const config = CONFIG[room]
  const roomAppliances = appliances.filter((a) => a.room === room)
  const env = environment[room]
  const p = presence[room]

  return (
    <div className="mx-auto flex h-full max-w-[1400px] flex-col px-6 py-4">
      <div className="mb-4 flex shrink-0 items-start justify-between gap-4">
        <div>
          <h1 className="mb-0.5 text-xl font-bold text-gray-900">{t(config.titleKey)}</h1>
          <p className="text-sm text-gray-500">{t(config.subtitleKey)}</p>
        </div>
        {config.canSimulate && (
          <button
            type="button"
            onClick={() => triggerIncident(room)}
            className="flex min-h-11 shrink-0 items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-100"
          >
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            {t('kitchen.simulate')}
          </button>
        )}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-3 gap-5">
        <div className="col-span-2 flex min-h-0 flex-col gap-4">
          {p && <PresenceCard presence={p} />}

          <section>
            <h2 className="mb-2 text-xs font-semibold tracking-wide text-gray-600 uppercase">
              {t(config.envKey)}
            </h2>
            <div className={cn('grid gap-2', config.envColumns)}>
              {env?.metrics.map((metric) => <EnvCard key={metric.key} metric={metric} />)}
            </div>
          </section>

          {roomAppliances.length > 0 && (
            <section className="flex min-h-0 flex-1 flex-col">
              <h2 className="mb-2 shrink-0 text-xs font-semibold tracking-wide text-gray-600 uppercase">
                {t('section.appliances')}
              </h2>
              {/* 기기 수에 맞춰 한 줄에 담아 세로 스크롤이 생기지 않게 한다 */}
              <div
                className={cn('grid min-h-0 flex-1 gap-3', roomAppliances.length >= 3 ? 'grid-cols-3' : 'grid-cols-2')}
                style={{ gridAutoRows: 'minmax(0, 1fr)' }}
              >
                {roomAppliances.map((appliance) => (
                  <ApplianceCard
                    key={appliance.id}
                    appliance={appliance}
                    onClick={() => onSelect(appliance.id)}
                  />
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="col-span-1 min-h-0">
          <section className="flex h-full flex-col overflow-hidden rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
            <h2 className="mb-3 shrink-0 text-sm font-semibold text-gray-700">{t(config.eventsKey)}</h2>
            {/* 화면 높이를 늘리지 않도록 표시 건수를 제한한다 */}
            <EventTimeline events={roomEvents[room] ?? []} max={4} />
          </section>
        </div>
      </div>
    </div>
  )
}

function RoomElderly({ room, onSelect }: { room: RoomId; onSelect: (id: string) => void }) {
  const { t } = usePreferences()
  const { appliances, presence, environment, triggerIncident } = useHomeState()
  const config = CONFIG[room]
  const roomAppliances = appliances.filter((a) => a.room === room)
  const p = presence[room]
  const env = environment[room]

  return (
    <div className="mx-auto flex h-full max-w-[1100px] flex-col gap-4 overflow-hidden px-6 py-5">
      {/* 어르신 화면은 정보를 늘리지 않는다. 제목만 크게 둔다. */}
      <h1 className="shrink-0 text-3xl font-bold text-gray-900">{t(config.titleKey)}</h1>

      {p && <PresenceCard presence={p} />}

      {config.elderlyBody === 'appliances' ? (
        <div className={cn('grid gap-4', roomAppliances.length >= 3 ? 'grid-cols-3' : 'grid-cols-2')}>
          {roomAppliances.map((appliance) => (
            <ApplianceCard
              key={appliance.id}
              appliance={appliance}
              size="lg"
              onClick={() => onSelect(appliance.id)}
            />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {env?.metrics
            .filter((m) => m.key === 'humidity' || m.key === 'temp')
            .map((metric) => (
              <div key={metric.key} className="rounded-2xl border border-gray-200 bg-white p-5">
                <p className="mb-1 text-lg font-bold text-gray-700">
                  {t(metric.key === 'humidity' ? 'env.humidity' : 'env.temp')}
                </p>
                <p
                  className={cn(
                    'tabular text-3xl font-bold',
                    metric.key === 'humidity' ? 'text-blue-600' : 'text-orange-500',
                  )}
                >
                  {metric.value}
                  <span className="text-lg font-normal text-gray-500"> {metric.unit}</span>
                </p>
                <p
                  className={cn(
                    'mt-1 text-base font-semibold',
                    metric.status === 'warning' ? 'text-amber-700' : 'text-emerald-700',
                  )}
                >
                  {metric.status === 'warning' ? '⚠ 다소 높습니다' : '✓ 정상입니다'}
                </p>
              </div>
            ))}
        </div>
      )}

      {config.canSimulate && (
        <button
          type="button"
          onClick={() => triggerIncident(room)}
          className="flex min-h-16 shrink-0 items-center justify-center gap-2 rounded-2xl bg-amber-500 text-xl font-bold text-white transition-colors hover:bg-amber-600"
        >
          <AlertTriangle className="h-6 w-6" aria-hidden="true" />
          {t('kitchen.simulate')}
        </button>
      )}
    </div>
  )
}
