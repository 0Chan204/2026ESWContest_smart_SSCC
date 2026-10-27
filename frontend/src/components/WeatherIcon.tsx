import { Cloud, CloudDrizzle, CloudFog, CloudLightning, CloudMoon, CloudRain, CloudSnow, CloudSun, Moon, Sun, type LucideIcon } from 'lucide-react'

/** WMO 날씨 코드 → 아이콘 (Open-Meteo 와 같은 코드 체계). 밤(19~6시)에는 해 대신 달 */
export function weatherIcon(code: number, hour: number): { Icon: LucideIcon; color: string } {
  const night = hour >= 19 || hour < 6
  if (code === 0) return night ? { Icon: Moon, color: 'text-ink-2' } : { Icon: Sun, color: 'text-glyph-light' }
  if (code === 1 || code === 2) return night ? { Icon: CloudMoon, color: 'text-ink-2' } : { Icon: CloudSun, color: 'text-glyph-light' }
  if (code === 45 || code === 48) return { Icon: CloudFog, color: 'text-ink-3' }
  if (code >= 51 && code <= 57) return { Icon: CloudDrizzle, color: 'text-glyph-water' }
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return { Icon: CloudRain, color: 'text-glyph-water' }
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return { Icon: CloudSnow, color: 'text-ink-3' }
  if (code >= 95) return { Icon: CloudLightning, color: 'text-glyph-light' }
  return { Icon: Cloud, color: 'text-ink-3' }
}
