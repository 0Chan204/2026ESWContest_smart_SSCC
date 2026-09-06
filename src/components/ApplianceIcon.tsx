import { Droplets, Flame, Sun, Wind, Zap } from 'lucide-react'
import type { ApplianceVariant } from '@/types'
import { cn } from '@/lib/cn'

const ICONS: Record<string, typeof Flame> = {
  induction: Flame,
  purifier: Droplets,
  fan: Wind,
  light: Sun,
}

const COLORS: Record<string, string> = {
  induction: 'text-orange-500',
  purifier: 'text-blue-500',
  fan: 'text-cyan-500',
  light: 'text-yellow-500',
}

export function ApplianceIcon({
  id, variant = 'active', className,
}: {
  id: string
  variant?: ApplianceVariant
  className?: string
}) {
  const Icon = ICONS[id] ?? Zap
  // OFF / 오프라인 기기는 채도를 완전히 뺀다.
  const desaturated = variant === 'off' || variant === 'offline'
  const color = desaturated ? 'text-gray-400' : (COLORS[id] ?? 'text-gray-500')
  return <Icon className={cn(className ?? 'h-6 w-6', color)} aria-hidden="true" />
}
