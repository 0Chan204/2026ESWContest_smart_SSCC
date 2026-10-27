import { useHome } from '@/store/HomeStore'
import { HOUSE_ROOMS } from '@/lib/labels'
import type { AirPurifierDevice, FanDevice, HouseRoom, LightDevice, Risk } from '@/types'

/** 평면도 · 재실 감지 화면이 같이 쓰는 공간 목록 (주방 | 침실 | 욕실) */
export const RISK_BG: Partial<Record<Risk, string>> = { danger: 'bg-danger-soft', warning: 'bg-warn-soft', caution: 'bg-caution-soft' }
export const RISK_INK: Partial<Record<Risk, string>> = { danger: 'text-danger', warning: 'text-warn', caution: 'text-caution' }

export function useRooms() {
  const { location, kitchenRisk, bathroomRisk, devices } = useHome()
  const risk: Record<HouseRoom, Risk> = { kitchen: kitchenRisk, bedroom: 'normal', bathroom: bathroomRisk }
  const lights = devices.filter((d): d is LightDevice => d.kind === 'light')
  const fans = devices.filter((d): d is FanDevice => d.kind === 'fan')
  const airs = devices.filter((d): d is AirPurifierDevice => d.kind === 'air')
  return {
    location,
    rooms: HOUSE_ROOMS.map((id) => ({
      id, risk: risk[id], here: location === id,
      lights: lights.filter((d) => d.room === id), fans: fans.filter((d) => d.room === id), airs: airs.filter((d) => d.room === id),
    })),
  }
}

