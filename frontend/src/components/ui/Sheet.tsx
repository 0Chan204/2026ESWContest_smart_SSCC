import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { useDismissable } from '@/hooks/useDismissable'
import { cn } from '@/lib/cn'

/**
 * 모달 시트. center = 가운데 다이얼로그, side = 오른쪽 상세 패널.
 * 휴대폰 폭(768px 미만)에서는 둘 다 아래에서 올라오는 시트(손잡이 막대 포함)로 바뀐다.
 * 닫기 버튼은 iOS 의 회색 원형 X.
 */
export function Sheet({
  open, onClose, title, subtitle, children, footer, variant = 'center', width = 520,
  urgent = false, dismissOnBackdrop = true, hideClose = false,
}: {
  open: boolean
  onClose: () => void
  title?: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
  variant?: 'center' | 'side'
  width?: number
  urgent?: boolean
  dismissOnBackdrop?: boolean
  hideClose?: boolean
}) {
  const ref = useDismissable(open, onClose)
  if (!open) return null
  const side = variant === 'side'
  return (
    <div className={cn(
      'fixed inset-0 z-50 flex items-end justify-center',
      side ? 'md:items-stretch md:justify-end md:p-3' : 'md:items-center md:p-6',
    )}>
      <div className="absolute inset-0 bg-[var(--scrim)]" onClick={dismissOnBackdrop ? onClose : undefined} aria-hidden="true" />
      <div
        ref={ref}
        role={urgent ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        tabIndex={-1}
        aria-label={typeof title === 'string' ? title : undefined}
        style={{ ['--sheet-w' as string]: `${width}px` }}
        className={cn(
          'relative flex w-full flex-col bg-canvas shadow-[var(--shadow-pop)]',
          'max-h-[92dvh] rounded-t-[22px] md:w-[var(--sheet-w)]',
          side
            ? 'md:h-full md:max-h-none md:max-w-[92vw] md:rounded-[22px]'
            : 'md:max-h-[calc(100dvh-48px)] md:max-w-[calc(100vw-48px)] md:rounded-[22px]',
        )}
      >
        <span className="mx-auto mt-2 h-[5px] w-9 shrink-0 rounded-full bg-track md:hidden" aria-hidden="true" />
        {(title || !hideClose) && (
          <header className="flex shrink-0 items-start justify-between gap-4 px-5 pt-4 pb-3 md:pt-5">
            <div className="min-w-0 pl-1">
              {title && <h2 className="text-[1.375rem] leading-tight font-bold tracking-[-0.01em] text-ink">{title}</h2>}
              {subtitle && <p className="mt-1 text-[0.875rem] text-ink-2">{subtitle}</p>}
            </div>
            {!hideClose && (
              <button type="button" onClick={onClose} aria-label="닫기"
                className="press flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full bg-fill text-ink-2">
                <X className="h-4 w-4" strokeWidth={2.6} aria-hidden="true" />
              </button>
            )}
          </header>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5">{children}</div>
        {footer && <footer className="shrink-0 px-5 pt-1 pb-5">{footer}</footer>}
      </div>
    </div>
  )
}
