import { useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useHome } from '@/store/HomeStore'
import type { SafetyEvent } from '@/types'

/** 자동 조치 적절성 피드백 (시나리오 4막). 모델·임계값 조정의 근거 데이터가 된다. */
export function FeedbackButtons({ event, size = 'md' }: { event: SafetyEvent; size?: 'md' | 'lg' }) {
  const { submitFeedback } = useHome()
  const [busy, setBusy] = useState(false)
  const done = event.feedback

  if (done) {
    return (
      <p className="px-4 text-[0.875rem] text-ink-3">
        {done.verdict === 'approved' ? '“적절했어요”' : '“과했어요”'} 로 남겼어요. 판단 기준을 다듬는 데 참고할게요.
      </p>
    )
  }
  const send = async (v: 'approved' | 'rejected') => {
    setBusy(true)
    try { await submitFeedback(event.eventId, v) } finally { setBusy(false) }
  }
  const s = size === 'lg' ? 'xl' : 'lg'
  return (
    <div>
      <p className="mb-1.5 px-4 text-[0.8125rem] font-medium text-ink-3">이 조치가 적절했나요?</p>
      <div className="flex gap-2">
        <Button variant="plain" size={s} className="flex-1" disabled={busy} onClick={() => send('approved')}>
          <ThumbsUp className="h-4 w-4" aria-hidden="true" />적절했어요
        </Button>
        <Button variant="plain" size={s} className="flex-1" disabled={busy} onClick={() => send('rejected')}>
          <ThumbsDown className="h-4 w-4" aria-hidden="true" />과했어요
        </Button>
      </div>
    </div>
  )
}
