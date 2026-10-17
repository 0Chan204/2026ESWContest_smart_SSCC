import { useEffect } from 'react'

/** html 에 테마를 건다. 토큰(CSS 변수)이 data-theme 에 따라 바뀐다. */
export function useApplyTheme(theme: 'dark' | 'light') {
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0b0b0c' : '#f2f2f7')
  }, [theme])
}
