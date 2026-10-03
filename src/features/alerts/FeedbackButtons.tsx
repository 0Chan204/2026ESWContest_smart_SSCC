import { useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { useHome } from '@/store/HomeStore'
import type { SafetyEvent } from '@/types'
import { cn } from '@/lib/cn'

/** 자동 조치 적절성 피드백 (시나리오 4막). 모델·임계값 조정의 근거 데이터가 된다. */
export function FeedbackButtons({ event, size = 'md' }: { event: SafetyEvent; size?: 'md' | 'lg' }) {
  const { submitFeedback } = useHome()
  const [busy, setBusy] = useState(false)
  const done = event.feedback

  if (done) {
    return (
      <p className="rounded-xl bg-sunken px-4 py-3 text-sm text-ink-2">
        {done.verdict === 'approved' ? '“적절했어요” 로 남겨주셨어요.' : '“과했어요” 로 남겨주셨어요.'} 판단 기준을 다듬는 데 참고할게요.
      </p>
    )
  }
  const send = async (v: 'approved' | 'rejected') => {
    setBusy(true)
    try { await submitFeedback(event.eventId, v) } finally { setBusy(false) }
  }
  const btn = cn('flex flex-1 items-center justify-center gap-2 rounded-xl bg-sunken font-semibold text-ink hover:bg-line disabled:opacity-40',
    size === 'lg' ? 'min-h-14 text-lg' : 'min-h-11 text-[0.9375rem]')
  return (
    <div>
      <p className={cn('mb-2 font-semibold text-ink', size === 'lg' ? 'text-lg' : 'text-sm')}>이 자동 조치가 적절했나요?</p>
      <div className="flex gap-2">
        <button type="button" className={btn} disabled={busy} onClick={() => send('approved')}>
          <ThumbsUp className="h-4 w-4" aria-hidden="true" />적절했어요
        </button>
        <button type="button" className={btn} disabled={busy} onClick={() => send('rejected')}>
          <ThumbsDown className="h-4 w-4" aria-hidden="true" />과했어요
        </button>
      </div>
    </div>
  )
}
