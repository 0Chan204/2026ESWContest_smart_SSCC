import { Check, LayoutGrid, Type } from 'lucide-react'
import { usePreferences } from '@/store/PreferencesContext'
import type { Mode } from '@/types'

/** 최초 1회 화면 모드 선택. 선택은 저장되고 이후에는 설정에서만 바꾼다. */
export function ModeSelect() {
  const { setMode } = usePreferences()
  const options: { mode: Mode; Icon: typeof Type; title: string; desc: string; points: string[] }[] = [
    { mode: 'elderly', Icon: Type, title: '크게 보기', desc: '어르신께 추천해요',
      points: ['글자와 버튼을 크게', '꼭 필요한 정보만', '쉬운 말로 안내'] },
    { mode: 'normal', Icon: LayoutGrid, title: '기본 보기', desc: '자세히 보고 싶을 때',
      points: ['온도·기록까지 한눈에', '판단 근거와 정확도 표시', '안전 정책 설정'] },
  ]
  return (
    <main className="flex h-dvh flex-col items-center justify-center bg-canvas px-10">
      <p className="text-[0.9375rem] font-semibold text-ink-3">HomeVIS</p>
      <h1 className="mt-2 text-[2.125rem] font-bold tracking-tight text-ink">어떤 화면이 편하세요?</h1>
      <p className="mt-2 text-lg text-ink-2">나중에 설정에서 언제든 바꿀 수 있어요.</p>
      <div className="mt-10 grid w-full max-w-[820px] grid-cols-2 gap-5">
        {options.map(({ mode, Icon, title, desc, points }) => (
          <button key={mode} type="button" onClick={() => setMode(mode)}
            className="group flex flex-col rounded-3xl bg-surface p-8 text-left transition-shadow hover:shadow-[0_6px_24px_rgba(0,0,0,0.08)]">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sunken group-hover:bg-brand-soft">
              <Icon className="h-7 w-7 text-ink-2 group-hover:text-brand" aria-hidden="true" />
            </span>
            <span className="mt-6 text-[1.625rem] font-bold text-ink">{title}</span>
            <span className="mt-1 text-[1rem] text-ink-2">{desc}</span>
            <ul className="mt-5 space-y-2">
              {points.map((p) => (
                <li key={p} className="flex items-center gap-2 text-[1rem] text-ink">
                  <Check className="h-4 w-4 text-ok" aria-hidden="true" />{p}
                </li>
              ))}
            </ul>
            <span className="mt-8 flex min-h-14 items-center justify-center rounded-2xl bg-ink text-lg font-semibold text-white group-hover:bg-brand">
              이 화면으로 시작
            </span>
          </button>
        ))}
      </div>
    </main>
  )
}
