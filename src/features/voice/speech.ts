/**
 * Web Speech API 최소 타입 정의.
 * lib.dom 에 표준 타입이 없어 필요한 부분만 직접 선언한다. (any 미사용)
 */
interface SpeechAlternative {
  readonly transcript: string
}
interface SpeechResult {
  readonly 0: SpeechAlternative
  readonly length: number
}
interface SpeechResultList {
  readonly 0: SpeechResult
  readonly length: number
}
export interface SpeechRecognitionEventLike {
  readonly results: SpeechResultList
}
export interface SpeechRecognitionErrorLike {
  readonly error: string
}
export interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  continuous: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorLike) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

interface SpeechWindow {
  SpeechRecognition?: SpeechRecognitionCtor
  webkitSpeechRecognition?: SpeechRecognitionCtor
}

/**
 * 사용 가능한 경우에만 인스턴스를 만든다.
 * 보안 컨텍스트(HTTPS 또는 localhost)가 아니면 마이크 자체를 쓸 수 없으므로 만들지 않는다.
 */
export function createRecognition(): SpeechRecognitionLike | null {
  if (!window.isSecureContext) return null
  const w = window as unknown as SpeechWindow
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) return null
  try {
    const recognition = new Ctor()
    recognition.lang = 'ko-KR'
    recognition.interimResults = false
    recognition.maxAlternatives = 1
    recognition.continuous = false
    return recognition
  } catch {
    return null
  }
}
