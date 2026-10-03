import { cn } from '@/lib/cn'

export function Segmented<T extends string | number>({ value, options, onChange, label, size = 'md' }: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
  size?: 'md' | 'lg'
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex w-full rounded-xl bg-sunken p-1">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'flex-1 rounded-lg font-semibold transition-all',
            size === 'lg' ? 'min-h-12 text-base' : 'min-h-10 text-sm',
            value === o.value ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(0,0,0,0.08)]' : 'text-ink-3 hover:text-ink-2',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
