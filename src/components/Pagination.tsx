import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useT } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

/**
 * 스크롤 대신 페이지네이션.
 * (기획서: 1440×900 에서 테이블 + 페이지네이션이 스크롤 없이 모두 보여야 한다)
 */
export function Pagination({
  page, totalPages, onChange,
}: {
  page: number
  totalPages: number
  onChange: (next: number) => void
}) {
  const t = useT()
  if (totalPages <= 1) return null

  return (
    <nav className="flex items-center justify-center gap-2 py-4" aria-label="페이지 이동">
      <button
        type="button"
        onClick={() => onChange(Math.max(1, page - 1))}
        disabled={page === 1}
        aria-label={t('history.page.prev')}
        className="flex h-11 w-11 items-center justify-center rounded-lg border border-gray-200 text-gray-500 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
      </button>
      {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          aria-label={t('history.page.go', { n })}
          aria-current={page === n ? 'page' : undefined}
          className={cn(
            'h-11 min-w-11 rounded-lg px-3 text-sm font-semibold transition-colors',
            page === n
              ? 'bg-brand text-white'
              : 'border border-gray-200 text-gray-600 hover:bg-gray-50',
          )}
        >
          {n}
        </button>
      ))}
      <button
        type="button"
        onClick={() => onChange(Math.min(totalPages, page + 1))}
        disabled={page === totalPages}
        aria-label={t('history.page.next')}
        className="flex h-11 w-11 items-center justify-center rounded-lg border border-gray-200 text-gray-500 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ChevronRight className="h-4 w-4" aria-hidden="true" />
      </button>
    </nav>
  )
}
