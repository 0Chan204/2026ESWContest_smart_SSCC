import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/cn'

type IconType = LucideIcon

/**
 * iOS '설정' 앱 방식의 묶음 목록.
 * 제목(작은 회색 글자) · 둥근 흰 칸 · 줄 사이 얇은 구분선 · 아래 설명(선택)
 */
export function ListGroup({ title, footer, action, children, className, bodyClassName }: {
  title?: ReactNode
  footer?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={className}>
      {(title || action) && (
        <div className="mb-1.5 flex items-end justify-between gap-3 px-4">
          {title && <h3 className="text-[0.8125rem] font-medium text-ink-3">{title}</h3>}
          {action}
        </div>
      )}
      <div className={cn('inset-list overflow-hidden rounded-xl bg-surface', bodyClassName)}>{children}</div>
      {footer && <p className="mt-1.5 px-4 text-[0.8125rem] leading-snug text-ink-3">{footer}</p>}
    </section>
  )
}

/** 목록 한 줄. onClick 이 있으면 버튼이 된다. */
export function ListRow({
  leading, title, subtitle, value, trailing, chevron = false, onClick, big = false, titleClass, wrap = false,
}: {
  leading?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  value?: ReactNode
  trailing?: ReactNode
  chevron?: boolean
  onClick?: () => void
  big?: boolean
  titleClass?: string
  /** 보조 글이 길면 줄바꿈 */
  wrap?: boolean
}) {
  const body = (
    <>
      {leading && <span className="flex shrink-0 items-center">{leading}</span>}
      <span className={cn('row-sep flex min-w-0 flex-1 items-center gap-3 pr-4', big ? 'min-h-16 py-3 short:min-h-14 short:py-2' : 'min-h-[3.25rem] py-2.5')}>
        <span className="min-w-0 flex-1">
          <span className={cn('block truncate text-ink', big ? 'text-[1.25rem]' : 'text-[1rem]', titleClass)}>{title}</span>
          {subtitle && <span className={cn('block text-ink-2', wrap ? 'leading-snug' : 'truncate', big ? 'text-[1rem]' : 'text-[0.8125rem]')}>{subtitle}</span>}
        </span>
        {value !== undefined && <span className={cn('tabular shrink-0 text-ink-2', big ? 'text-[1.0625rem]' : 'text-[0.9375rem]')}>{value}</span>}
        {trailing}
        {chevron && <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" strokeWidth={2.4} aria-hidden="true" />}
      </span>
    </>
  )
  const cls = cn('flex w-full items-center gap-3 pl-4 text-left', onClick && 'press hover:bg-sunken')
  return onClick
    ? <button type="button" onClick={onClick} className={cls}>{body}</button>
    : <div className={cls}>{body}</div>
}

const SYM = {
  blue: 'bg-sym-blue', green: 'bg-sym-green', gray: 'bg-sym-gray', red: 'bg-sym-red', orange: 'bg-sym-orange', indigo: 'bg-sym-indigo',
} as const

/** iOS 설정 앱의 색깔 사각 아이콘 */
export function SymbolIcon({ icon: Icon, color }: { icon: IconType; color: keyof typeof SYM }) {
  return (
    <span className={cn('flex h-[30px] w-[30px] items-center justify-center rounded-[8px]', SYM[color])}>
      <Icon className="h-[18px] w-[18px] text-white" strokeWidth={2.2} aria-hidden="true" />
    </span>
  )
}
