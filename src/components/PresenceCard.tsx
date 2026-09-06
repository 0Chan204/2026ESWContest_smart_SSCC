import { User, UserX } from 'lucide-react'
import type { Presence } from '@/types'
import { StatusBadge } from './StatusBadge'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

/**
 * 재실 감지 카드.
 * 어르신 모드에서는 'AI 신뢰도' 같은 전문 용어를 표시하지 않는다.
 */
export function PresenceCard({ presence }: { presence: Presence }) {
  const { t, elderly } = usePreferences()
  const { detected, lastDetectedSec, action, confidence } = presence

  if (elderly) {
    return (
      <div
        className={cn(
          'rounded-2xl border-2 p-5 text-center',
          detected ? 'border-emerald-200 bg-emerald-50' : 'border-gray-200 bg-gray-50',
        )}
      >
        <div
          className={cn(
            'mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full',
            detected ? 'bg-emerald-100' : 'bg-gray-200',
          )}
        >
          {detected
            ? <User className="h-7 w-7 text-emerald-600" aria-hidden="true" />
            : <UserX className="h-7 w-7 text-gray-400" aria-hidden="true" />}
        </div>
        <p className={cn('mb-1 text-2xl font-bold', detected ? 'text-emerald-700' : 'text-gray-600')}>
          {t(detected ? 'presence.detectedElderly' : 'presence.noneElderly')}
        </p>
        <p className="text-base text-gray-500">
          {t('presence.lastElderly', { sec: lastDetectedSec })}
        </p>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'rounded-2xl border bg-white p-4 shadow-sm',
        detected ? 'border-emerald-200' : 'border-gray-200',
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-700">{t('presence.title')}</p>
        <StatusBadge status={detected ? 'normal' : 'offline'} />
      </div>
      <div className="flex items-center gap-4">
        <div
          className={cn(
            'flex h-12 w-12 shrink-0 items-center justify-center rounded-xl',
            detected ? 'bg-emerald-50' : 'bg-gray-100',
          )}
        >
          {detected
            ? <User className="h-6 w-6 text-emerald-600" aria-hidden="true" />
            : <UserX className="h-6 w-6 text-gray-400" aria-hidden="true" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className={cn('text-base font-bold', detected ? 'text-emerald-700' : 'text-gray-500')}>
            {t(detected ? 'presence.detected' : 'presence.none')}
          </p>
          <p className="text-xs text-gray-400">
            {t('presence.meta', { action, sec: lastDetectedSec })}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="mb-0.5 text-xs text-gray-400">{t('presence.confidence')}</p>
          <p className="tabular text-base font-bold text-gray-700">{confidence}%</p>
        </div>
      </div>
    </div>
  )
}
