/**
 * 호출어 "홈비스" 찾기.
 * 음성 인식이 "홈 비스", "홈비즈", "홈비쓰", "홈비스야", "HomeVIS", "home vis" 처럼 적어도 호출어로 본다.
 * 문장 맨 앞에 있을 때만 호출어다 (대화 중간에 우연히 들어간 말로 켜지지 않도록).
 */
const WAKE = /^\s*(?:홈\s*비\s*[스즈쓰]|홈\s*빗\s*스|home\s*-?\s*vis(?:e)?)\s*(?:야|여|요|아)?(?=$|[\s,.!?~·]|[가-힣])[\s,.!?~·]*/i

export interface WakeMatch {
  /** 문장 앞에 호출어가 있었는지 */
  wake: boolean
  /** 호출어를 뗀 나머지 문장 (호출어가 없으면 원문) */
  rest: string
}

export function detectWake(text: string): WakeMatch {
  const m = WAKE.exec(text)
  if (!m) return { wake: false, rest: text.trim() }
  return { wake: true, rest: text.slice(m[0].length).trim() }
}
