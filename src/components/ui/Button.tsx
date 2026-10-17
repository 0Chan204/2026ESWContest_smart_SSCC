import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

type Variant = 'primary' | 'secondary' | 'plain' | 'danger' | 'ghost' | 'quiet'
type Size = 'sm' | 'md' | 'lg' | 'xl'

/** iOS 버튼 스타일: 채움(파랑) · 회색 · 흰색 · 위험(빨강) · 글자만 */
const VARIANT: Record<Variant, string> = {
  primary: 'bg-brand text-white',
  secondary: 'bg-fill text-ink',
  /** 회색 바탕(시트 등) 위의 흰 버튼 */
  plain: 'bg-surface text-ink',
  danger: 'bg-danger-fill text-white',
  ghost: 'bg-transparent text-brand-ink',
  quiet: 'bg-transparent text-ink-2',
}
const SIZE: Record<Size, string> = {
  sm: 'min-h-9 px-3.5 text-[0.875rem] rounded-[10px]',
  md: 'min-h-11 px-4 text-[1rem] rounded-[12px]',
  lg: 'min-h-[50px] px-5 text-[1.0625rem] rounded-[14px]',
  xl: 'min-h-[60px] px-6 text-[1.25rem] rounded-[16px]',
}

export function Button({
  variant = 'secondary', size = 'md', className, children, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; children: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      className={cn(
        'press inline-flex items-center justify-center gap-2 font-semibold disabled:cursor-not-allowed disabled:opacity-40',
        VARIANT[variant], SIZE[size], className,
      )}
    >
      {children}
    </button>
  )
}
