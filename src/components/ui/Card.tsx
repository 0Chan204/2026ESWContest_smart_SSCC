import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** 흰(다크: 짙은 회색) 면. 테두리 없이 바탕과의 대비로 구분한다. */
export function Card({ children, className, as: Tag = 'section' }: {
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article'
}) {
  // 상태 색 배경(bg-*-soft 등)을 넘기면 기본 배경을 쓰지 않는다 (CSS 순서에 따라 덮어쓰이는 문제 방지)
  const hasBg = /(^|\s)bg-/.test(className ?? '')
  return <Tag className={cn('rounded-2xl', !hasBg && 'bg-surface', className)}>{children}</Tag>
}

/** 화면 안 구역 제목 (iOS 의 굵은 섹션 제목) */
export function SectionTitle({ children, action, className }: { children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('mb-2.5 flex items-end justify-between gap-3', className)}>
      <h2 className="text-[1.25rem] font-bold tracking-[-0.01em] text-ink">{children}</h2>
      {action}
    </div>
  )
}
