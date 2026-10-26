import { Mic, X } from 'lucide-react'
import { EXAMPLE_COMMANDS } from './commands'
import type { VoiceController, VoiceState } from './useVoice'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { cn } from '@/lib/cn'

const LABEL: Record<Exclude<VoiceState, 'processing' | 'completed' | 'error'>, string> = {
  idle: '무엇을 도와드릴까요?', listening: '듣고 있어요', recognized: '알아들었어요', confirm: '',
}

/** 레일의 마이크 버튼 옆에 뜨는 음성 패널 */
export function VoicePanel({ voice }: { voice: VoiceController }) {
  const { elderly } = usePreferences()
  const { state, heard, reply, pending, demo, progress, errorText } = voice
  const big = elderly
  const text = state === 'completed' ? reply : state === 'error' ? errorText : state === 'processing' ? progress : LABEL[state]
  return (
    <div role="dialog" aria-modal="false" aria-label="음성 명령"
      className={cn('fixed inset-x-3 bottom-[88px] z-40 overflow-hidden rounded-[22px] bg-surface shadow-[var(--shadow-pop)] md:inset-x-auto md:bottom-5',
        elderly ? 'md:left-[128px] md:w-[440px]' : 'md:left-[104px] md:w-[380px]')}>
      <div className="flex items-center justify-between px-5 pt-4">
        <span className="flex items-center gap-2 text-[0.8125rem] font-semibold text-ink-3">
          음성 명령{demo && <span className="font-normal">· 예시</span>}
        </span>
        <button type="button" onClick={voice.close} aria-label="닫기" className="press -mr-2 flex h-11 w-11 items-center justify-center rounded-full">
          <span className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-fill text-ink-2">
            <X className="h-4 w-4" strokeWidth={2.6} aria-hidden="true" />
          </span>
        </button>
      </div>
      <div className="px-5 pb-5">
        <div className="flex items-center gap-4">
          {state === 'listening' ? (
            <span className="wave flex h-10 w-10 shrink-0 items-center justify-center gap-[3px]" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => <span key={i} className="h-7 w-[4px] rounded-full bg-brand" />)}
            </span>
          ) : (
            <Mic className={cn('h-8 w-8 shrink-0', state === 'error' ? 'text-danger' : state === 'completed' ? 'text-ok' : 'text-ink-3')}
              strokeWidth={1.8} aria-hidden="true" />
          )}
          <div aria-live="polite" className="min-w-0">
            {heard && <p className={cn('font-semibold text-ink', big ? 'text-xl' : 'text-[1.0625rem]')}>“{heard}”</p>}
            {text && <p className={cn(state === 'completed' ? 'text-ink' : 'text-ink-2', big ? 'text-lg' : 'text-[0.9375rem]')}>{text}</p>}
          </div>
        </div>

        {state === 'confirm' && pending && <Confirm voice={voice} big={big} />}

        {state === 'listening' && (
          <ul className="mt-4 flex flex-wrap gap-1.5">
            {EXAMPLE_COMMANDS.map((c) => <li key={c} className="rounded-full bg-fill px-3 py-1.5 text-[0.8125rem] text-ink-2">{c}</li>)}
          </ul>
        )}
      </div>
    </div>
  )
}

/** 확인 창: 서버(또는 시연 규칙)가 만든 문장 그대로 + 남은 시간 */
function Confirm({ voice, big }: { voice: VoiceController; big: boolean }) {
  const now = useNow(1000)
  const pending = voice.pending!
  const left = pending.deadline ? Math.max(0, Math.ceil((new Date(pending.deadline).getTime() - now) / 1000)) : null
  return (
    <div className="mt-4">
      <p className={cn('font-semibold text-ink', big ? 'text-xl' : 'text-base')}>{pending.message}</p>
      {left !== null && !Number.isNaN(left) && (
        <p className="tabular mt-0.5 text-[0.8125rem] text-ink-3">{left}초 뒤 자동으로 취소돼요</p>
      )}
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={voice.cancel} className={cn('press flex-1 rounded-[12px] bg-fill font-semibold text-ink', big ? 'min-h-14 text-lg' : 'min-h-11')}>취소</button>
        <button type="button" onClick={voice.confirm} className={cn('press flex-1 rounded-[12px] bg-brand font-semibold text-white', big ? 'min-h-14 text-lg' : 'min-h-11')}>실행</button>
      </div>
    </div>
  )
}
