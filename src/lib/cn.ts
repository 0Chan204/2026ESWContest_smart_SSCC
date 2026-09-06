/** 조건부 className 결합. tailwind-merge 없이 충돌 없는 사용을 전제로 한다. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
