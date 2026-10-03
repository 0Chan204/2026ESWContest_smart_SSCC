import { Mic, X } from 'lucide-react'
import { EXAMPLE_COMMANDS } from './commands'
import type { VoiceController } from './useVoice'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

const LABEL = {
  idle: '무엇을 도와드릴까요?', listening: '듣고 있어요', recognized: '알아들었어요',
  processing: '확인하고 있어요', completed: '완료', error: '잘 듣지 못했어요. 다시 말씀해 주세요.',
} as const

/** 레일의 마이크 버튼 옆에 뜨는 음성 패널 */
export function VoicePanel({ voice }: { voice: VoiceController }) {
  const { elderly } = usePreferences()
  const { state, heard, reply, pending, demo } = voice
  const big = elderly
  return (
    <div role="dialog" aria-modal="false" aria-label="음성 명령"
      className={cn('fixed bottom-5 z-40 overflow-hidden rounded-3xl bg-surface shadow-[0_12px_40px_rgba(0,0,0,0.18)]',
        elderly ? 'left-[140px] w-[420px]' : 'left-[116px] w-[360px]')}>
      <div className="flex items-center justify-between px-5 pt-4">
        <span className="flex items-center gap-2 text-[0.8125rem] font-semibold text-ink-3">
          음성 명령{demo && <span className="rounded-md bg-muted-soft px-1.5 py-0.5 text-[0.6875rem]">예시 재생</span>}
        </span>
        <button type="button" onClick={voice.close} aria-label="닫기" className="-mr-2 flex h-10 w-10 items-center justify-center rounded-full text-ink-3 hover:bg-sunken">
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      <div className="px-5 pb-5">
        <div className="flex items-center gap-4">
          <span className={cn('relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full',
            state === 'error' ? 'bg-danger-soft' : state === 'completed' ? 'bg-ok-soft' : 'bg-brand-soft')}>
            {state === 'listening' && <span className="absolute inset-0 animate-ping rounded-full bg-brand/20" aria-hidden="true" />}
            <Mic className={cn('h-6 w-6', state === 'error' ? 'text-danger' : state === 'completed' ? 'text-ok' : 'text-brand')} aria-hidden="true" />
          </span>
          <div aria-live="polite" className="min-w-0">
            {heard && <p className={cn('font-semibold text-ink', big ? 'text-xl' : 'text-[1.0625rem]')}>“{heard}”</p>}
            <p className={cn(state === 'completed' ? 'text-ink' : 'text-ink-2', big ? 'text-lg' : 'text-[0.9375rem]')}>
              {state === 'completed' ? reply : LABEL[state]}
            </p>
          </div>
        </div>

        {pending && (
          <div className="mt-4">
            <p className={cn('mb-3 font-semibold text-ink', big ? 'text-xl' : 'text-base')}>{pending.message}</p>
            <div className="flex gap-2">
              <button type="button" onClick={voice.close} className={cn('flex-1 rounded-xl bg-sunken font-semibold text-ink', big ? 'min-h-14 text-lg' : 'min-h-11')}>취소</button>
              <button type="button" onClick={voice.confirm} className={cn('flex-1 rounded-xl bg-brand font-semibold text-white', big ? 'min-h-14 text-lg' : 'min-h-11')}>실행</button>
            </div>
          </div>
        )}

        {state === 'listening' && (
          <ul className="mt-4 flex flex-wrap gap-1.5">
            {EXAMPLE_COMMANDS.map((c) => <li key={c} className="rounded-full bg-sunken px-3 py-1.5 text-[0.8125rem] text-ink-2">{c}</li>)}
          </ul>
        )}
      </div>
    </div>
  )
}
