import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * 높이가 정해진 칸에 '온전히 들어가는 줄' 만 보여주는 목록.
 * 월패드 한 화면 배치에서 마지막 줄이 반쯤 잘려 보이는 것을 막는다.
 * 넘치는 줄은 자리를 유지한 채 숨겨(visibility) 크기가 바뀌면 다시 계산한다.
 * 높이 제한이 없는 배치(세로 태블릿·휴대폰)에서는 모두 보인다.
 */
export function FitList<T>({ items, render, getKey, className, empty, none }: {
  items: T[]
  render: (item: T) => ReactNode
  getKey: (item: T) => string
  className?: string
  empty?: ReactNode
  /** 칸이 너무 낮아 한 줄도 못 넣을 때 대신 보여줄 한 줄 */
  none?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState(items.length)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const limit = el.clientHeight
      let n = 0
      for (const child of Array.from(el.querySelectorAll<HTMLElement>(':scope > [data-row]'))) {
        if (child.offsetTop + child.offsetHeight <= limit + 1) n++
        else break
      }
      setFit(n)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [items])

  if (items.length === 0) return <>{empty ?? null}</>
  return (
    <div ref={ref} className={cn('relative', className)}>
      {fit === 0 && none && <div className="absolute inset-x-0 top-0">{none}</div>}
      {items.map((item, i) => (
        <div key={getKey(item)} data-row className={i >= fit ? 'invisible' : undefined} aria-hidden={i >= fit || undefined}>
          {render(item)}
        </div>
      ))}
    </div>
  )
}
