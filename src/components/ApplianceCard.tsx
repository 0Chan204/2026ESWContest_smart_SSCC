import { AlertTriangle, ChevronRight, WifiOff } from 'lucide-react'
import type { Appliance, ApplianceVariant } from '@/types'
import { ApplianceIcon } from './ApplianceIcon'
import { getVariant, POWER_KEY, ROOM_KEY } from '@/lib/appliance'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

interface VariantStyle {
  card: string
  iconBg: string
  name: string
  power: string
  room: string
  detail: string
}

/**
 * 상태별 시각 변형.
 * OFF 는 "고장"이 아니므로 Red/Orange 를 쓰지 않고, 카드 전체에서 색을 빼서(grayscale)
 * 켜진 기기와 한눈에 구분되게 한다. 단 읽기 어려울 만큼 투명하게 만들지는 않는다.
 */
const STYLES: Record<ApplianceVariant, VariantStyle> = {
  active: {
    card: 'bg-white border-gray-100 hover:border-blue-200 hover:shadow-md',
    iconBg: 'bg-blue-50',
    name: 'text-gray-900',
    power: 'text-brand font-semibold',
    room: 'text-gray-400',
    detail: 'text-gray-500',
  },
  standby: {
    card: 'bg-white border-gray-100 hover:border-blue-200 hover:shadow-md',
    iconBg: 'bg-gray-50',
    name: 'text-gray-900',
    power: 'text-gray-700 font-semibold',
    room: 'text-gray-400',
    detail: 'text-gray-500',
  },
  off: {
    card: 'bg-gray-100 border-gray-300 hover:border-gray-400 grayscale',
    iconBg: 'bg-gray-200',
    name: 'text-gray-600',
    power: 'text-gray-600 font-semibold',
    room: 'text-gray-500',
    detail: 'text-gray-500',
  },
  warning: {
    card: 'bg-amber-50 border-amber-200 hover:border-amber-300',
    iconBg: 'bg-amber-100',
    name: 'text-gray-900',
    power: 'text-amber-700 font-semibold',
    room: 'text-amber-600',
    detail: 'text-amber-700',
  },
  danger: {
    card: 'bg-red-50 border-red-300 hover:border-red-400',
    iconBg: 'bg-red-100',
    name: 'text-gray-900',
    power: 'text-red-700 font-semibold',
    room: 'text-red-600',
    detail: 'text-red-700',
  },
  offline: {
    card: 'bg-gray-100 border-gray-300 grayscale',
    iconBg: 'bg-gray-300',
    name: 'text-gray-500',
    power: 'text-gray-500 font-semibold',
    room: 'text-gray-400',
    detail: 'text-gray-500',
  },
}

export function ApplianceCard({
  appliance, onClick, size = 'md',
}: {
  appliance: Appliance
  onClick: () => void
  size?: 'md' | 'lg'
}) {
  const { t } = usePreferences()
  const variant = getVariant(appliance)
  const s = STYLES[variant]
  const large = size === 'lg'

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        // 카드가 세로로 늘어나도 아이콘은 위, 상태는 아래에 고정되도록 flex column 으로 잡는다.
        'group flex h-full w-full flex-col rounded-2xl border text-left transition-all',
        large ? 'p-4' : 'p-4',
        s.card,
      )}
    >
      <div className="mb-3 flex items-start justify-between">
        <div
          className={cn(
            'flex items-center justify-center rounded-xl',
            large ? 'h-12 w-12' : 'h-10 w-10',
            s.iconBg,
          )}
        >
          <ApplianceIcon id={appliance.id} variant={variant} className={large ? 'h-7 w-7' : 'h-6 w-6'} />
        </div>
        <span className="flex items-center gap-1.5">
          {/* 색상만이 아니라 아이콘 + 텍스트로 상태를 함께 표시한다 */}
          {variant === 'offline' && (
            <span className="flex items-center gap-1 text-xs font-semibold text-gray-500">
              <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />
              {t('appliance.disconnected')}
            </span>
          )}
          {(variant === 'warning' || variant === 'danger') && (
            <span
              className={cn(
                'flex items-center gap-1 text-xs font-semibold',
                variant === 'danger' ? 'text-red-600' : 'text-amber-600',
              )}
            >
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              {t(variant === 'danger' ? 'status.danger' : 'status.warning')}
            </span>
          )}
          {variant === 'standby' && (
            <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
              {t('status.normal')}
            </span>
          )}
          {variant === 'active' && (
            <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
              {t('status.normal')}
            </span>
          )}
          {variant === 'off' && (
            <span className="flex items-center gap-1 text-xs font-medium text-gray-500">
              <span className="h-1.5 w-1.5 rounded-full bg-gray-400" aria-hidden="true" />
              {t('appliance.off')}
            </span>
          )}
        </span>
      </div>

      <div className="flex-1">
        <p className={cn('mb-0.5 font-semibold', large ? 'text-xl' : 'text-sm', s.name)}>
          {appliance.name}
        </p>
        <p className={cn('mb-2', large ? 'text-base' : 'text-xs', s.room)}>
          {t(ROOM_KEY[appliance.room])}
        </p>
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <span className={cn(large ? 'text-lg' : 'text-sm', s.power)}>
            {t(POWER_KEY[appliance.power])}
          </span>
          <span className={cn('ml-1.5', large ? 'text-base' : 'text-xs', s.detail)}>
            {appliance.detail}
          </span>
        </div>
        <ChevronRight
          className={cn(
            'h-4 w-4 shrink-0 transition-colors',
            variant === 'active' ? 'text-gray-300 group-hover:text-blue-400' : 'text-gray-400',
          )}
          aria-hidden="true"
        />
      </div>
    </button>
  )
}
