import { Info, ShieldCheck } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Toggle } from '@/components/ui/Toggle'
import { Segmented } from '@/components/ui/Segmented'
import { Sparkline } from '@/components/ui/Sparkline'
import { DeviceIcon } from '@/components/DeviceIcon'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import { summarize } from '@/lib/device'
import { BURNER_LABEL, PUBLISHER_LABEL, ROOM_LABEL } from '@/lib/labels'
import { formatDuration, formatWhen } from '@/lib/format'
import { cn } from '@/lib/cn'

export function DeviceSheet({ deviceId, onClose }: { deviceId: string | null; onClose: () => void }) {
  const { devices, policy, controlDevice } = useHome()
  const { elderly } = usePreferences()
  const d = devices.find((x) => x.id === deviceId)
  if (!d) return null
  const s = summarize(d)

  return (
    <Sheet open onClose={onClose} variant="side" width={elderly ? 560 : 480} title={d.name} subtitle={ROOM_LABEL[d.room]}>
      <div className="flex items-center gap-4 rounded-3xl bg-sunken p-5">
        <DeviceIcon kind={d.kind} active={s.active && d.online} size="lg" className="bg-surface" />
        <div>
          <p className={cn('font-bold', elderly ? 'text-3xl' : 'text-2xl', s.risk === 'danger' ? 'text-danger' : 'text-ink')}>{s.status}</p>
          <p className={cn('text-ink-2', elderly ? 'text-lg' : 'text-[0.9375rem]')}>{s.detail}</p>
        </div>
      </div>

      {!d.online && <Note>기기와 연결이 끊겼어요. 마지막으로 받은 상태를 보여주고 있어요.</Note>}

      {d.kind === 'induction' && (
        <>
          <section className="mt-6">
            <div className="mb-2 flex items-baseline justify-between">
              <h3 className="text-[0.9375rem] font-semibold text-ink">온도 추이</h3>
              <span className="text-[0.8125rem] text-ink-3">최근 3분 · 빨간 점선 = 과열 기준 {policy.overheatEnterC}°C</span>
            </div>
            <div className="h-28 rounded-2xl bg-sunken px-3 py-3">
              <Sparkline values={d.tempHistory} max={Math.max(170, policy.overheatEnterC + 15)} threshold={policy.overheatEnterC}
                color={d.burner.deviceState === 'overheated' ? '#dc3a3a' : '#2f6bed'} label="인덕션 온도 추이" />
            </div>
          </section>
          <dl className="mt-5 divide-y divide-line">
            <Row k="화구 상태" v={BURNER_LABEL[d.burner.deviceState]} />
            <Row k="화력" v={d.burner.level > 0 ? `${d.burner.level}단 / 9단` : '0단'} />
            <Row k="현재 온도" v={`${d.burner.temperature.toFixed(1)}°C`} />
            <Row k="조리 시간" v={d.burner.activeSec > 0 ? formatDuration(d.burner.activeSec) : '-'} />
            <Row k="마지막 변경" v={PUBLISHER_LABEL[d.lastControl]} />
            <Row k="과열 잠금" v={`${policy.overheatEnterC}°C 이상 · ${policy.overheatExitC}°C 이하로 식으면 해제`} />
          </dl>
          <Note icon="shield">
            인덕션은 안전을 위해 이 화면에서 켜거나 끌 수 없어요. 위험할 때는 HomeVIS 가 자동으로 화력을 낮추거나 전원을 꺼요.
          </Note>
        </>
      )}

      {d.kind === 'purifier' && (
        <>
          <dl className="mt-5 divide-y divide-line">
            <Row k="마지막 출수" v={d.lastDispense ? `${formatWhen(d.lastDispense.at)} · ${d.lastDispense.ml}mL` : '기록 없음'} />
            <Row k="출수 방식" v={d.lastDispense?.auto ? '아침 자동 출수' : '직접 출수'} />
            <Row k="오늘 자동 출수" v={d.autoDispensedToday ? '완료 (하루 1회)' : '아직 안 함'} />
          </dl>
          <Note>아침에 일어나 30분 안에 주방으로 오시면 물 한 컵(250mL)을 자동으로 준비해요. 하루 한 번만 동작해요.</Note>
        </>
      )}

      {d.kind === 'fan' && (
        <div className="mt-6 space-y-5">
          <SwitchRow label="전원" checked={d.on} disabled={!d.online} onChange={(v) => controlDevice(d.id, { on: v })} big={elderly} />
          <div>
            <p className={cn('mb-2 font-semibold text-ink', elderly ? 'text-lg' : 'text-[0.9375rem]')}>풍량</p>
            <Segmented label="풍량" size={elderly ? 'lg' : 'md'} value={d.speed}
              options={[{ value: 1, label: '약' }, { value: 2, label: '중' }, { value: 3, label: '강' }]}
              onChange={(v) => d.online && controlDevice(d.id, { speed: v })} />
          </div>
          <Note>조리를 시작하거나 주방 위험이 감지되면 자동으로 켜지고 풍량을 조절해요. 직접 바꾸면 자동 운전이 잠시 꺼져요.</Note>
        </div>
      )}

      {d.kind === 'light' && (
        <div className="mt-6 space-y-5">
          <SwitchRow label="전원" checked={d.on} disabled={!d.online} onChange={(v) => controlDevice(d.id, { on: v })} big={elderly} />
          <label className="block">
            <span className={cn('mb-2 flex justify-between font-semibold text-ink', elderly ? 'text-lg' : 'text-[0.9375rem]')}>
              밝기<span className="tabular text-ink-2">{d.brightness}%</span>
            </span>
            <input type="range" min={10} max={100} step={10} value={d.brightness} disabled={!d.online}
              onChange={(e) => controlDevice(d.id, { brightness: Number(e.target.value) })}
              className="h-2 w-full cursor-pointer" aria-label="밝기" />
          </label>
          <Note>욕실에 사람이 들어오면 자동으로 켜지고, 나가면 꺼져요.</Note>
        </div>
      )}
    </Sheet>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-6 py-3.5 text-[0.9375rem]">
      <dt className="shrink-0 text-ink-2">{k}</dt>
      <dd className="text-right font-medium text-ink">{v}</dd>
    </div>
  )
}

function SwitchRow({ label, checked, onChange, disabled, big }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; big?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-2xl bg-sunken px-5 py-4">
      <span className={cn('font-semibold text-ink', big ? 'text-lg' : 'text-[0.9375rem]')}>{label}</span>
      <Toggle checked={checked} onChange={onChange} label={label} disabled={disabled} size={big ? 'lg' : 'md'} />
    </div>
  )
}

function Note({ children, icon = 'info' }: { children: React.ReactNode; icon?: 'info' | 'shield' }) {
  const Icon = icon === 'shield' ? ShieldCheck : Info
  return (
    <p className="mt-5 flex gap-2.5 rounded-2xl bg-brand-soft px-4 py-3.5 text-[0.875rem] leading-relaxed text-[#2a4a8f]">
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

