import { useEffect, useState, type ReactNode } from 'react'
import { User } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Sparkline } from '@/components/ui/Sparkline'
import { RoomControls } from './RoomControls'
import { RISK_BG, RISK_INK, useRooms } from './rooms'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { useNow } from '@/hooks/useNow'
import { LOCATION_LABEL, ROOM_LABEL } from '@/lib/labels'
import { formatAgo } from '@/lib/format'
import { NODE_STATUS_LABEL, SENSING_WINDOW_MS, isFresh, roomPresence, roomSeries, rssiBars } from '@/lib/sensing'
import type { HouseRoom, SensingNode, SensingSample } from '@/types'
import { cn } from '@/lib/cn'

const NODE_POLL_MS = 2500

/** 방금 · n초 전 (1분이 넘으면 n분 전) */
function ago(iso: string, now: number): string {
  const sec = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  return sec < 2 ? '방금' : sec < 60 ? `${sec}초 전` : formatAgo(iso, now)
}

/**
 * 위치 크게 보기 = 재실 감지 화면 — 홈의 '지금 위치' 칸에서 연다.
 * 공간마다 한 칸: 재실 판단(신뢰도 · 행동 · 최근 1분 그래프 · 센서 노드 신호) + 그 공간의 조명 · 환풍기 · 공기청정기.
 * 재실 판단 결과는 사람이 있는 공간 하나만 알려주므로, 신뢰도 숫자는 그 공간에만 보여준다.
 */
export function LocationSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return <LocationSheetBody onClose={onClose} />
}

