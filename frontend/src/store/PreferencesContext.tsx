import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { createTranslate, type Translate } from '@/i18n'
import { readBool, readEnum, readInt, write } from '@/lib/storage'
import type { Language, Mode, Theme } from '@/types'

export const FONT_SCALE_MIN = 100
export const FONT_SCALE_MAX = 130
export const FONT_SCALE_STEP = 5
export const FONT_SCALE_DEFAULT = 115

const MODES: readonly Mode[] = ['normal', 'elderly']
const LANGS: readonly Language[] = ['ko', 'en']
const THEMES: readonly Theme[] = ['dark', 'light', 'system']

interface PreferencesValue {
  /** null 이면 아직 최초 모드 선택을 하지 않은 상태 */
  mode: Mode | null
  elderly: boolean
  fontScale: number
  language: Language
  voiceEnabled: boolean
  /** 호출어 "홈비스"로 부르기 — 켜면 마이크가 계속 켜져 있다. 기본 꺼짐 */
  wakeWordEnabled: boolean
  /** 위험 알림을 소리 내어 읽어줄지 (기기 내장 음성만 사용) */
  ttsEnabled: boolean
  /** 사용자가 고른 테마 (기본: 다크 — 플랫폼 샘플과 같은 어두운 대시보드) */
  theme: Theme
  /** 실제로 그려지는 테마 (system 이면 기기 설정을 따른다) */
  resolvedTheme: 'dark' | 'light'
  /** 첫 실행 권한 동의 창에 답했는지 */
  consentAnswered: boolean
  t: Translate
  setMode: (mode: Mode) => void
  setFontScale: (scale: number) => void
  setLanguage: (language: Language) => void
  setVoiceEnabled: (enabled: boolean) => void
  setWakeWordEnabled: (enabled: boolean) => void
  setTtsEnabled: (enabled: boolean) => void
  setTheme: (theme: Theme) => void
  /** 권한 동의 창 응답. 허용하면 마이크(음성 명령)·음성 안내를 켠다 */
  answerConsent: (granted: boolean) => void
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
  // 호출어 대기는 마이크를 계속 켜 두므로 동의 창에서 '허용'을 눌러도 켜지 않는다. 설정에서 직접 켠다.
  const [wakeWordEnabled, setWakeWordEnabledState] = useState(() => readBool('wakeword', false))
  const [ttsEnabled, setTtsEnabledState] = useState(() => readBool('tts', true))
  const [theme, setThemeState] = useState<Theme>(() => readEnum<Theme>('theme', THEMES, 'light'))
  const [consentAnswered, setConsentAnswered] = useState(() => readBool('consent_answered', false))
  const [systemDark, setSystemDark] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches,
  )

  // '시스템' 테마일 때 기기 설정 변화를 따라간다
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  const resolvedTheme: 'dark' | 'light' = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  // 어르신 모드에서만 루트 폰트 크기를 키운다.
  // --spacing 이 px 로 고정되어 있어 여백·아이콘·그리드는 그대로 유지된다.
  useEffect(() => {
    const root = document.documentElement
    root.style.setProperty(
      '--font-size-base',
      mode === 'elderly' ? `${(fontScale / 100) * 16}px` : '16px',
    )
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

  const setWakeWordEnabled = useCallback((next: boolean) => {
    setWakeWordEnabledState(next)
    write('wakeword', next)
  }, [])

  const setTtsEnabled = useCallback((next: boolean) => {
    setTtsEnabledState(next)
    write('tts', next)
  }, [])

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    write('theme', next)
  }, [])

  const answerConsent = useCallback((granted: boolean) => {
    if (granted) {
      setVoiceEnabledState(true); write('voice', true)
      setTtsEnabledState(true); write('tts', true)
    }
    setConsentAnswered(true)
    write('consent_answered', true)
  }, [])

  const t = useMemo(() => createTranslate(language), [language])

  const value = useMemo<PreferencesValue>(
    () => ({
      mode,
      elderly: mode === 'elderly',
      fontScale,
      language,
      voiceEnabled,
      wakeWordEnabled,
      ttsEnabled,
      theme,
      resolvedTheme,
      consentAnswered,
      t,
      setMode,
      setFontScale,
      setLanguage,
      setVoiceEnabled,
      setWakeWordEnabled,
      setTtsEnabled,
      setTheme,
      answerConsent,
    }),
    [mode, fontScale, language, voiceEnabled, wakeWordEnabled, ttsEnabled, theme, resolvedTheme, consentAnswered, t,
      setMode, setFontScale, setLanguage, setVoiceEnabled, setWakeWordEnabled, setTtsEnabled, setTheme, answerConsent],
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
