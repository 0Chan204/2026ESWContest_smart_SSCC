import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { createTranslate, type Translate } from '@/i18n'
import { readBool, readEnum, readInt, write } from '@/lib/storage'
import type { Language, Mode } from '@/types'

export const FONT_SCALE_MIN = 100
export const FONT_SCALE_MAX = 130
export const FONT_SCALE_STEP = 5
export const FONT_SCALE_DEFAULT = 115

const MODES: readonly Mode[] = ['normal', 'elderly']
const LANGS: readonly Language[] = ['ko', 'en']

interface PreferencesValue {
  /** null 이면 아직 최초 모드 선택을 하지 않은 상태 */
  mode: Mode | null
  elderly: boolean
  fontScale: number
  language: Language
  voiceEnabled: boolean
  t: Translate
  setMode: (mode: Mode) => void
  setFontScale: (scale: number) => void
  setLanguage: (language: Language) => void
  setVoiceEnabled: (enabled: boolean) => void
}

const PreferencesContext = createContext<PreferencesValue | null>(null)

function clampScale(value: number): number {
  if (!Number.isFinite(value)) return FONT_SCALE_DEFAULT
  return Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, Math.round(value)))
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  // 저장된 값은 항상 검증해서 읽는다. 조작된 값이 들어와도 기본값으로 안전하게 폴백한다.
  const [mode, setModeState] = useState<Mode | null>(() => {
    const stored = readEnum<Mode | 'none'>('mode', [...MODES, 'none'] as const, 'none')
    return stored === 'none' ? null : stored
  })
  const [fontScale, setFontScaleState] = useState(() =>
    readInt('fontscale', FONT_SCALE_MIN, FONT_SCALE_MAX, FONT_SCALE_DEFAULT),
  )
  const [language, setLanguageState] = useState<Language>(() =>
    readEnum<Language>('language', LANGS, 'ko'),
  )
  // 음성 인식은 개인정보 관점에서 기본 꺼짐. 사용자가 명시적으로 켜야 한다.
  const [voiceEnabled, setVoiceEnabledState] = useState(() => readBool('voice', false))

  // 어르신 모드에서만 루트 폰트 크기를 키운다.
  // --spacing 이 px 로 고정되어 있어 여백·아이콘·그리드는 그대로 유지된다.
  useEffect(() => {
    const root = document.documentElement
    root.style.setProperty(
      '--font-size-base',
      mode === 'elderly' ? `${(fontScale / 100) * 16}px` : '16px',
    )
    root.style.setProperty('--nav-h', mode === 'elderly' ? '88px' : '64px')
  }, [mode, fontScale])

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const setMode = useCallback((next: Mode) => {
    setModeState(next)
    write('mode', next)
    write('onboarding_complete', true)
  }, [])

  const setFontScale = useCallback((next: number) => {
    const clamped = clampScale(next)
    setFontScaleState(clamped)
    write('fontscale', clamped)
  }, [])

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next)
    write('language', next)
  }, [])

  const setVoiceEnabled = useCallback((next: boolean) => {
    setVoiceEnabledState(next)
    write('voice', next)
  }, [])

  const t = useMemo(() => createTranslate(language), [language])

  const value = useMemo<PreferencesValue>(
    () => ({
      mode,
      elderly: mode === 'elderly',
      fontScale,
      language,
      voiceEnabled,
      t,
      setMode,
      setFontScale,
      setLanguage,
      setVoiceEnabled,
    }),
    [mode, fontScale, language, voiceEnabled, t, setMode, setFontScale, setLanguage, setVoiceEnabled],
  )

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
}

export function usePreferences(): PreferencesValue {
  const ctx = useContext(PreferencesContext)
  if (!ctx) throw new Error('usePreferences 는 PreferencesProvider 안에서만 사용할 수 있습니다.')
  return ctx
}

/** 번역 함수만 필요할 때 */
export function useT(): Translate {
  return usePreferences().t
}
