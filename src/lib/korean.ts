/** 마지막 글자의 받침 유무에 따라 조사를 고른다. (예: 조명을 / 환풍기를) */
export function withObjectParticle(word: string): string {
  const last = word.trim().slice(-1)
  const code = last.charCodeAt(0)
  if (Number.isNaN(code) || code < 0xac00 || code > 0xd7a3) return `${word}를`
  const hasFinal = (code - 0xac00) % 28 !== 0
  return `${word}${hasFinal ? '을' : '를'}`
}
