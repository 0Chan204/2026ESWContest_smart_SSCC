/** 2026-08-13T18:29:20 → 2026.08.13 18:29:20 */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 2026-08-13T18:29:20 → 08.13 18:29:20 (테이블 폭 절약) */
export function formatDateShort(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** Date → HH:MM */
export function formatClock(d: Date): string {
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Date → YYYY-MM-DD (input[type=date] 용) */
export function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function p(n: number): string {
  return String(n).padStart(2, '0')
}
