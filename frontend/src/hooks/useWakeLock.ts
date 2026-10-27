import { useEffect } from 'react'

/**
 * 대시보드가 떠 있는 동안 화면이 꺼지지 않게 한다 (Screen Wake Lock API).
 * 운영체제 설정을 바꾸지 않고, 탭을 닫거나 다른 탭으로 가면 브라우저가 자동으로 풀어준다.
 * 지원하지 않는 브라우저에서는 아무 일도 하지 않는다.
 */
export function useWakeLock() {
  useEffect(() => {
    if (!('wakeLock' in navigator)) return
    let lock: WakeLockSentinel | null = null
    let alive = true
    const request = async () => {
      if (document.visibilityState !== 'visible') return
      try {
        lock = await navigator.wakeLock.request('screen')
        if (!alive) void lock.release()
      } catch { /* 배터리 절약 모드 등으로 거부되면 그냥 둔다 */ }
    }
    // 탭이 다시 보이면 브라우저가 풀어둔 잠금을 다시 건다
    const onVisible = () => { if (document.visibilityState === 'visible') void request() }
    void request()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      alive = false
      document.removeEventListener('visibilitychange', onVisible)
      void lock?.release()
    }
  }, [])
}
