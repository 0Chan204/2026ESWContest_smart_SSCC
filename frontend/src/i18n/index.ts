import { ko, type TKey } from './ko'
import { en } from './en'
import type { Language } from '@/types'

const DICTS: Record<Language, Partial<Record<TKey, string>>> = { ko, en }

export type Translate = (key: TKey, vars?: Record<string, string | number>) => string

/** 사전 조회 + {placeholder} 치환. 없는 키는 한국어로 폴백한다. */
export function createTranslate(lang: Language): Translate {
  const dict = DICTS[lang]
  return (key, vars) => {
    const template = dict[key] ?? ko[key] ?? key
    if (!vars) return template
    return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
      Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole,
    )
  }
}

export type { TKey }
