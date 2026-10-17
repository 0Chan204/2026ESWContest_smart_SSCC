import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { useHome } from '@/store/HomeStore'
import type { KitchenPolicy } from '@/types'

/**
 * 안전 정책 (GET/PUT /policies/kitchen-absence · /policies/fall-safety).
 * 시연·튜닝용 관리자 설정. 값끼리의 순서(관찰 < 저감 < 차단)를 검증한 뒤 저장한다.
 */
export function PolicyForm() {
  const { policy, fallPolicy, savePolicy, saveFallPolicy } = useHome()
  const [p, setP] = useState<KitchenPolicy>(policy)
  const [autoReport, setAutoReport] = useState(fallPolicy.autoReportSec)
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof KitchenPolicy) => (v: number) => setP((x) => ({ ...x, [k]: v }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const problems: string[] = []
    if (!(p.watchAfterSec < p.reduceAfterSec && p.reduceAfterSec < p.offAfterSec)) problems.push('관찰 < 화력 저감 < 전원 차단 순서여야 해요.')
    if (p.reduceToLevel < 1 || p.reduceToLevel > 9) problems.push('낮출 화력은 1~9단이어야 해요.')
    if (p.minConfidence < 0.5 || p.minConfidence > 0.99) problems.push('최소 감지 정확도는 50~99% 사이여야 해요.')
    if (p.overheatExitC >= p.overheatEnterC - 10) problems.push('과열 해제 온도는 진입 온도보다 10°C 이상 낮아야 해요.')
    if (autoReport < 15 || autoReport > 600) problems.push('자동 신고 대기 시간은 15~600초여야 해요.')
    if (problems.length) return setError(problems.join(' '))
    setError(null)
    await savePolicy(p)
    await saveFallPolicy({ autoReportSec: autoReport })
    toast.success('안전 정책을 저장했어요.')
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <Group title="조리 중 주방 이탈" footer="거실 등 주방 근처에 있으면 시간에 배수를 곱해 덜 민감하게 판단해요.">
        <Num label="지켜보기 시작" unit="초" value={p.watchAfterSec} onChange={set('watchAfterSec')} min={10} max={3600} />
        <Num label="화력 자동 저감" unit="초" value={p.reduceAfterSec} onChange={set('reduceAfterSec')} min={20} max={3600} />
        <Num label="전원 자동 차단" unit="초" value={p.offAfterSec} onChange={set('offAfterSec')} min={30} max={7200} />
        <Num label="낮출 화력" unit="단" value={p.reduceToLevel} onChange={set('reduceToLevel')} min={1} max={9} />
        <Num label="근처 배수" unit="배" value={p.nearZoneMultiplier} onChange={set('nearZoneMultiplier')} min={1} max={4} step={0.5} />
        <Num label="최소 감지 정확도" unit="%" value={Math.round(p.minConfidence * 100)} onChange={(v) => set('minConfidence')(v / 100)} min={50} max={99} />
      </Group>
      <Group title="과열" footer="인덕션 본체도 같은 기준으로 검사해요.">
        <Num label="과열 잠금 온도" unit="°C" value={p.overheatEnterC} onChange={set('overheatEnterC')} min={100} max={260} />
        <Num label="잠금 해제 온도" unit="°C" value={p.overheatExitC} onChange={set('overheatExitC')} min={30} max={200} />
      </Group>
      <Group title="낙상" footer="보호자가 응답하지 않으면 자동으로 신고해요.">
        <Num label="자동 신고까지" unit="초" value={autoReport} onChange={setAutoReport} min={15} max={600} />
      </Group>
      {error && <p role="alert" className="px-4 text-[0.875rem] font-medium text-danger">{error}</p>}
      <Button type="submit" variant="primary" size="lg" className="w-full">정책 저장</Button>
    </form>
  )
}

function Group({ title, footer, children }: { title: string; footer: string; children: React.ReactNode }) {
  return (
    <fieldset>
      <legend className="mb-1.5 px-4 text-[0.8125rem] font-medium text-ink-3">{title}</legend>
      <div className="inset-list overflow-hidden rounded-xl bg-surface">{children}</div>
      <p className="mt-1.5 px-4 text-[0.8125rem] leading-snug text-ink-3">{footer}</p>
    </fieldset>
  )
}

function Num({ label, unit, value, onChange, min, max, step = 1 }: {
  label: string; unit: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number
}) {
  return (
    <label className="flex min-h-[3.25rem] items-center gap-3 pl-4">
      <span className="row-sep flex flex-1 items-center gap-3 self-stretch pr-4">
        <span className="flex-1 text-[1rem] text-ink">{label}</span>
        <input type="number" inputMode="decimal" value={value} min={min} max={max} step={step}
          onChange={(e) => { const n = Number(e.target.value); if (Number.isFinite(n)) onChange(n) }}
          className="tabular w-24 rounded-lg bg-fill px-2.5 py-1.5 text-right text-[1rem] text-ink outline-none focus:ring-2 focus:ring-brand" />
        <span className="w-6 text-[0.875rem] text-ink-3">{unit}</span>
      </span>
    </label>
  )
}
