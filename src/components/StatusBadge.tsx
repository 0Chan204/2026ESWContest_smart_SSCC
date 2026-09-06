import { AlertTriangle, CheckCircle2, Info, WifiOff } from 'lucide-react'
import { useT } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

export type BadgeStatus = 'normal' | 'warning' | 'danger' | 'offline' | 'success' | 'canceled' | 'info'

const STYLES: Record<BadgeStatus, string> = {
  normal: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  danger: 'bg-red-50 text-red-700 border-red-200',
  offline: 'bg-gray-100 text-gray-500 border-gray-200',
  canceled: 'bg-gray-100 text-gray-600 border-gray-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
}

const ICONS: Record<BadgeStatus, typeof CheckCircle2> = {
  normal: CheckCircle2,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: AlertTriangle,
  offline: WifiOff,
  canceled: Info,
  info: Info,
}

const LABEL_KEYS = {
  normal: 'status.normal',
  success: 'status.success',
  warning: 'status.warning',
  danger: 'status.danger',
  offline: 'status.offline',
  canceled: 'status.canceled',
  info: 'status.info',
} as const

/**
 * 상태를 색상만으로 구분하지 않고 아이콘 + 텍스트를 항상 함께 쓴다.
 * (색각 이상 사용자 및 어르신 가독성 대응)
 */
export function StatusBadge({ status }: { status: BadgeStatus }) {
  const t = useT()
  const Icon = ICONS[status]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold',
        STYLES[status],
      )}
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
      {t(LABEL_KEYS[status])}
    </span>
  )
}
