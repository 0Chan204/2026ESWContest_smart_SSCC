import { useEffect, useRef } from 'react'
import { Check, Clock3, ExternalLink, MessageSquareWarning, Power, TriangleAlert } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/Button'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useSpeech } from '@/hooks/useSpeech'
import { useNow } from '@/hooks/useNow'
import { FALL_STATUS_LABEL } from '@/lib/labels'
import { formatCountdown, formatTime } from '@/lib/format'
import { maskPhone } from '@/lib/phone'
import { cn } from '@/lib/cn'

/**
 * 대시보드 낙상 경보 (WS fall.incident).
 * 서버가 이미 수행한 일(인덕션 비상 차단 · 보호자 문자)과 남은 일(자동 신고까지 시간)을 한 화면에 보여준다.
 */
export function FallAlertSheet() {
  const { fall, fallAlertOpen, setFallAlert, contacts, source } = useHome()
  const { elderly } = usePreferences()
  const speak = useSpeech()
  const now = useNow()
  const spokenFor = useRef<string | null>(null)

  useEffect(() => {
    if (fall?.status === 'pending' && fallAlertOpen && spokenFor.current !== fall.incidentId) {
      spokenFor.current = fall.incidentId
      speak('욕실에서 넘어지신 것 같아요. 보호자에게 바로 알렸어요.')
    }
  }, [fall, fallAlertOpen, speak])

  if (!fall || !fallAlertOpen) return null
  const pending = fall.status === 'pending'
  const left = (new Date(fall.autoReportAt).getTime() - now) / 1000
  const g = contacts.guardian
  const big = elderly

  return (
    <Sheet open onClose={() => setFallAlert(false)} width={big ? 680 : 560} urgent hideClose dismissOnBackdrop={false}
      footer={(
        <div className="flex gap-2">
          {source.demo && pending && (
            <Button size={big ? 'xl' : 'lg'} className="flex-1" onClick={() => window.open(fall.confirmUrl, '_blank', 'noopener,noreferrer')}>
              <ExternalLink className="h-5 w-5" aria-hidden="true" />보호자 화면 보기
            </Button>
          )}
          <Button variant={pending ? 'danger' : 'primary'} size={big ? 'xl' : 'lg'} className="flex-1" onClick={() => setFallAlert(false)}>
            {pending ? '확인했어요' : '닫기'}
          </Button>
        </div>
      )}>
      <div className={cn('-mx-5 mt-2 flex items-center gap-4 px-6 py-5 md:mx-0 md:mt-5 md:rounded-2xl', pending ? 'bg-danger-fill text-white' : 'bg-surface text-ink')}>
        <TriangleAlert className={cn('h-9 w-9 shrink-0', pending && 'soft-pulse')} strokeWidth={1.8} aria-hidden="true" />
        <div>
          <p className={cn('font-bold', big ? 'text-3xl' : 'text-[1.5rem]')}>욕실 낙상 감지</p>
          <p className={cn(pending ? 'text-white/85' : 'text-ink-2', big ? 'text-lg' : 'text-[0.9375rem]')}>
            {formatTime(fall.detectedAt)}{!big && ` · 정확도 ${Math.round(fall.confidence * 100)}%`}
          </p>
        </div>
      </div>

      <ul className={cn('inset-list mt-6 overflow-hidden rounded-xl bg-surface', big ? 'text-xl' : 'text-[1rem]')}>
        {fall.burnerShutOff && <Step icon={Power} tone="ok">켜져 있던 인덕션 전원을 껐어요</Step>}
        {g
          ? <Step icon={Check} tone="ok">보호자 {g.name}님({maskPhone(g.phone)})께 문자를 보냈어요</Step>
          : <Step icon={MessageSquareWarning} tone="warn">보호자 연락처가 없어 문자를 못 보냈어요</Step>}
        {pending
          ? <Step icon={Clock3} tone="danger">응답이 없으면 <b className="tabular">{formatCountdown(left)}</b> 후 자동 신고</Step>
          : <Step icon={Check} tone={fall.status === 'resolved' ? 'ok' : 'danger'}>{FALL_STATUS_LABEL[fall.status]}</Step>}
      </ul>
    </Sheet>
  )
}

function Step({ icon: Icon, tone, children }: { icon: typeof Check; tone: 'ok' | 'warn' | 'danger'; children: React.ReactNode }) {
  const c = { ok: 'text-ok', warn: 'text-warn', danger: 'text-danger' }[tone]
  return (
    <li className="flex items-center gap-3 pl-4">
      <Icon className={cn('h-5 w-5 shrink-0', c)} strokeWidth={2.2} aria-hidden="true" />
      <span className="row-sep flex-1 py-3.5 pr-4 leading-snug text-ink">{children}</span>
    </li>
  )
}
