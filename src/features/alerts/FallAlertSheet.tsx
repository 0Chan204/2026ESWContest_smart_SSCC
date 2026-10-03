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
      <div className="pt-7">
        <div className={cn('flex items-center gap-3 rounded-2xl px-5 py-4', pending ? 'bg-danger text-white' : 'bg-sunken text-ink')}>
          <TriangleAlert className={cn('h-7 w-7 shrink-0', pending && 'soft-pulse')} aria-hidden="true" />
          <div>
            <p className={cn('font-bold', big ? 'text-3xl' : 'text-2xl')}>욕실에서 낙상이 감지됐어요</p>
            <p className={cn('opacity-90', big ? 'text-lg' : 'text-[0.9375rem]')}>{formatTime(fall.detectedAt)} 감지{!big && ` · 감지 정확도 ${Math.round(fall.confidence * 100)}%`}</p>
          </div>
        </div>

        <ul className={cn('mt-5 space-y-3', big ? 'text-xl' : 'text-[1rem]')}>
          {fall.burnerShutOff && (
            <Step icon={<Power className="h-5 w-5" />} tone="ok">켜져 있던 인덕션 전원을 바로 껐어요</Step>
          )}
          {g ? (
            <Step icon={<Check className="h-5 w-5" />} tone="ok">보호자 {g.name}님({maskPhone(g.phone)})께 문자를 보냈어요</Step>
          ) : (
            <Step icon={<MessageSquareWarning className="h-5 w-5" />} tone="warn">보호자 연락처가 없어 문자를 보내지 못했어요 · 설정에서 등록해 주세요</Step>
          )}
          {pending ? (
            <Step icon={<Clock3 className="h-5 w-5" />} tone="danger">
              응답이 없으면 <b className="tabular">{formatCountdown(left)}</b> 후 자동으로 신고돼요
            </Step>
          ) : (
            <Step icon={<Check className="h-5 w-5" />} tone={fall.status === 'resolved' ? 'ok' : 'danger'}>{FALL_STATUS_LABEL[fall.status]}</Step>
          )}
        </ul>
      </div>
    </Sheet>
  )
}

function Step({ icon, tone, children }: { icon: React.ReactNode; tone: 'ok' | 'warn' | 'danger'; children: React.ReactNode }) {
  const c = { ok: 'bg-ok-soft text-ok', warn: 'bg-warn-soft text-warn', danger: 'bg-danger-soft text-danger' }[tone]
  return (
    <li className="flex items-start gap-3">
      <span className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full', c)} aria-hidden="true">{icon}</span>
      <span className="pt-1 leading-snug text-ink">{children}</span>
    </li>
  )
}
