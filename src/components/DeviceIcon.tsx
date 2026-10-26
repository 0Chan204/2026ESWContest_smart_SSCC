import { AirVent, CookingPot, Droplet, Fan, Lightbulb } from 'lucide-react'
import type { Device } from '@/types'

/** 기기 종류별 아이콘과 켜졌을 때 색 (홈 앱: 조명 노랑 · 환기 청록 · 물 파랑 · 화구 주황 · 공기 초록) */
export const DEVICE_GLYPH = {
  induction: { Icon: CookingPot, on: 'text-glyph-heat' },
  purifier: { Icon: Droplet, on: 'text-glyph-water' },
  fan: { Icon: Fan, on: 'text-glyph-fan' },
  light: { Icon: Lightbulb, on: 'text-glyph-light' },
  air: { Icon: AirVent, on: 'text-glyph-air' },
} as const satisfies Record<Device['kind'], { Icon: typeof CookingPot; on: string }>
