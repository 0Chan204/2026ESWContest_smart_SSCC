import { Check } from 'lucide-react'
import { usePreferences } from '@/store/PreferencesContext'
import type { Mode } from '@/types'

/** 최초 1회 화면 모드 선택. 선택은 저장되고 이후에는 설정에서만 바꾼다. */
export function ModeSelect() {
  const { setMode } = usePreferences()
  const options: { mode: Mode; title: string; desc: string; sample: string; points: string[] }[] = [
    { mode: 'elderly', title: '크게 보기', desc: '어르신께 추천', sample: '가',
      points: ['글자와 버튼을 크게', '꼭 필요한 정보만', '쉬운 말로 안내'] },
    { mode: 'normal', title: '기본 보기', desc: '자세히 보고 싶을 때', sample: '가',
      points: ['온도·기록까지 한눈에', '판단 근거와 정확도', '안전 정책 설정'] },
  ]
  return (
    <main className="flex h-dvh flex-col items-center overflow-y-auto bg-canvas px-6 py-10 md:px-10">
      <div className="my-auto flex w-full flex-col items-center">
        <p className="text-[0.9375rem] font-semibold text-ink-3">HomeVIS</p>
        <h1 className="mt-1 text-center text-[2rem] font-bold tracking-[-0.02em] text-ink md:text-[2.5rem]">어떤 화면이 편하세요?</h1>
        <p className="mt-2 text-center text-[1.0625rem] text-ink-2">설정에서 언제든 바꿀 수 있어요.</p>
        <div className="mt-10 grid w-full max-w-[760px] grid-cols-1 gap-4 md:grid-cols-2">
          {options.map(({ mode, title, desc, sample, points }) => (
            <button key={mode} type="button" onClick={() => setMode(mode)}
              className="press flex flex-col rounded-[22px] bg-surface p-7 text-left">
              <span className={mode === 'elderly' ? 'text-[4rem] leading-none font-bold text-ink' : 'text-[2.5rem] leading-none font-bold text-ink'} aria-hidden="true">{sample}</span>
              <span className="mt-6 text-[1.5rem] font-bold text-ink">{title}</span>
              <span className="text-[1rem] text-ink-3">{desc}</span>
              <ul className="mt-5 space-y-2">
                {points.map((p) => (
                  <li key={p} className="flex items-center gap-2 text-[1rem] text-ink-2">
                    <Check className="h-4 w-4 text-brand-ink" strokeWidth={2.6} aria-hidden="true" />{p}
                  </li>
                ))}
              </ul>
              <span className="mt-8 flex min-h-[50px] items-center justify-center rounded-[14px] bg-brand text-[1.0625rem] font-semibold text-white">
                이 화면으로 시작
              </span>
            </button>
          ))}
        </div>
      </div>
    </main>
  )
}
