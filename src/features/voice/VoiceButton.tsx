import { Mic } from 'lucide-react'
import { usePreferences } from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

/**
 * 좌측 하단 플로팅 음성 버튼.
 * 모든 화면에서 동일한 위치에 노출되고, 화면 모서리에서 24px 이상 떨어져 있다.
 */
export function VoiceButton({ onStart, active }: { onStart: () => void; active: boolean }) {
  const { t, elderly } = usePreferences()
  return (
    <button
      type="button"
      onClick={onStart}
      title={t('voice.button')}
      aria-label={t('voice.button')}
      aria-expanded={active}
      className={cn(
        'bg-brand hover:bg-brand-dark fixed bottom-6 left-6 z-40 flex items-center justify-center rounded-2xl text-white shadow-lg transition-all active:scale-95',
        elderly ? 'h-18 w-18 flex-col gap-1' : 'h-14 w-14',
      )}
    >
      <Mic className={elderly ? 'h-7 w-7' : 'h-5 w-5'} aria-hidden="true" />
      {elderly && <span className="text-xs leading-none font-bold">{t('voice.buttonElderly')}</span>}
    </button>
  )
}
