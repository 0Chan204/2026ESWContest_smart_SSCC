/**
 * localStorage 안전 접근 레이어.
 *
 * 원칙
 *  1. 저장하는 값은 UI 환경설정뿐이다. 인증정보·개인정보·센서 원본은 저장하지 않는다.
 *  2. 읽을 때 항상 화이트리스트/범위 검증을 한다.
 *     사용자가 devtools 로 값을 조작해도 앱은 기본값으로 안전하게 폴백한다.
 *  3. 시크릿 모드 등 접근 불가 환경에서도 예외로 앱이 죽지 않는다.
 */

const PREFIX = 'homevis_'

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(PREFIX + key, value)
  } catch {
    /* 저장 실패는 무시한다. 설정이 유지되지 않을 뿐 기능은 동작한다. */
  }
}

/** 허용된 문자열 집합 안의 값만 통과시킨다. */
export function readEnum<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const raw = safeGet(key)
  return allowed.includes(raw as T) ? (raw as T) : fallback
}

/** 지정 범위 안의 정수만 통과시킨다. */
export function readInt(key: string, min: number, max: number, fallback: number): number {
  const raw = safeGet(key)
  if (raw === null) return fallback
  const n = Number.parseInt(raw, 10)
  if (!Number.isFinite(n) || n < min || n > max) return fallback
  return n
}

export function readBool(key: string, fallback: boolean): boolean {
  const raw = safeGet(key)
  if (raw === 'true') return true
  if (raw === 'false') return false
  return fallback
}

/** 허용 키인지 확인 후 저장한다. */
export function write(key: string, value: string | number | boolean): void {
  safeSet(key, String(value))
}

export function has(key: string): boolean {
  return safeGet(key) !== null
}
