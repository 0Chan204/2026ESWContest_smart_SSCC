import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'quiet'
type Size = 'sm' | 'md' | 'lg' | 'xl'

const VARIANT: Record<Variant, string> = {
  primary: 'bg-brand text-white hover:bg-brand-dark',
  secondary: 'bg-sunken text-ink hover:bg-line',
  danger: 'bg-danger text-white hover:brightness-95',
  ghost: 'bg-transparent text-brand hover:bg-brand-soft',
  quiet: 'bg-transparent text-ink-2 hover:bg-sunken',
}
const SIZE: Record<Size, string> = {
  sm: 'min-h-9 px-3 text-sm rounded-lg',
  md: 'min-h-11 px-4 text-[0.9375rem] rounded-xl',
  lg: 'min-h-13 px-5 text-base rounded-2xl',
  xl: 'min-h-16 px-6 text-lg rounded-2xl',
}

export function Button({
  variant = 'secondary', size = 'md', className, children, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; children: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      className={cn(
        'inline-flex items-center justify-center gap-2 font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        VARIANT[variant], SIZE[size], className,
      )}
    >
      {children}
    </button>
  )
}
