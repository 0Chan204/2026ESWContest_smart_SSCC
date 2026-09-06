import { Activity, Home, User } from 'lucide-react'
import { usePreferences } from '@/store/PreferencesContext'
import type { Mode } from '@/types'

/**
 * 최초 진입 시 딱 한 번만 노출된다.
 * 선택 결과는 localStorage 에 저장되며, 이후에는 설정에서만 변경한다.
 */
export function ModeSelect() {
  const { t, setMode } = usePreferences()

  const cards: {
    mode: Mode
    Icon: typeof User
    iconWrap: string
    icon: string
    tagWrap: string
    tag: string
    button: string
    tagKey: 'onboarding.elderly.tag' | 'onboarding.normal.tag'
    titleKey: 'onboarding.elderly.title' | 'onboarding.normal.title'
    descKey: 'onboarding.elderly.desc' | 'onboarding.normal.desc'
    hoverBorder: string
  }[] = [
    {
      mode: 'elderly', Icon: User,
      iconWrap: 'bg-amber-50 group-hover:bg-amber-100', icon: 'text-amber-600',
      tagWrap: 'bg-amber-50 border-amber-200', tag: 'text-amber-700',
      button: 'bg-amber-500 hover:bg-amber-600',
      tagKey: 'onboarding.elderly.tag', titleKey: 'onboarding.elderly.title',
      descKey: 'onboarding.elderly.desc', hoverBorder: 'hover:border-amber-400',
    },
    {
      mode: 'normal', Icon: Activity,
      iconWrap: 'bg-blue-50 group-hover:bg-blue-100', icon: 'text-brand',
      tagWrap: 'bg-blue-50 border-blue-200', tag: 'text-blue-700',
      button: 'bg-brand hover:bg-brand-dark',
      tagKey: 'onboarding.normal.tag', titleKey: 'onboarding.normal.title',
      descKey: 'onboarding.normal.desc', hoverBorder: 'hover:border-brand',
    },
  ]

  return (
    <main className="flex h-dvh flex-col items-center justify-center overflow-y-auto p-8">
      <div className="mb-10 flex items-center gap-2.5">
        <span className="bg-brand flex h-9 w-9 items-center justify-center rounded-xl">
          <Home className="h-4.5 w-4.5 text-white" aria-hidden="true" />
        </span>
        <span className="text-brand text-2xl font-bold tracking-tight">HomeVIS</span>
      </div>

      <h1 className="mb-2 text-center text-3xl font-bold text-gray-900">{t('onboarding.title')}</h1>
      <p className="mb-10 text-center text-gray-500">{t('onboarding.subtitle')}</p>

      <div className="grid w-full max-w-[760px] grid-cols-2 gap-5">
        {cards.map((card) => (
          <button
            key={card.mode}
            type="button"
            onClick={() => setMode(card.mode)}
            className={`group rounded-2xl border border-gray-200 bg-white p-8 text-left shadow-sm transition-all hover:shadow-md ${card.hoverBorder}`}
          >
            <span className={`mb-5 flex h-16 w-16 items-center justify-center rounded-2xl transition-colors ${card.iconWrap}`}>
              <card.Icon className={`h-8 w-8 ${card.icon}`} aria-hidden="true" />
            </span>
            <span className={`mb-2 inline-flex items-center rounded-md border px-2 py-0.5 ${card.tagWrap}`}>
              <span className={`text-xs font-semibold ${card.tag}`}>{t(card.tagKey)}</span>
            </span>
            <span className="mt-2 mb-1 block text-xl font-bold text-gray-900">{t(card.titleKey)}</span>
            <span className="mb-7 block text-sm text-gray-500">{t(card.descKey)}</span>
            <span className={`block w-full rounded-xl py-4 text-center font-semibold text-white transition-colors ${card.button}`}>
              {t('onboarding.select')}
            </span>
          </button>
        ))}
      </div>

      <p className="mt-8 text-sm text-gray-400">{t('onboarding.footer')}</p>
    </main>
  )
}
