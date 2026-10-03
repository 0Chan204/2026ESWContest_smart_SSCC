import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** 흰 면 카드. 테두리 없이 바탕(연회색)과의 대비로 구분한다. */
export function Card({ children, className, as: Tag = 'section' }: {
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article'
}) {
  // 상태 색 배경(bg-*-soft 등)을 넘기면 기본 흰 배경을 쓰지 않는다 (CSS 순서에 따라 덮어쓰이는 문제 방지)
  const hasBg = /(^|\s)bg-/.test(className ?? '')
  return <Tag className={cn('rounded-3xl', !hasBg && 'bg-surface', className)}>{children}</Tag>
}

export function CardTitle({ title, action, className }: { title: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('mb-3 flex items-center justify-between gap-3', className)}>
      <h2 className="text-[0.9375rem] font-semibold text-ink">{title}</h2>
      {action}
    </div>
  )
}
