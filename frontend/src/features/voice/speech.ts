/**
 * Web Speech API 최소 타입 정의.
 * lib.dom 에 표준 타입이 없어 필요한 부분만 직접 선언한다. (any 미사용)
 */
interface SpeechAlternative {
  readonly transcript: string
  readonly confidence?: number
}
interface SpeechResult {
  readonly 0: SpeechAlternative
  readonly length: number
  readonly isFinal?: boolean
}
interface SpeechResultList {
  readonly [index: number]: SpeechResult | undefined
  readonly length: number
}
export interface SpeechRecognitionEventLike {
  readonly results: SpeechResultList
  /** 이번 이벤트에서 바뀐 첫 결과의 위치 (연속 인식) */
  readonly resultIndex?: number
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

/** 이 브라우저에서 음성 인식을 쓸 수 있는지 (보안 컨텍스트 + Web Speech API) */
export function speechSupported(): boolean {
  if (typeof window === 'undefined' || !window.isSecureContext) return false
  const w = window as unknown as SpeechWindow
  return !!(w.SpeechRecognition ?? w.webkitSpeechRecognition)
}

/**
 * 사용 가능한 경우에만 인스턴스를 만든다.
 * 보안 컨텍스트(HTTPS 또는 localhost)가 아니면 마이크 자체를 쓸 수 없으므로 만들지 않는다.
 * continuous = true 는 호출어 대기용 (끝없이 듣고, 끊기면 다시 시작한다).
 */
export function createRecognition({ continuous = false }: { continuous?: boolean } = {}): SpeechRecognitionLike | null {
  if (!speechSupported()) return null
  const w = window as unknown as SpeechWindow
  const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition)!
  try {
    const recognition = new Ctor()
    recognition.lang = 'ko-KR'
    recognition.interimResults = false
    recognition.maxAlternatives = 1
    recognition.continuous = continuous
    return recognition
  } catch {
    return null
  }
}

/** 이번 이벤트에서 끝난(final) 문장들. continuous 가 아니면 첫 결과 하나 */
export function finalTranscripts(e: SpeechRecognitionEventLike): { text: string; confidence?: number }[] {
  const out: { text: string; confidence?: number }[] = []
  for (let i = e.resultIndex ?? 0; i < e.results.length; i++) {
    const r = e.results[i]
    if (!r || r.isFinal === false) continue
    const alt = r[0]
    const text = alt?.transcript?.trim() ?? ''
    if (text) out.push({ text, confidence: typeof alt.confidence === 'number' && alt.confidence > 0 ? alt.confidence : undefined })
  }
  return out
}
