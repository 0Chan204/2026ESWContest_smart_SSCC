/**
 * 추이 미니 그래프 (SVG, 라이브러리 없이). 온도 · 재실 신뢰도에 쓴다.
 * threshold 선(과열 기준)을 함께 그려 "얼마나 가까운지" 를 보이게 한다.
 * 색은 CSS 변수로 받아 테마에 따라 바뀐다. (예: 'var(--color-brand-ink)')
 */
export function Sparkline({ values, max, min = 20, threshold, color, height = 72, label }: {
  values: number[]
  max: number
  /** 아래 끝 값 (기본 20 — 실온 근처 온도) */
  min?: number
  threshold?: number
  color: string
  height?: number
  label: string
}) {
  const W = 300
  const H = height
  const span = Math.max(1, max - min)
  const pts = values.length > 1 ? values : [values[0] ?? min, values[0] ?? min]
  const step = W / (pts.length - 1)
  const y = (v: number) => H - ((Math.min(max, Math.max(min, v)) - min) / span) * (H - 6) - 3
  const line = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${W},${H} L0,${H} Z`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-full w-full" role="img" aria-label={label}>
      <path d={area} style={{ fill: color }} opacity="0.12" />
      {threshold !== undefined && (
        <line x1="0" x2={W} y1={y(threshold)} y2={y(threshold)} style={{ stroke: 'var(--color-danger)' }}
          strokeWidth="1" strokeDasharray="4 4" opacity="0.7" vectorEffect="non-scaling-stroke" />
      )}
      <path d={line} fill="none" style={{ stroke: color }} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}
