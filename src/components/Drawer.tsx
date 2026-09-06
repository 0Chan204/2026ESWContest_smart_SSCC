import type { ReactNode } from 'react'
import { useDismissable } from '@/hooks/useDismissable'

interface DrawerProps {
  open: boolean
  onClose: () => void
  labelledBy: string
  children: ReactNode
}

/** 오른쪽에서 슬라이드되는 설정 드로어 */
export function Drawer({ open, onClose, labelledBy, children }: DrawerProps) {
  const containerRef = useDismissable(open, onClose)
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className="absolute top-0 right-0 flex h-full w-[360px] max-w-[90vw] flex-col bg-white shadow-2xl"
      >
        {children}
      </div>
    </div>
  )
}
