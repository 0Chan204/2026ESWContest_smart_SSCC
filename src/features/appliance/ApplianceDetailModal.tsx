import { Check, Minus, X } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { ApplianceIcon } from '@/components/ApplianceIcon'
import { EventTimeline } from '@/components/EventTimeline'
import { getVariant, POWER_KEY, ROOM_KEY } from '@/lib/appliance'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import { cn } from '@/lib/cn'

/**
 * 가전 상세 팝업.
 *
 * 제어 버튼은 supportsControl 이 true 인 기기에만 렌더링한다.
 * 음성으로 할 수 있는 조작은 반드시 여기에서 버튼으로도 할 수 있어야 한다.
 */
export function ApplianceDetailModal({
  applianceId, onClose,
}: {
  applianceId: string | null
  onClose: () => void
}) {
  const { t } = usePreferences()
  const { applianceById, setPower } = useHomeState()
  const appliance = applianceId ? applianceById(applianceId) : undefined

  if (!appliance) return null
  const isOn = appliance.power === 'ON'
  const variant = getVariant(appliance)

  const rows: [string, string][] = [
    [t('appliance.power'), t(POWER_KEY[appliance.power])],
    [t('appliance.connection'), t('status.normal')],
    [t('appliance.current'), appliance.detail],
    [t('appliance.lastUpdate'), appliance.lastUpdate],
    [t('appliance.detail'), appliance.sub],
  ]

  return (
    <Modal open onClose={onClose} labelledBy="appliance-modal-title" size="lg">
      <header className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
        <div>
          <h2 id="appliance-modal-title" className="text-lg font-bold text-gray-900">
            {appliance.name}
          </h2>
          <p className="text-sm text-gray-500">{t(ROOM_KEY[appliance.room])}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close')}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <div className="px-6 py-5">
        <div className="mb-4 flex gap-5">
          <div
            className={cn(
              'flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl',
              isOn ? 'bg-blue-50' : 'bg-gray-100',
            )}
          >
            <ApplianceIcon id={appliance.id} variant={variant} className="h-10 w-10" />
          </div>
          <dl className="grid flex-1 grid-cols-2 gap-x-4 gap-y-2.5">
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-gray-400">{label}</dt>
                <dd className="text-sm font-semibold text-gray-800">{value}</dd>
              </div>
            ))}
          </dl>
        </div>

        {appliance.supportsControl ? (
          <div className="mb-4 rounded-xl bg-gray-50 p-3">
            <p className="mb-2 text-xs font-semibold text-gray-500">{t('appliance.control')}</p>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setPower(appliance.id, 'ON')}
                aria-pressed={isOn}
                className={cn(
                  'flex min-h-12 items-center justify-center gap-1.5 rounded-xl border-2 text-sm font-semibold transition-all',
                  isOn
                    ? 'bg-brand border-brand text-white'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-blue-300',
                )}
              >
                <Check className="h-4 w-4" aria-hidden="true" /> {t('appliance.turnOn')}
              </button>
              <button
                type="button"
                onClick={() => setPower(appliance.id, 'OFF')}
                aria-pressed={!isOn}
                className={cn(
                  'flex min-h-12 items-center justify-center gap-1.5 rounded-xl border-2 text-sm font-semibold transition-all',
                  !isOn
                    ? 'border-gray-700 bg-gray-700 text-white'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-gray-400',
                )}
              >
                <Minus className="h-4 w-4" aria-hidden="true" /> {t('appliance.turnOff')}
              </button>
            </div>
          </div>
        ) : (
          <p className="mb-4 rounded-xl bg-gray-50 px-3 py-2.5 text-xs text-gray-500">
            {t('appliance.noControl')}
          </p>
        )}

        <div className="border-t border-gray-100 pt-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-700">{t('appliance.recentHistory')}</h3>
          <EventTimeline events={appliance.history} max={3} dense />
        </div>
      </div>

      <footer className="border-t border-gray-100 bg-gray-50 px-6 py-4">
        <button
          type="button"
          onClick={onClose}
          className="bg-brand hover:bg-brand-dark min-h-12 w-full rounded-xl text-sm font-semibold text-white transition-colors"
        >
          {t('appliance.close')}
        </button>
      </footer>
    </Modal>
  )
}
