import { cn } from '@/lib/cn'

/** iOS·One UI 계열 스위치. role=switch 로 스크린리더에 상태를 알린다. */
export function Toggle({ checked, onChange, label, disabled, size = 'md' }: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
  size?: 'md' | 'lg'
}) {
  const lg = size === 'lg'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={(e) => { e.stopPropagation(); onChange(!checked) }}
      className={cn(
        'relative inline-flex shrink-0 items-center rounded-full transition-colors disabled:opacity-40',
        lg ? 'h-9 w-16' : 'h-7 w-12',
        checked ? 'bg-brand' : 'bg-[#cfd3d9]',
      )}
    >
      <span
        className={cn(
          'absolute rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.18)] transition-transform',
          lg ? 'top-1 left-1 h-7 w-7' : 'top-1 left-1 h-5 w-5',
          checked && (lg ? 'translate-x-7' : 'translate-x-5'),
        )}
      />
    </button>
  )
}
