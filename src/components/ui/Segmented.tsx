import { cn } from '@/lib/cn'

/** iOS 세그먼트 컨트롤. 같은 자리에서 보기를 바꿀 때 쓴다. */
export function Segmented<T extends string | number>({ value, options, onChange, label, size = 'md', className }: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
  /** md 36px · touch 44px(터치 패널) · lg 48px(어르신) */
  size?: 'md' | 'touch' | 'lg'
  className?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn('flex rounded-[10px] bg-fill p-[3px]', className)}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'flex-1 rounded-[8px] font-semibold transition-colors',
            size === 'lg' ? 'min-h-12 text-[1.0625rem]' : size === 'touch' ? 'min-h-11 text-[0.9375rem]' : 'min-h-9 text-[0.875rem]',
            value === o.value ? 'bg-thumb text-ink shadow-[var(--shadow-thumb)]' : 'text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
