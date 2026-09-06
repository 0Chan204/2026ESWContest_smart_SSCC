import { WifiOff, X } from 'lucide-react'
import { ROOM_KEY } from '@/lib/appliance'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'

/**
 * 연결 오류 안내.
 * MQTT / WebSocket 같은 내부 기술 용어를 사용자에게 노출하지 않는다.
 */
export function ConnectionBanner() {
  const { t } = usePreferences()
  const { connectionIssue, dismissConnectionIssue } = useHomeState()
  if (!connectionIssue) return null

  return (
    <div
      role="status"
      className="flex shrink-0 flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-6 py-2.5"
    >
      <WifiOff className="h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />
      <span className="text-sm font-medium text-amber-800">
        {t('connection.message', { room: t(ROOM_KEY[connectionIssue.room]) })}
      </span>
      <span className="text-sm text-amber-700">
        {t('connection.last', { sec: connectionIssue.lastReceivedSec })}
      </span>
      <button type="button" className="text-xs text-amber-800 underline">
        {t('connection.detail')}
      </button>
      <button
        type="button"
        onClick={dismissConnectionIssue}
        aria-label={t('connection.dismiss')}
        className="ml-auto flex h-8 w-8 items-center justify-center text-amber-600 hover:text-amber-900"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  )
}