function LocationSheetBody({ onClose }: { onClose: () => void }) {
  const { location, latestSensing, sensing, source } = useHome()
  const { elderly } = usePreferences()
  const { rooms } = useRooms()
  const now = useNow(1000)
  const [nodes, setNodes] = useState<SensingNode[] | null>(null)

  // 센서 노드 신호는 열려 있는 동안만 몇 초마다 묻는다
  useEffect(() => {
    if (elderly) return
    let alive = true
    const load = () => source.loadSensingNodes().then((n) => { if (alive) setNodes(n) }).catch(() => { if (alive) setNodes([]) })
    load()
    const t = setInterval(load, NODE_POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [source, elderly])

  const live = isFresh(latestSensing, now)
  const where = location === 'outside' ? '집 밖에 계세요' : location === 'unknown' ? '위치 확인 중' : `${LOCATION_LABEL[location]}에 계세요`

  return (
    <Sheet open onClose={onClose} width={elderly ? 980 : 1000} title="지금 위치"
      subtitle={(
        <span className="flex flex-wrap items-center gap-x-2">
          <span>{where}</span>
          <span aria-hidden="true" className="text-ink-3">·</span>
          {latestSensing ? (
            <span className={cn('flex items-center gap-1.5', live ? 'text-ok' : 'text-warn')}>
              <span className={cn('h-2 w-2 rounded-full', live ? 'bg-ok' : 'bg-warn')} aria-hidden="true" />
              {live ? '실시간' : '갱신 멈춤'}
              <span className="tabular text-ink-3">{ago(latestSensing.at, now)}</span>
            </span>
          ) : <span className="text-ink-3">재실 판단 결과 없음</span>}
        </span>
      )}>
      <div className="grid grid-cols-1 gap-[2px] overflow-hidden rounded-xl bg-line p-[2px] lg:grid-cols-3">
        {rooms.map((r) => (
          <RoomColumn key={r.id} room={r.id} here={r.here} riskBg={RISK_BG[r.risk]} riskInk={RISK_INK[r.risk]}
            latest={latestSensing} history={sensing} now={now} node={nodes?.find((n) => n.room === r.id) ?? (nodes ? null : undefined)}
            controls={<RoomControls lights={r.lights} fans={r.fans} airs={r.airs} />} />
        ))}
      </div>
      <p className={cn('mt-2 px-4 text-[0.8125rem] text-ink-3', elderly && 'short:hidden')}>각 공간의 Wi-Fi 신호로 판단해요. 카메라는 쓰지 않아요.</p>
    </Sheet>
  )
}

function RoomColumn({ room, here, riskBg, riskInk, latest, history, now, node, controls }: {
  room: HouseRoom
  here: boolean
  riskBg?: string
  riskInk?: string
  latest: SensingSample | null
  history: SensingSample[]
  now: number
  /** undefined = 아직 불러오는 중, null = 정보 없음 */
  node: SensingNode | null | undefined
  controls: ReactNode
}) {
  const { elderly } = usePreferences()
  const p = roomPresence(latest, room, now)
  const live = p.freshness === 'live'
  const series = roomSeries(history, room, now)
  // 비어 있으면 최근 1분 안에 마지막으로 있었던 때
  const lastSeen = [...history].reverse().find((s) => s.present && s.room === room && now - new Date(s.at).getTime() <= SENSING_WINDOW_MS)

  const big = !latest ? '결과 없음' : !live ? '확인 중' : p.present ? (p.percent !== null ? `${p.percent}%` : '있음') : '비어 있음'
  const numeric = live && p.present && p.percent !== null
  const line = !latest ? '재실 판단을 기다리는 중'
    : !live ? `${ago(latest.at, now)} 결과`
    : p.present ? ['사람 있음', p.activity].filter(Boolean).join(' · ')
    : lastSeen ? `${ago(lastSeen.at, now)}까지 있었어요` : '최근 1분 감지 없음'

  return (
    <section aria-label={ROOM_LABEL[room]}
      className={cn('flex min-w-0 flex-col gap-3 p-4 md:max-lg:grid md:max-lg:grid-cols-2 md:max-lg:gap-5', elderly && 'short:gap-2 short:p-3',
        riskBg ?? (here ? 'bg-brand-soft' : 'bg-surface'))}>
      <div className="flex min-w-0 flex-col">
        <div className="flex min-h-10 items-center justify-between gap-3">
          <h3 className={cn('font-semibold', elderly ? 'text-[1.375rem]' : 'text-[1.0625rem]', riskInk ?? (here ? 'text-brand-ink' : 'text-ink-2'))}>{ROOM_LABEL[room]}</h3>
          {here && (
            <span className="locate relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand text-brand" role="img" aria-label="지금 여기 계세요">
              <span className="relative flex"><User className="h-5 w-5 text-white" aria-hidden="true" /></span>
            </span>
          )}
        </div>

        <p className={cn('mt-1 flex items-end', elderly ? 'h-12' : 'h-14')}
          aria-label={numeric ? `재실 신뢰도 ${p.percent}%` : undefined}>
          <span className={cn('tabular leading-none',
            numeric ? cn('font-light tracking-[-0.03em]', elderly ? 'text-[2.75rem]' : 'text-[3.25rem]')
              : cn('font-semibold', elderly ? 'text-[1.75rem]' : 'text-[1.625rem]'),
            p.present && live ? (riskInk ?? 'text-ink') : 'text-ink-3')}>{big}</span>
        </p>
        <p className={cn('mt-1.5 truncate', elderly ? 'text-[1.125rem]' : 'text-[0.9375rem]', p.present && live ? 'font-medium text-ink' : 'text-ink-2')}>{line}</p>

        {!elderly && (
          <>
            <div className="mt-3 h-11" title="최근 1분 재실 신뢰도">
              <Sparkline values={series.length > 0 ? series : [0, 0]} min={0} max={100} height={44}
                color={riskInk ? 'var(--color-danger)' : series.some((v) => v > 0) ? 'var(--color-brand-ink)' : 'var(--color-ink-3)'}
                label={`${ROOM_LABEL[room]} 최근 1분 재실 신뢰도`} />
            </div>
            <NodeLine node={node} />
          </>
        )}
      </div>
      <div className="mt-auto">{controls}</div>
    </section>
  )
}

/** 센서 노드 한 줄: 이름 · 신호 막대 · dBm · Hz · 상태 */
function NodeLine({ node }: { node: SensingNode | null | undefined }) {
  if (node === undefined) return <p className="mt-2 text-[0.8125rem] text-ink-3">센서 신호 확인 중</p>
  if (node === null) return <p className="mt-2 text-[0.8125rem] text-ink-3">센서 정보 없음</p>
  const ok = node.status === 'ok'
  const bars = rssiBars(node.rssi)
  return (
    <p className="mt-2 flex min-w-0 items-center gap-2 text-[0.8125rem]">
      <span className="font-semibold text-ink-2 uppercase">{node.node}</span>
      {ok && (
        <>
          <span className="flex h-3 items-end gap-[2px]" role="img" aria-label={`신호 ${bars}단계`}>
            {[1, 2, 3, 4].map((i) => (
              <span key={i} className={cn('w-[3px] rounded-[1px]', i <= bars ? 'bg-ink-2' : 'bg-track')} style={{ height: `${i * 25}%` }} />
            ))}
          </span>
          <span className="tabular min-w-0 truncate text-ink-2">
            {node.rssi !== undefined ? `${Math.round(node.rssi)} dBm` : '–'} · {node.rateHz !== undefined ? `${node.rateHz.toFixed(1)} Hz` : '–'}
          </span>
        </>
      )}
      <span className={cn('ml-auto shrink-0 font-medium', ok ? 'text-ok' : 'text-warn')}>{NODE_STATUS_LABEL[node.status]}</span>
    </p>
  )
}
