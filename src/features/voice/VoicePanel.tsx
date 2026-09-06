import { Mic, Volume2, X } from 'lucide-react'
import { EXAMPLE_COMMANDS } from './commands'
import type { VoiceController, VoiceState } from './useVoice'
import { usePreferences } from '@/store/PreferencesContext'
import type { TKey } from '@/i18n'
import { cn } from '@/lib/cn'

const STATE_LABEL: Record<VoiceState, TKey> = {
  idle: 'voice.state.idle',
  listening: 'voice.state.listening',
  recognized: 'voice.state.recognized',
  processing: 'voice.state.processing',
  completed: 'voice.state.completed',
  error: 'voice.state.error',
}

const STATE_COLOR: Record<VoiceState, string> = {
  idle: 'text-gray-500',
  listening: 'text-brand',
  recognized: 'text-emerald-600',
  processing: 'text-amber-600',
  completed: 'text-emerald-700',
  error: 'text-red-600',
}

export function VoicePanel({ voice }: { voice: VoiceController }) {
  const { t } = usePreferences()
  const { state, demo, recognized, reply, pending } = voice

  const description =
    state === 'listening' ? t('voice.listening')
      : state === 'recognized' ? `"${recognized}"`
        : state === 'processing' ? t('voice.processing')
          : state === 'completed' ? reply
            : state === 'error' ? t('voice.error')
              : t('voice.idle')

  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-label={t('voice.title')}
      className="fixed bottom-26 left-6 z-50 w-[300px] max-w-[calc(100vw-48px)] overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl"
    >
      <header className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Volume2 className="text-brand h-4 w-4" aria-hidden="true" />
          <span className="text-sm font-semibold text-gray-700">{t('voice.title')}</span>
          {demo && (
            <span className="rounded-md border border-gray-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-gray-500">
              {t('voice.demoBadge')}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={voice.close}
          aria-label={t('common.close')}
          className="flex h-8 w-8 items-center justify-center rounded text-gray-400 transition-colors hover:text-gray-600"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </header>

      <div className="px-4 py-4">
        <div className="mb-4 flex justify-center">
          <span
            className={cn(
              'relative flex h-14 w-14 items-center justify-center rounded-full',
              state === 'listening' ? 'bg-blue-50'
                : state === 'completed' ? 'bg-emerald-50'
                  : state === 'error' ? 'bg-red-50' : 'bg-gray-50',
            )}
          >
            {state === 'listening' && (
              <span className="absolute inset-0 animate-ping rounded-full bg-blue-200 opacity-40" aria-hidden="true" />
            )}
            <Mic className={cn('h-6 w-6', STATE_COLOR[state])} aria-hidden="true" />
          </span>
        </div>

        <p aria-live="polite" className={cn('mb-1 text-center text-sm font-medium break-keep', STATE_COLOR[state])}>
          {description}
        </p>
        <p className="text-center text-xs text-gray-400">{t(STATE_LABEL[state])}</p>

        {pending && (
          <div className="mt-4 border-t border-gray-100 pt-4">
            <p className="mb-3 text-center text-sm font-medium break-keep text-gray-800">{pending.message}</p>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={voice.cancelConfirm}
                className="min-h-11 rounded-xl border border-gray-300 text-sm text-gray-700 transition-colors hover:bg-gray-50"
              >
                {t('voice.cancel')}
              </button>
              <button
                type="button"
                onClick={voice.confirm}
                className="bg-brand hover:bg-brand-dark min-h-11 rounded-xl text-sm font-semibold text-white transition-colors"
              >
                {t('voice.run')}
              </button>
            </div>
          </div>
        )}

        {state === 'listening' && !pending && (
          <div className="mt-3 border-t border-gray-100 pt-3">
            <p className="mb-1.5 text-xs text-gray-500">{t('voice.examples')}</p>
            <ul className="space-y-1">
              {EXAMPLE_COMMANDS.map((cmd) => (
                <li key={cmd} className="rounded-lg bg-gray-50 px-2.5 py-1 text-xs text-gray-600">
                  {cmd}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
