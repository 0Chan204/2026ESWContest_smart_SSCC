import { Droplets, Sun, Thermometer, Wind } from 'lucide-react'
import type { EnvMetric } from '@/types'
import { useT } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

const ICONS = {
  lux: Sun,
  temp: Thermometer,
  humidity: Droplets,
  air: Wind,
} as const

const LABEL_KEYS = {
  lux: 'env.lux',
  temp: 'env.temp',
  humidity: 'env.humidity',
  air: 'env.air',
} as const

export function EnvCard({ metric }: { metric: EnvMetric }) {
  const t = useT()
  const Icon = ICONS[metric.key]
  const valueColor =
    metric.status === 'warning'
      ? 'text-amber-600'
      : metric.status === 'danger'
        ? 'text-red-600'
        : 'text-gray-800'

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 text-gray-400" aria-hidden="true" />
        <span className="text-xs text-gray-400">{t(LABEL_KEYS[metric.key])}</span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className={cn('tabular text-xl leading-none font-bold', valueColor)}>{metric.value}</span>
        {metric.unit && <span className="text-xs text-gray-400">{metric.unit}</span>}
      </div>
    </div>
  )
}
