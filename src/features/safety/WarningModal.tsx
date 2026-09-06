import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, Droplets, Flame, Info, UserX } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import type { SafetyIncident } from '@/types'
import { cn } from '@/lib/cn'

const FACT_ICONS = { flame: Flame, userX: UserX, droplets: Droplets } as const

/**
 * 위험 알림.
 * 위험 상황마다 새로 마운트되도록 key 를 주어 카운트다운이 항상 정확한 값에서 시작하게 한다.
 */
export function WarningModal() {
  const { activeIncident } = useHomeState()
  if (!activeIncident) return null
  return <WarningDialog key={activeIncident.id} incident={activeIncident} />
}

function WarningDialog({ incident }: { incident: SafetyIncident }) {
  const { t, elderly } = usePreferences()
  const { resolveIncident, cancelIncident } = useHomeState()
  const [remaining, setRemaining] = useState(incident.countdownSec)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (remaining <= 0) {
      const id = setTimeout(resolveIncident, 400)
      return () => clearTimeout(id)
    }
    const id = setTimeout(() => setRemaining((n) => n - 1), 1000)
    return () => clearTimeout(id)
  }, [remaining, resolveIncident])

  const progress = ((incident.countdownSec - remaining) / incident.countdownSec) * 100

  return (
    <Modal
      open
      onClose={cancelIncident}
      dismissOnBackdrop={false}
      labelledBy="warning-title"
      size={elderly ? 'lg' : 'sm'}
      urgent
    >
      <div className="flex items-center gap-3 bg-amber-500 px-6 py-4">
        <AlertTriangle className="h-6 w-6 shrink-0 text-white" aria-hidden="true" />
        <h2 id="warning-title" className={cn('font-bold text-white', elderly ? 'text-2xl' : 'text-lg')}>
          {incident.title}
        </h2>
      </div>

      <div className="px-6 py-5">
        <p
          className={cn(
            'mb-4 leading-relaxed break-keep whitespace-pre-line text-gray-700',
            elderly ? 'text-xl' : 'text-sm',
          )}
        >
          {incident.description}
        </p>

        <ul className="mb-4 space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3.5">
          {incident.facts.map((fact) => {
            const Icon = FACT_ICONS[fact.icon]
            return (
              <li
                key={fact.text}
                className={cn(
                  'flex items-center gap-2',
                  elderly ? 'text-lg' : 'text-sm',
                  fact.emphasis ? 'font-semibold text-gray-800' : 'text-amber-800',
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {fact.text}
              </li>
            )
          })}
        </ul>

        <div className="mb-4">
          <div className="mb-1.5 flex items-center justify-between">
            <p className={cn('text-gray-600', elderly ? 'text-lg' : 'text-sm')}>
              {remaining > 0 ? t('warning.countdown', { n: remaining }) : t('warning.running')}
            </p>
            <span className="tabular text-lg font-bold text-amber-600">{Math.max(0, remaining)}</span>
          </div>
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-gray-200"
            role="progressbar"
            aria-valuenow={Math.round(progress)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-2 rounded-full bg-amber-500 transition-all duration-1000 ease-linear"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* 어르신 모드에서는 접지 않고 쉬운 문장으로 바로 보여준다 */}
        {!elderly && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="flex min-h-11 items-center gap-2 text-sm text-gray-600 transition-colors hover:text-gray-800"
          >
            <Info className="h-4 w-4" aria-hidden="true" />
            {t('warning.why')}
            <ChevronDown className={cn('h-4 w-4 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
          </button>
        )}

        {(expanded || elderly) && (
          <ul className="mt-2 space-y-1.5 rounded-xl bg-gray-50 p-3">
            {incident.reasoning.map((reason) => (
              <li key={reason} className={cn('flex items-center gap-2 text-gray-700', elderly ? 'text-lg' : 'text-sm')}>
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-gray-100 px-6 py-4">
        <button
          type="button"
          onClick={cancelIncident}
          className={cn(
            'w-full rounded-xl border border-gray-300 font-medium text-gray-700 transition-colors hover:bg-gray-50',
            elderly ? 'min-h-16 text-xl' : 'min-h-12 text-sm',
          )}
        >
          {t('warning.handleMyself')}
        </button>
      </div>
    </Modal>
  )
}
