import { Sheet } from '@/components/ui/Sheet'
import { ListGroup, ListRow } from '@/components/ui/List'
import { HomeMap } from './HomeMap'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { LOCATION_LABEL } from '@/lib/labels'
import { formatAgo, formatDuration } from '@/lib/format'
import type { Presence } from '@/types'

const ZONE_LABEL = { kitchen: '주방 안', near: '주방 근처', far: '멀리', unknown: '확인 중' } as const

function presenceValue(p: Presence | undefined) {
  if (!p) return '확인 중'
  return p.present ? `사람 있음 · ${Math.round(p.confidence * 100)}%` : `비어 있음${p.absentSec > 0 ? ` · ${formatDuration(p.absentSec)}` : ''}`
}

/** 위치 크게 보기 — 홈의 위치 칸을 누르면 열린다 */
export function LocationSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { location, presence } = useHome()
  const { elderly } = usePreferences()
  useNow(5_000)   // '○초 전' 갱신
  if (!open) return null
  const k = presence.kitchen
  const last = [presence.kitchen?.observedAt, presence.bathroom?.observedAt].filter(Boolean).sort().at(-1)

  return (
    <Sheet open onClose={onClose} width={elderly ? 860 : 760} title="지금 위치"
      subtitle={location === 'outside' ? '집 밖' : location === 'unknown' ? '센서 신호가 약해 확인 중' : `${LOCATION_LABEL[location]}에 계세요`}>
      <HomeMap big className="h-[300px] max-h-[44dvh] md:h-[340px]" />
      <ListGroup className="mt-6" footer="각 공간의 Wi-Fi 신호로 사람이 있는지 판단해요. 카메라는 쓰지 않아요.">
        <ListRow big={elderly} title="현재 위치" value={<span className="font-semibold text-brand-ink">{LOCATION_LABEL[location]}</span>} />
        <ListRow big={elderly} title="주방" value={presenceValue(k)} />
        {!elderly && k && !k.present && <ListRow title="주방과의 거리" value={ZONE_LABEL[k.zone]} />}
        <ListRow big={elderly} title="욕실" value={presenceValue(presence.bathroom)} />
        {last && <ListRow big={elderly} title="마지막 확인" value={formatAgo(last)} />}
      </ListGroup>
    </Sheet>
  )
}
