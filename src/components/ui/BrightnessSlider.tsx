import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { Lightbulb } from 'lucide-react'
import { BRIGHTNESS_STEP, brightnessLabel, snapBrightness } from '@/lib/device'
import { cn } from '@/lib/cn'

/** 끌기로 볼 만큼 움직였는지 (이보다 적게 움직이면 누르기 = 켜고 끄기) */
const DRAG_PX = 6
/** 키보드로 바꾼 밝기를 보내기까지 기다리는 시간 */
const KEY_COMMIT_MS = 450
/** 보낸 값을 기기 응답 없이 보여주는 최대 시간 */
const PENDING_MS = 5000

/**
 * 밝기 슬라이더 (홈 앱 · 제어 센터의 알약 모양).
 * - 좌우로 끌면 밝기를 바꾸고, 손을 떼면 한 번만 보낸다 (명령을 연달아 보내지 않음)
 * - 짧게 누르면 켜고 끈다
 * - steps 가 있으면 그 단계로만 멈춘다 (백엔드 전등: 끔 · 절전 20% · 100%), 없으면 10% 단위
 * - 보낸 값은 기기 상태가 바뀌거나 5초가 지날 때까지 먼저 보여준다 (그 뒤엔 실제 상태)
 * 마우스·터치·펜 모두 pointer 이벤트로 처리하고, 키보드는 화살표 · Home · End · Enter/Space.
 */
export function BrightnessSlider({
  value, steps, savingLevel, onCommit, onToggle, label, name, disabled = false, size = 'md', className,
}: {
  /** 지금 밝기 0~100 (0 = 꺼짐) */
  value: number
  steps?: readonly number[]
  /** 이 밝기면 '절전 20%' 처럼 읽는다 */
  savingLevel?: number
  onCommit: (value: number) => void
  onToggle: () => void
  /** 스크린리더용 이름 (예: '침실 조명 밝기') */
  label: string
  /** 슬라이더 안 왼쪽에 보일 이름 */
  name?: ReactNode
  disabled?: boolean
  size?: 'md' | 'lg'
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; x: number; start: number; moved: boolean; v: number } | null>(null)
  const keyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [draft, setDraft] = useState<number | null>(null)
  // 보낸 값 + 보낼 때의 실제 값. 실제 값이 바뀌면(기기 응답) 자동으로 무시된다
  const [pending, setPending] = useState<{ v: number; base: number } | null>(null)

  useEffect(() => () => {
    if (keyTimer.current) clearTimeout(keyTimer.current)
    if (pendingTimer.current) clearTimeout(pendingTimer.current)
  }, [])

  const shown = draft ?? (pending && pending.base === value ? pending.v : value)
  const snap = (v: number) => snapBrightness(v, steps)

  const commit = (v: number) => {
    setDraft(null)
    if (v === value) { setPending(null); return }
    setPending({ v, base: value })
    if (pendingTimer.current) clearTimeout(pendingTimer.current)
    pendingTimer.current = setTimeout(() => setPending(null), PENDING_MS)
    onCommit(v)
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled || (e.pointerType === 'mouse' && e.button !== 0)) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { id: e.pointerId, x: e.clientX, start: shown, moved: false, v: shown }
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    const dx = e.clientX - d.x
    if (!d.moved && Math.abs(dx) < DRAG_PX) return
    d.moved = true
    const width = ref.current?.getBoundingClientRect().width || 1
    d.v = snap(d.start + (dx / width) * 100)
    setDraft(d.v)
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    if (!d.moved) { setDraft(null); setPending(null); onToggle(); return }
    commit(d.v)
  }
  const onPointerCancel = () => {
    if (!drag.current) return
    drag.current = null
    setDraft(null)
  }

  // 키보드: 한 단계씩 (단계가 없으면 10%)
  const neighbor = (dir: 1 | -1) => {
    if (steps && steps.length > 0) {
      const sorted = [...steps].sort((a, b) => a - b)
      const next = dir > 0 ? sorted.find((s) => s > shown) : [...sorted].reverse().find((s) => s < shown)
      return next ?? shown
    }
    return Math.max(0, Math.min(100, shown + dir * BRIGHTNESS_STEP))
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return
    let next: number | null = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = neighbor(1)
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = neighbor(-1)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = 100
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPending(null); onToggle(); return }
    if (next === null) return
    e.preventDefault()
    const v = snap(next)
    setDraft(v)
    if (keyTimer.current) clearTimeout(keyTimer.current)
    keyTimer.current = setTimeout(() => commit(v), KEY_COMMIT_MS)
  }

  const lit = shown > 0
  const text = brightnessLabel(shown, savingLevel)
  const ticks = (steps ?? []).filter((s) => s > 0 && s < 100)
  const lg = size === 'lg'

  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={shown}
      aria-valuetext={text}
      aria-disabled={disabled || undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onLostPointerCapture={onPointerCancel}
      onKeyDown={onKeyDown}
      className={cn(
        'relative isolate flex touch-pan-y items-center overflow-hidden rounded-2xl bg-fill select-none',
        lg ? 'h-16' : 'h-14',
        disabled ? 'opacity-40' : 'cursor-pointer',
        className,
      )}
    >
      {/* 채움: 밝기만큼 따뜻한 색 */}
      <span aria-hidden="true"
        className={cn('absolute inset-y-0 left-0 -z-10 bg-glyph-light/30', draft === null && 'transition-[width] duration-300 ease-out')}
        style={{ width: `${shown}%` }} />
      {ticks.map((t) => (
        <span key={t} aria-hidden="true" className="absolute bottom-2 -z-10 h-1 w-1 -translate-x-1/2 rounded-full bg-ink-3/50" style={{ left: `${t}%` }} />
      ))}
      <Lightbulb aria-hidden="true" strokeWidth={1.9}
        className={cn('ml-4 shrink-0', lg ? 'h-7 w-7' : 'h-6 w-6', lit ? 'fill-glyph-light/40 text-glyph-light' : 'text-ink-3')} />
      {name && <span className={cn('ml-3 min-w-0 flex-1 truncate font-semibold text-ink', lg ? 'text-[1.125rem]' : 'text-[1rem]')}>{name}</span>}
      <span className={cn('tabular mr-4 ml-auto shrink-0 pl-3 font-semibold', lg ? 'text-[1.125rem]' : 'text-[0.9375rem]', lit ? 'text-ink' : 'text-ink-2')}>{text}</span>
    </div>
  )
}
