import { Sheet } from '@/components/ui/Sheet'
import { HomeMapControls } from './HomeMap'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { LOCATION_LABEL } from '@/lib/labels'
import { formatAgo, formatDuration } from '@/lib/format'
import type { Presence } from '@/types'
import { cn } from '@/lib/cn'

const ZONE_LABEL = { kitchen: '주방 안', near: '주방 근처', far: '멀리', unknown: '확인 중' } as const

function presenceValue(p: Presence | undefined) {
  if (!p) return '확인 중'
  return p.present ? `사람 있음 · ${Math.round(p.confidence * 100)}%` : `비어 있음${p.absentSec > 0 ? ` · ${formatDuration(p.absentSec)}` : ''}`
}

/**
 * 위치 크게 보기 — 홈의 '지금 위치' 칸에서 연다.
 * 큰 평면도에서 방마다 조명 밝기·환풍기를 바로 조작하고, 아래 한 줄에 재실 판단을 보여준다.
 */
export function LocationSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { location, presence } = useHome()
  const { elderly } = usePreferences()
  useNow(5_000)   // '○초 전' 갱신
  if (!open) return null
  const k = presence.kitchen
  const last = [presence.kitchen?.observedAt, presence.bathroom?.observedAt].filter(Boolean).sort().at(-1)
  const facts = [
    { k: '주방', v: presenceValue(k) },
    ...(!elderly && k && !k.present ? [{ k: '주방과의 거리', v: ZONE_LABEL[k.zone] }] : []),
    { k: '욕실', v: presenceValue(presence.bathroom) },
    ...(last ? [{ k: '마지막 확인', v: formatAgo(last) }] : []),
  ]

  return (
    <Sheet open onClose={onClose} width={elderly ? 980 : 960} title="지금 위치"
      subtitle={location === 'outside' ? '집 밖' : location === 'unknown' ? '센서 신호가 약해 확인 중' : `${LOCATION_LABEL[location]}에 계세요`}>
      <HomeMapControls />
      <section aria-label="재실 판단" className="mt-4 short:mt-3">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl bg-surface px-4 py-3 md:grid-flow-col md:auto-cols-fr md:grid-cols-none short:py-2.5">
          {facts.map((f) => (
            <div key={f.k} className="min-w-0">
              <dt className={cn('text-ink-3', elderly ? 'text-[1rem]' : 'text-[0.8125rem]')}>{f.k}</dt>
              <dd className={cn('truncate font-medium text-ink', elderly ? 'text-[1.25rem]' : 'text-[1rem]')}>{f.v}</dd>
            </div>
          ))}
        </dl>
        <p className={cn('mt-1.5 px-4 text-[0.8125rem] text-ink-3', elderly && 'short:hidden')}>각 공간의 Wi-Fi 신호로 판단해요. 카메라는 쓰지 않아요.</p>
      </section>
    </Sheet>
  )
}
