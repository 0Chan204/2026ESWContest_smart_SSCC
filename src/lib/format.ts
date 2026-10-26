const p = (n: number) => String(n).padStart(2, '0')

/** ISO → 2026.10.03 14:32 */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** ISO → 14:32 */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** ISO → "오늘 14:32" / "어제 18:29" / "10월 1일 07:42" */
export function formatWhen(iso: string, nowMs = Date.now()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const today = new Date(nowMs); today.setHours(0, 0, 0, 0)
  const day = new Date(d); day.setHours(0, 0, 0, 0)
  const diff = Math.round((today.getTime() - day.getTime()) / 86_400_000)
  const t = formatTime(iso)
  if (diff === 0) return `오늘 ${t}`
  if (diff === 1) return `어제 ${t}`
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${t}`
}

/** ISO → "방금" / "3분 전" / "2시간 전" */
export function formatAgo(iso: string, nowMs = Date.now()): string {
  const sec = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 1000))
  if (sec < 30) return '방금'
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))}분 전`
  if (sec < 86_400) return `${Math.round(sec / 3600)}시간 전`
  return `${Math.round(sec / 86_400)}일 전`
}

/** 초 → "1분 20초" / "12분" / "45초" */
export function formatDuration(totalSec: number): string {
  const s = Math.max(0, Math.round(totalSec))
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m === 0) return `${r}초`
  if (m >= 10 || r === 0) return `${m}분`
  return `${m}분 ${r}초`
}

/** 초 → 00:45 */
export function formatCountdown(totalSec: number): string {
  const s = Math.max(0, Math.ceil(totalSec))
  return `${p(Math.floor(s / 60))}:${p(s % 60)}`
}

/** Date → 10월 3일 금요일 */
export function formatToday(d: Date): string {
  const days = ['일', '월', '화', '수', '목', '금', '토']
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${days[d.getDay()]}요일`
}

export function formatClock(d: Date): string {
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Date → YYYY-MM-DD (로컬, input[type=date] 용) */
export function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Date → 시간대가 붙은 ISO (예: 2026-10-24T21:00:00+09:00). 백엔드 음성 명령 recognizedAt 용 */
export function isoWithOffset(d = new Date()): string {
  const off = -d.getTimezoneOffset()
  const a = Math.abs(off)
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
    + `${off >= 0 ? '+' : '-'}${p(Math.floor(a / 60))}:${p(a % 60)}`
}
