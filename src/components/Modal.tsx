import type { ReactNode } from 'react'
import { useDismissable } from '@/hooks/useDismissable'
import { cn } from '@/lib/cn'

interface ModalProps {
  open: boolean
  onClose: () => void
  /** 배경 클릭으로 닫히지 않게 하려면 false (위험 알림 등) */
  dismissOnBackdrop?: boolean
  labelledBy: string
  size?: 'sm' | 'md' | 'lg'
  children: ReactNode
  /** 위험 알림처럼 즉시 낭독이 필요한 경우 */
  urgent?: boolean
}

const SIZES = {
  sm: 'max-w-[420px]',
  md: 'max-w-[520px]',
  lg: 'max-w-[620px]',
} as const

export function Modal({
  open, onClose, dismissOnBackdrop = true, labelledBy, size = 'md', children, urgent,
}: ModalProps) {
  const containerRef = useDismissable(open, onClose)
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={dismissOnBackdrop ? onClose : undefined}
        aria-hidden="true"
      />
      <div
        ref={containerRef}
        role={urgent ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={cn(
          'relative w-full overflow-hidden rounded-2xl bg-white shadow-2xl',
          'max-h-[calc(100dvh-48px)] overflow-y-auto',
          SIZES[size],
        )}
      >
        {children}
      </div>
    </div>
  )
}
