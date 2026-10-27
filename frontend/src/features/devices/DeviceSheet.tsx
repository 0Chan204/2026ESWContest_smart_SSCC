import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Toggle } from '@/components/ui/Toggle'
import { Segmented } from '@/components/ui/Segmented'
import { BrightnessSlider } from '@/components/ui/BrightnessSlider'
import { Sparkline } from '@/components/ui/Sparkline'
import { Button } from '@/components/ui/Button'
import { ListGroup, ListRow } from '@/components/ui/List'
import { DEVICE_GLYPH } from '@/components/DeviceIcon'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { airAutoReason, lightLevel, savingLevel, summarize } from '@/lib/device'
import { AIR_LEVEL_LABEL, BURNER_LABEL, PUBLISHER_LABEL, ROOM_LABEL } from '@/lib/labels'
import { formatDuration, formatWhen } from '@/lib/format'
import type { Device } from '@/types'
import { cn } from '@/lib/cn'

/** 기기 상세 (오른쪽 패널). iOS 설정처럼 묶음 목록으로 보여준다. */
export function DeviceSheet({ deviceId, onClose }: { deviceId: string | null; onClose: () => void }) {
  const { devices, policy, controlDevice } = useHome()
  const { elderly } = usePreferences()
  const d = devices.find((x) => x.id === deviceId)
  if (!d) return null
  const s = summarize(d)
  const { Icon, on: glyph } = DEVICE_GLYPH[d.kind]
  const active = d.online && s.active
  const big = elderly

  return (
    <Sheet open onClose={onClose} variant="side" width={elderly ? 560 : 460} title={d.name} subtitle={ROOM_LABEL[d.room]}>
      <div className="flex items-center gap-4 rounded-2xl bg-surface p-5">
        <Icon className={cn('h-10 w-10 shrink-0', s.risk === 'danger' ? 'text-danger' : active ? glyph : 'text-ink-3')} strokeWidth={1.6} aria-hidden="true" />
        <div className="min-w-0">
          <p className={cn('font-bold', big ? 'text-3xl' : 'text-[1.5rem]', s.risk === 'danger' ? 'text-danger' : 'text-ink')}>{s.status}</p>
          <p className={cn('text-ink-2', big ? 'text-lg' : 'text-[0.9375rem]')}>{s.detail}</p>
        </div>
      </div>

      {!d.online && <Reconnect device={d} big={big} />}

      {d.kind === 'induction' && (
        <>
          <ListGroup title="최근 3분 온도" className="mt-6" bodyClassName="px-4 pt-4 pb-2">
            <div className="h-24">
              <Sparkline values={d.tempHistory} max={Math.max(170, policy.overheatEnterC + 15)} threshold={policy.overheatEnterC}
                color={d.burner.deviceState === 'overheated' ? 'var(--color-danger)' : 'var(--color-glyph-heat)'} label="인덕션 온도 추이" />
            </div>
            <p className="mt-1 text-right text-[0.75rem] text-danger">과열 {policy.overheatEnterC}°</p>
          </ListGroup>
          <ListGroup className="mt-6" footer="안전을 위해 이 화면에서는 켜거나 끌 수 없어요. 위험하면 HomeVIS 가 화력을 낮추거나 전원을 꺼요.">
            <ListRow big={big} title="화구" value={BURNER_LABEL[d.burner.deviceState]} />
            <ListRow big={big} title="화력" value={d.burner.level > 0 ? `${d.burner.level} / 9단` : '0단'} />
            <ListRow big={big} title="온도" value={`${d.burner.temperature.toFixed(1)}°C`} />
            <ListRow big={big} title="조리 시간" value={d.burner.activeSec > 0 ? formatDuration(d.burner.activeSec) : '–'} />
            <ListRow big={big} title="마지막 변경" value={PUBLISHER_LABEL[d.lastControl]} />
            <ListRow big={big} title="과열 잠금" value={`${policy.overheatEnterC}° 잠금 · ${policy.overheatExitC}° 해제`} />
          </ListGroup>
        </>
      )}

      {d.kind === 'purifier' && (
        <ListGroup className="mt-6" footer="아침에 일어나 30분 안에 주방에 오시면 물 한 컵(250mL)을 준비해요. 하루 한 번만.">
          <ListRow big={big} title="마지막 출수" value={d.lastDispense ? `${formatWhen(d.lastDispense.at)} · ${d.lastDispense.ml}mL` : '없음'} />
          <ListRow big={big} title="방식" value={d.lastDispense?.auto ? '아침 자동' : '직접'} />
          <ListRow big={big} title="오늘 자동 출수" value={d.autoDispensedToday ? '완료' : '아직'} />
        </ListGroup>
      )}

      {d.kind === 'fan' && (
        <>
          <ListGroup className="mt-6">
            <ListRow big={big} title="전원" trailing={<Toggle checked={d.on} disabled={!d.online} size={big ? 'lg' : 'md'} label="환풍기 전원" onChange={(v) => controlDevice(d.id, { on: v })} />} />
          </ListGroup>
          <ListGroup title="풍량" className="mt-6" bodyClassName="p-2" footer={d.room === 'kitchen' ? '조리를 시작하면 자동으로 켜져요. 직접 바꾸면 자동 운전이 잠시 꺼져요.' : '풍량을 고르면 그 풍량으로 켜져요.'}>
            <Segmented label="풍량" size={big ? 'lg' : 'touch'} value={d.speed}
              options={[{ value: 1, label: '약' }, { value: 2, label: '중' }, { value: 3, label: '강' }]}
              onChange={(v) => d.online && controlDevice(d.id, { speed: v })} />
          </ListGroup>
        </>
      )}

      {d.kind === 'air' && (
        <>
          <ListGroup className="mt-6">
            <ListRow big={big} title="전원" trailing={<Toggle checked={d.on} disabled={!d.online} size={big ? 'lg' : 'md'} label="공기청정기 전원" onChange={(v) => controlDevice(d.id, { on: v })} />} />
          </ListGroup>
          <ListGroup title="운전 모드" className="mt-6" bodyClassName="p-2" footer="자동이면 공기질이 나쁠 때 스스로 켜지고, 좋아지면 꺼져요.">
            <Segmented label="운전 모드" size={big ? 'lg' : 'touch'} value={d.mode}
              options={[{ value: 'auto', label: '자동' }, { value: 'manual', label: '수동' }]}
              onChange={(v) => d.online && controlDevice(d.id, { mode: v })} />
          </ListGroup>
          <ListGroup title="공기질" className="mt-6">
            <ListRow big={big} title="등급" value={d.airQuality?.level ? AIR_LEVEL_LABEL[d.airQuality.level] : '–'} />
            <ListRow big={big} title="초미세먼지 (PM2.5)" value={d.airQuality?.pm25 !== undefined ? `${Math.round(d.airQuality.pm25)} ㎍/㎥` : '–'} />
            <ListRow big={big} title="미세먼지 (PM10)" value={d.airQuality?.pm10 !== undefined ? `${Math.round(d.airQuality.pm10)} ㎍/㎥` : '–'} />
            <ListRow big={big} title="마지막 변경" value={d.on ? (airAutoReason(d) ? '자동' : '직접 켬') : d.auto ? '자동으로 꺼짐' : '직접'} />
          </ListGroup>
        </>
      )}

      {d.kind === 'light' && (
        <>
          <ListGroup className="mt-6">
            <ListRow big={big} title="전원" trailing={<Toggle checked={d.on} disabled={!d.online} size={big ? 'lg' : 'md'} label="조명 전원" onChange={(v) => controlDevice(d.id, { on: v })} />} />
          </ListGroup>
          <ListGroup title="밝기" className="mt-6" bodyClassName="p-2"
            footer={d.brightnessSteps ? '끔 · 절전 20% · 100% 중에서 골라요. 절전은 천천히 어두워져요.' : '사람이 들어오면 켜지고, 나가면 꺼져요.'}>
            <BrightnessSlider size={big ? 'lg' : 'md'} label={`${d.name} 밝기`} disabled={!d.online}
              value={lightLevel(d)} steps={d.brightnessSteps} savingLevel={savingLevel(d)}
              onToggle={() => void controlDevice(d.id, { on: !d.on })}
              onCommit={(v) => void controlDevice(d.id, v <= 0 ? { on: false } : { brightness: v })} />
          </ListGroup>
        </>
      )}
    </Sheet>
  )
}

/** 연결이 끊긴 기기: 다시 연결 (누르면 "연결 중…", 실패하면 그 자리에서 알린다) */
function Reconnect({ device, big }: { device: Device; big: boolean }) {
  const { reconnect } = useHome()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const run = async () => {
    setBusy(true); setFailed(false)
    try { setFailed(!(await reconnect(device.id))) } finally { setBusy(false) }
  }
  return (
    <ListGroup className="mt-6" footer={failed ? undefined : '마지막으로 받은 상태를 보여주고 있어요.'}>
      <div className="flex flex-col gap-3 p-4">
        <Button variant="primary" size={big ? 'xl' : 'lg'} disabled={busy} onClick={run}>
          {busy && <RefreshCw className="spin-slow h-5 w-5" aria-hidden="true" />}
          {busy ? '연결 중…' : '다시 연결'}
        </Button>
        {failed && <p role="alert" className="text-center text-[0.875rem] font-medium text-danger">연결하지 못했어요 · 전원을 확인해 주세요</p>}
      </div>
    </ListGroup>
  )
}
