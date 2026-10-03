import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/cn'

export function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (n: number) => void }) {
  if (totalPages <= 1) return null
  const btn = 'flex h-11 min-w-11 items-center justify-center rounded-xl text-sm font-semibold transition-colors'
  return (
    <nav className="flex items-center justify-center gap-1.5" aria-label="페이지 이동">
      <button type="button" aria-label="이전 페이지" disabled={page === 1} onClick={() => onChange(page - 1)}
        className={cn(btn, 'text-ink-2 hover:bg-sunken disabled:opacity-30')}>
        <ChevronLeft className="h-5 w-5" aria-hidden="true" />
      </button>
      {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
        <button key={n} type="button" onClick={() => onChange(n)} aria-current={n === page ? 'page' : undefined}
          aria-label={`${n}페이지`}
          className={cn(btn, 'px-3', n === page ? 'bg-ink text-white' : 'text-ink-2 hover:bg-sunken')}>
          {n}
        </button>
      ))}
      <button type="button" aria-label="다음 페이지" disabled={page === totalPages} onClick={() => onChange(page + 1)}
        className={cn(btn, 'text-ink-2 hover:bg-sunken disabled:opacity-30')}>
        <ChevronRight className="h-5 w-5" aria-hidden="true" />
      </button>
    </nav>
  )
}
