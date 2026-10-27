import { useApplyTheme } from '@/hooks/useApplyTheme'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { CheckCircle2, Phone, ShieldAlert, TriangleAlert } from 'lucide-react'
import { createFallApi } from '@/data/fallApi'
import { useNow } from '@/hooks/useNow'
import { formatAgo, formatCountdown, formatWhen } from '@/lib/format'
import { ROOM_LABEL } from '@/lib/labels'
import type { FallIncident } from '@/types'
import { cn } from '@/lib/cn'

type View =
  | { kind: 'loading' }
  | { kind: 'invalid' }
  | { kind: 'error' }
  | { kind: 'ready'; incident: FallIncident }

const POLL_MS = 5000

/**
 * 보호자 낙상 확인 페이지 — 문자 링크로 휴대폰에서 열린다.
 * 대시보드와 별개인 단독 화면 (모드 선택·메뉴 없음, 세로 모바일 레이아웃).
 *
 * 보안: 링크의 token 은 읽은 즉시 주소창에서 지운다(화면 공유·스크린샷·방문 기록 노출 방지).
 * 토큰은 메모리에만 두므로 새로고침하면 문자의 링크를 다시 눌러야 한다.
 */
export function FallConfirmPage() {
  useApplyTheme('light')   // 보호자 휴대폰: 야외에서도 잘 보이도록 항상 라이트
  const { incidentId = '' } = useParams()
  const api = useMemo(createFallApi, [])
  const tokenRef = useRef<string | null>(null)
  if (tokenRef.current === null) {
    tokenRef.current = new URLSearchParams(window.location.search).get('token') ?? ''
  }
  const token = tokenRef.current
  const [view, setView] = useState<View>({ kind: 'loading' })
  const [confirm, setConfirm] = useState<'resolve' | 'report' | null>(null)
  const [busy, setBusy] = useState(false)
  const now = useNow()

  useEffect(() => {
    if (window.location.search) window.history.replaceState(null, '', window.location.pathname)
    document.title = 'HomeVIS 안전 알림'
  }, [])

  const load = useCallback(async () => {
    if (!token || !incidentId) return setView({ kind: 'invalid' })
    try {
      const i = await api.get(incidentId, token)
      setView(i ? { kind: 'ready', incident: i } : { kind: 'invalid' })
    } catch {
      setView((v) => (v.kind === 'ready' ? v : { kind: 'error' }))
    }
  }, [api, incidentId, token])

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), POLL_MS)
    const off = api.watch(incidentId, (i) => setView({ kind: 'ready', incident: i }))
    return () => { clearInterval(id); off() }
  }, [api, incidentId, load])

  const act = async (kind: 'resolve' | 'report') => {
    setBusy(true)
    try {
      const i = kind === 'resolve' ? await api.resolve(incidentId, token) : await api.report(incidentId, token)
      setView({ kind: 'ready', incident: i })
    } catch (e) {
      setView(e instanceof Error && e.message === 'invalid' ? { kind: 'invalid' } : { kind: 'error' })
    } finally {
      setBusy(false); setConfirm(null)
    }
  }

  return (
    <div className="page-mobile bg-canvas">
      <div className="mx-auto flex min-h-full max-w-[480px] flex-col px-5 pt-6 pb-8">
        <header className="mb-5 flex items-center gap-2 text-[0.9375rem] font-semibold text-ink-2">
          <ShieldAlert className="h-5 w-5" aria-hidden="true" />HomeVIS 안전 알림
          {api.demo && <span className="ml-auto rounded-md bg-muted-soft px-2 py-0.5 text-xs text-ink-3">시연</span>}
        </header>

        {view.kind === 'loading' && <p className="py-20 text-center text-lg text-ink-2">확인하고 있어요…</p>}
        {view.kind === 'invalid' && (
          <Message title="링크를 확인할 수 없어요"
            body="링크가 만료됐거나 주소가 올바르지 않아요. 보안을 위해 새로고침하면 다시 확인할 수 없으니, 받은 문자의 링크를 다시 눌러 주세요." />
        )}
        {view.kind === 'error' && (
          <Message title="연결이 원활하지 않아요" body="인터넷 연결을 확인한 뒤 잠시 후 다시 시도해 주세요. 위급하면 바로 119 에 전화해 주세요." />
        )}
        {view.kind === 'ready' && (
          <Incident incident={view.incident} now={now} busy={busy} onAsk={setConfirm} />
        )}

        <a href="tel:119"
          className="mt-auto flex min-h-14 items-center justify-center gap-2 rounded-2xl border-2 border-danger/30 bg-surface text-lg font-bold text-danger">
          <Phone className="h-5 w-5" aria-hidden="true" />위급하면 119 에 바로 전화
        </a>
      </div>

      {confirm && (
        <div className="fixed inset-0 z-50 flex items-end justify-center">
          <div className="absolute inset-0 bg-[rgba(17,19,22,0.45)]" onClick={() => !busy && setConfirm(null)} aria-hidden="true" />
          <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
            className="relative w-full max-w-[480px] rounded-t-3xl bg-surface px-6 pt-6 pb-8">
            <h2 id="confirm-title" className="text-xl font-bold text-ink">
              {confirm === 'resolve' ? '괜찮다고 확인할까요?' : '신고를 요청할까요?'}
            </h2>
            <p className="mt-2 text-[1rem] leading-relaxed text-ink-2">
              {confirm === 'resolve'
                ? '직접 연락해서 무사한 것을 확인했을 때만 눌러 주세요. 자동 신고가 취소돼요.'
                : '신고 요청이 HomeVIS 안전 기록에 남아요. 응급 상황이면 119 에도 직접 전화해 주세요.'}
            </p>
            <div className="mt-6 flex gap-2">
              <button type="button" disabled={busy} onClick={() => setConfirm(null)}
                className="min-h-14 flex-1 rounded-2xl bg-sunken text-lg font-semibold text-ink">취소</button>
              <button type="button" disabled={busy} onClick={() => act(confirm)}
                className={cn('min-h-14 flex-1 rounded-2xl text-lg font-bold text-white disabled:opacity-50', confirm === 'resolve' ? 'bg-brand' : 'bg-danger-fill')}>
                {busy ? '처리 중…' : confirm === 'resolve' ? '괜찮아요' : '신고 요청'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Incident({ incident, now, busy, onAsk }: {
  incident: FallIncident; now: number; busy: boolean; onAsk: (k: 'resolve' | 'report') => void
}) {
  const pending = incident.status === 'pending'
  const total = Math.max(1, new Date(incident.autoReportAt).getTime() - new Date(incident.detectedAt).getTime())
  const left = (new Date(incident.autoReportAt).getTime() - now) / 1000
  const progress = Math.min(100, Math.max(0, ((now - new Date(incident.detectedAt).getTime()) / total) * 100))

  return (
    <div className="mb-6 space-y-4">
      <section className={cn('rounded-2xl p-6', pending ? 'bg-danger-fill text-white' : 'bg-surface text-ink')}>
        <TriangleAlert className={cn('h-9 w-9', pending ? 'soft-pulse' : 'text-danger')} aria-hidden="true" />
        <h1 className="mt-3 text-[1.75rem] leading-tight font-bold">{ROOM_LABEL[incident.room]}에서 낙상이 감지됐어요</h1>
        <p className={cn('mt-2 text-[1rem]', pending ? 'text-white/85' : 'text-ink-2')}>
          {formatWhen(incident.detectedAt)} · {formatAgo(incident.detectedAt, now)}
        </p>
      </section>

      {pending ? (
        <>
          <section className="rounded-2xl bg-surface p-6">
            <p className="text-[1rem] text-ink-2">응답이 없으면 자동으로 신고돼요</p>
            <p className="tabular mt-1 text-[2.75rem] leading-none font-bold text-ink">{formatCountdown(left)}</p>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-sunken" role="progressbar"
              aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} aria-label="자동 신고까지 남은 시간">
              <div className="h-full rounded-full bg-danger transition-[width] duration-1000 ease-linear" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-4 text-[0.9375rem] leading-relaxed text-ink-2">
              {incident.burnerShutOff && '켜져 있던 인덕션은 자동으로 꺼졌어요. '}먼저 전화로 안부를 확인해 주세요.
            </p>
          </section>
          <div className="space-y-2.5">
            <button type="button" disabled={busy} onClick={() => onAsk('report')}
              className="min-h-16 w-full rounded-2xl bg-danger-fill text-xl font-bold text-white disabled:opacity-50">도움이 필요해요 · 신고 요청</button>
            <button type="button" disabled={busy} onClick={() => onAsk('resolve')}
              className="min-h-16 w-full rounded-2xl bg-surface text-xl font-bold text-ink disabled:opacity-50">괜찮아요 · 확인했어요</button>
          </div>
        </>
      ) : (
        <section className="rounded-2xl bg-surface p-6">
          <CheckCircle2 className={cn('h-9 w-9', incident.status === 'resolved' ? 'text-ok' : 'text-danger')} aria-hidden="true" />
          <h2 className="mt-3 text-2xl font-bold text-ink">
            {incident.status === 'resolved' && '괜찮다고 확인됐어요'}
            {incident.status === 'reported' && '신고 요청이 접수됐어요'}
            {incident.status === 'auto_reported' && '응답이 없어 자동으로 신고됐어요'}
          </h2>
          <p className="mt-2 text-[1rem] leading-relaxed text-ink-2">
            {incident.status === 'resolved'
              ? '확인해 주셔서 고마워요. 이 내용은 HomeVIS 안전 기록에 남아요.'
              : '안전 기록에 남았어요. 응급 상황이면 아래 버튼으로 119 에 바로 전화해 주세요.'}
          </p>
        </section>
      )}
    </div>
  )
}

function Message({ title, body }: { title: string; body: string }) {
  return (
    <section className="mb-6 rounded-2xl bg-surface p-6">
      <h1 className="text-2xl font-bold text-ink">{title}</h1>
      <p className="mt-2 text-[1rem] leading-relaxed text-ink-2">{body}</p>
    </section>
  )
}
