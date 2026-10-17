import { useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * 모달/드로어 공통 동작:
 *  - ESC 로 닫기
 *  - 열려 있는 동안 포커스를 컨테이너 안에 가둔다(Tab 순환)
 *  - 닫힐 때 이전 포커스로 복귀
 *
 * 터치 월패드가 주 환경이지만 키보드/스크린리더 접근성을 위해 필요하다.
 */
export function useDismissable(open: boolean, onClose: () => void) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<Element | null>(null)

  useEffect(() => {
    if (!open) return
    previousFocusRef.current = document.activeElement

    // 창 자체에 포커스를 둔다 — 스크린리더는 제목을 읽고, 터치 화면에는 첫 버튼 테두리가 생기지 않는다
    containerRef.current?.focus({ preventScroll: true })

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const nodes = containerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)
      if (!nodes || nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (!first || !last) return
      if (document.activeElement === containerRef.current) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      const previous = previousFocusRef.current
      if (previous instanceof HTMLElement) previous.focus()
    }
  }, [open, onClose])

  return containerRef
}
