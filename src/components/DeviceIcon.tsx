import { CookingPot, Droplet, Fan, Lightbulb } from 'lucide-react'
import type { Device } from '@/types'
import { cn } from '@/lib/cn'

const ICON = { induction: CookingPot, purifier: Droplet, fan: Fan, light: Lightbulb } as const

/** 기기 아이콘. 켜져 있으면 포인트 색, 꺼져 있거나 끊기면 회색. */
export function DeviceIcon({ kind, active, className, size = 'md' }: {
  kind: Device['kind']
  active: boolean
  className?: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const Icon = ICON[kind]
  const box = { sm: 'h-9 w-9', md: 'h-11 w-11', lg: 'h-14 w-14' }[size]
  const ic = { sm: 'h-[18px] w-[18px]', md: 'h-[22px] w-[22px]', lg: 'h-7 w-7' }[size]
  return (
    <span className={cn('flex shrink-0 items-center justify-center rounded-full', box, active ? 'bg-brand-soft' : 'bg-sunken', className)}>
      <Icon className={cn(ic, active ? 'text-brand' : 'text-ink-3')} strokeWidth={1.9} aria-hidden="true" />
    </span>
  )
}
