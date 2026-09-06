import { X } from 'lucide-react'
import { Drawer } from '@/components/Drawer'
import { FontScaleControl } from './FontScaleControl'
import { usePreferences } from '@/store/PreferencesContext'
import type { Language, Mode } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 설정 드로어.
 * 설정 아이콘은 절대 모드 선택 화면으로 되돌아가지 않는다. 여기서 모두 처리한다.
 */
export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const {
    t, mode, elderly, language, setMode, setLanguage, fontScale, voiceEnabled, setVoiceEnabled,
  } = usePreferences()

  const modes: [Mode, string][] = [
    ['normal', t('settings.mode.normal')],
    ['elderly', t('settings.mode.elderly')],
  ]
  const languages: [Language, string][] = [
    ['ko', '한국어'],
    ['en', 'English'],
  ]

  return (
    <Drawer open={open} onClose={onClose} labelledBy="settings-title">
      <header className="flex items-center justify-between border-b border-gray-100 px-6 py-5">
        <h2 id="settings-title" className="text-lg font-bold text-gray-900">
          {t('settings.title')}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('settings.close')}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <div className="flex-1 space-y-7 overflow-y-auto px-6 py-5">
        <section>
          <h3 className="mb-3 text-xs font-semibold tracking-wider text-gray-500 uppercase">
            {t('settings.mode')}
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {modes.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                aria-pressed={mode === value}
                className={cn(
                  'min-h-14 rounded-xl border-2 text-sm font-semibold transition-all',
                  mode === value
                    ? 'bg-brand border-brand text-white'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-blue-200',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </section>

        <section className={cn(!elderly && 'pointer-events-none opacity-40')} aria-disabled={!elderly}>
          <h3 className="mb-3 text-xs font-semibold tracking-wider text-gray-500 uppercase">
            {t('settings.fontSize')}
          </h3>
          <div className="rounded-xl bg-gray-50 p-4">
            <FontScaleControl />
            <p className="mt-3 text-center text-sm text-gray-600">
              {t('settings.fontSize.current')} <span className="text-brand font-bold">{fontScale}%</span>
            </p>
          </div>
          {!elderly && (
            <p className="mt-2 text-xs text-gray-500">{t('settings.fontSize.elderlyOnly')}</p>
          )}
        </section>

        <section>
          <h3 className="mb-3 text-xs font-semibold tracking-wider text-gray-500 uppercase">
            {t('settings.voice')}
          </h3>
          <label className="flex min-h-14 cursor-pointer items-center justify-between gap-3 rounded-xl bg-gray-50 px-4">
            <span className="text-sm font-medium text-gray-800">{t('settings.voice.enable')}</span>
            <input
              type="checkbox"
              checked={voiceEnabled}
              onChange={(e) => setVoiceEnabled(e.target.checked)}
              className="accent-brand h-6 w-6 cursor-pointer"
            />
          </label>
          {/* 개인정보 고지: 브라우저 음성 인식은 외부 서버로 음성이 전송될 수 있다 */}
          <p className="mt-2 text-xs leading-relaxed break-keep text-gray-500">
            {t('settings.voice.notice')}
          </p>
          {!voiceEnabled && <p className="mt-1 text-xs text-gray-400">{t('settings.voice.off')}</p>}
        </section>

        <section>
          <h3 className="mb-3 text-xs font-semibold tracking-wider text-gray-500 uppercase">
            {t('settings.language')}
          </h3>
          <div className="grid grid-cols-2 gap-1 rounded-xl bg-gray-50 p-1">
            {languages.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setLanguage(value)}
                aria-pressed={language === value}
                className={cn(
                  'min-h-12 rounded-lg text-sm font-medium transition-all',
                  language === value
                    ? 'text-brand bg-white shadow-sm'
                    : 'text-gray-600 hover:text-gray-800',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </section>
      </div>

      <footer className="border-t border-gray-100 px-6 py-5">
        <p className="text-center text-xs text-gray-500">{t('settings.footer')}</p>
      </footer>
    </Drawer>
  )
}
