import { CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import { Modal } from '@/components/Modal'
import { usePreferences } from '@/store/PreferencesContext'
import { useHomeState } from '@/store/HomeStateContext'
import { ROOM_KEY } from '@/lib/appliance'
import { cn } from '@/lib/cn'

/** 안전 조치 완료 결과. 이 시점에 이미 처리 이력에 자동 기록되어 있다. */
export function ResultModal() {
  const { t, elderly } = usePreferences()
  const { lastResult, clearResult } = useHomeState()
  if (!lastResult) return null

  return (
    <Modal open onClose={clearResult} labelledBy="result-title" size={elderly ? 'lg' : 'sm'}>
      <div className="px-6 pt-8 pb-5 text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-emerald-50">
          <CheckCircle2 className="h-9 w-9 text-emerald-600" aria-hidden="true" />
        </div>
        <h2 id="result-title" className={cn('mb-2 font-bold text-gray-900', elderly ? 'text-3xl' : 'text-xl')}>
          {t('result.title')}
        </h2>
        <p className={cn('break-keep text-gray-600', elderly ? 'text-xl' : 'text-sm')}>
          {t(ROOM_KEY[lastResult.room])} · {lastResult.content}
        </p>
      </div>

      <div className="px-6 pb-6">
        <div className="mb-4 rounded-xl bg-gray-50 p-4">
          <p className="mb-2.5 text-xs font-semibold tracking-wider text-gray-500 uppercase">
            {t('result.reasoning')}
          </p>
          <ul className="space-y-2">
            {lastResult.reasoning.map((reason) => (
              <li key={reason} className={cn('flex items-center gap-2 text-gray-700', elderly ? 'text-lg' : 'text-sm')}>
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
        </div>

        <button
          type="button"
          onClick={clearResult}
          className={cn(
            'bg-brand hover:bg-brand-dark mb-2 w-full rounded-xl font-semibold text-white transition-colors',
            elderly ? 'min-h-16 text-xl' : 'min-h-12',
          )}
        >
          {t('result.confirm')}
        </button>

        {/* 잘못된 판단 신고는 일반 모드에서만 노출한다 (어르신 화면 단순화) */}
        {!elderly && (
          <button
            type="button"
            onClick={() => {
              toast.success(t('result.reported'))
              clearResult()
            }}
            className="min-h-11 w-full text-sm text-gray-500 transition-colors hover:text-gray-700"
          >
            {t('result.report')}
          </button>
        )}
      </div>
    </Modal>
  )
}
