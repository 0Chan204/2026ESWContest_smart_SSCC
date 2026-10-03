import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { useDismissable } from '@/hooks/useDismissable'
import { cn } from '@/lib/cn'

/**
 * 모달 시트. center = 가운데 다이얼로그, side = 오른쪽에서 열리는 상세 패널.
 * ESC / 바깥 터치로 닫히고 포커스는 시트 안에 갇힌다.
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
    <div className={cn('fixed inset-0 z-50 flex', side ? 'justify-end' : 'items-center justify-center p-6')}>
      <div className="absolute inset-0 bg-[rgba(17,19,22,0.42)]" onClick={dismissOnBackdrop ? onClose : undefined} aria-hidden="true" />
      <div
        ref={ref}
        role={urgent ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        style={{ width, maxWidth: side ? '92vw' : 'calc(100vw - 48px)' }}
        className={cn(
          'relative flex flex-col bg-surface shadow-[0_12px_40px_rgba(0,0,0,0.16)]',
          side ? 'h-full rounded-l-3xl' : 'max-h-[calc(100dvh-48px)] rounded-3xl',
        )}
      >
        {(title || !hideClose) && (
          <header className="flex shrink-0 items-start justify-between gap-4 px-7 pt-6 pb-3">
            <div className="min-w-0">
              {title && <h2 className="text-xl font-bold text-ink">{title}</h2>}
              {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
            </div>
            {!hideClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="닫기"
                className="-mt-1 -mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink-3 hover:bg-sunken"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            )}
          </header>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-7 pb-6">{children}</div>
        {footer && <footer className="shrink-0 px-7 pt-2 pb-6">{footer}</footer>}
      </div>
    </div>
  )
}
