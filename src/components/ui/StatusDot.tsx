import type { Risk } from '@/types'
import { RISK_TONE } from '@/lib/labels'
import { cn } from '@/lib/cn'

/** 점 + 글자. 상태를 색만으로 전달하지 않는다. */
export function StatusText({ risk, children, className }: { risk: Risk; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 font-medium', RISK_TONE[risk].text, className)}>
      <span className={cn('h-2 w-2 shrink-0 rounded-full', RISK_TONE[risk].strong, risk === 'danger' && 'soft-pulse')} aria-hidden="true" />
      {children}
    </span>
  )
}

export function Badge({ tone = 'muted', children }: { tone?: 'muted' | 'brand' | 'ok' | 'warn' | 'danger' | 'caution'; children: React.ReactNode }) {
  const cls = {
    muted: 'bg-muted-soft text-ink-2', brand: 'bg-brand-soft text-brand', ok: 'bg-ok-soft text-ok',
    warn: 'bg-warn-soft text-warn', danger: 'bg-danger-soft text-danger', caution: 'bg-caution-soft text-caution',
  }[tone]
  return <span className={cn('inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold', cls)}>{children}</span>
}
