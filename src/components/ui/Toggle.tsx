import { cn } from '@/lib/cn'

/** iOS 스위치 (켜지면 초록). role=switch 로 스크린리더에 상태를 알린다. */
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
        'relative inline-flex shrink-0 items-center rounded-full transition-colors duration-200 disabled:opacity-40',
        lg ? 'h-[38px] w-[64px]' : 'h-[31px] w-[51px]',
        checked ? 'bg-switch' : 'bg-track',
      )}
    >
      <span
        className={cn(
          'absolute top-[2px] left-[2px] rounded-full bg-white shadow-[0_3px_8px_rgba(0,0,0,0.15),0_1px_1px_rgba(0,0,0,0.16)] transition-transform duration-200',
          lg ? 'h-[34px] w-[34px]' : 'h-[27px] w-[27px]',
          checked && (lg ? 'translate-x-[26px]' : 'translate-x-[20px]'),
        )}
      />
    </button>
  )
}
