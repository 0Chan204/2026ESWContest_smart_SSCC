import { useEffect, useState } from 'react'

/** 주기적으로 갱신되는 현재 시각(ms). 카운트다운·"n분 전" 표시용. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}
