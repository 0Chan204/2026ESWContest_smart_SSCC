import {
  FONT_SCALE_MAX, FONT_SCALE_MIN, FONT_SCALE_STEP, usePreferences,
} from '@/store/PreferencesContext'
import { cn } from '@/lib/cn'

/**
 * 어르신 모드 글자 크기 조절.
 * A- / A+ 버튼과 슬라이더 둘 다 제공한다. (터치 환경에서 슬라이더만으로는 미세 조절이 어렵다)
 */
export function FontScaleControl({ compact }: { compact?: boolean }) {
  const { fontScale, setFontScale, t } = usePreferences()

  const btn = cn(
    'flex items-center justify-center rounded-lg font-bold transition-colors',
    compact
      ? 'h-11 w-11 text-sm text-gray-600 hover:bg-gray-200'
      : 'h-11 w-11 border border-gray-200 bg-white text-sm text-gray-700 hover:border-blue-300',
  )

  return (
    <div className={cn('flex items-center gap-2', compact ? 'rounded-xl bg-gray-100 px-2 py-1' : 'gap-3')}>
      <button
        type="button"
        onClick={() => setFontScale(fontScale - FONT_SCALE_STEP)}
        disabled={fontScale <= FONT_SCALE_MIN}
        aria-label="글자 크기 줄이기"
        className={cn(btn, 'disabled:opacity-40')}
      >
        A-
      </button>
      <input
        type="range"
        min={FONT_SCALE_MIN}
        max={FONT_SCALE_MAX}
        step={FONT_SCALE_STEP}
        value={fontScale}
        onChange={(e) => setFontScale(Number(e.target.value))}
        aria-label={t('settings.fontSize')}
        aria-valuetext={`${fontScale}%`}
        className={cn('h-2 cursor-pointer rounded-full', compact ? 'w-24' : 'flex-1')}
      />
      <button
        type="button"
        onClick={() => setFontScale(fontScale + FONT_SCALE_STEP)}
        disabled={fontScale >= FONT_SCALE_MAX}
        aria-label="글자 크기 키우기"
        className={cn(btn, 'disabled:opacity-40')}
      >
        A+
      </button>
      {compact && <span className="tabular w-10 text-center text-xs text-gray-500">{fontScale}%</span>}
    </div>
  )
}
