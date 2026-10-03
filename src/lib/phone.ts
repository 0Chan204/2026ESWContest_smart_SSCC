/**
 * 전화번호 검증·표시. 백엔드 schemas._normalize_phone 과 같은 규칙:
 * 숫자만 남겨 9~11자리, 0으로 시작.
 */
export function normalizePhone(value: string): string | null {
  const digits = value.replace(/\D/g, '')
  if (digits.length < 9 || digits.length > 11 || !digits.startsWith('0')) return null
  return digits
}

/** 01012345678 → 010-1234-5678 */
export function formatPhone(digits: string): string {
  if (digits.length === 11) return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
  if (digits.length === 10) return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`
  return digits
}

/** 화면 표시용 마스킹: 010-****-5678 (월패드는 여러 사람이 보는 공용 화면) */
export function maskPhone(digits: string): string {
  const f = formatPhone(digits)
  const parts = f.split('-')
  if (parts.length === 3) return `${parts[0]}-${'*'.repeat(parts[1]!.length)}-${parts[2]}`
  return f.replace(/\d(?=\d{4})/g, '*')
}
