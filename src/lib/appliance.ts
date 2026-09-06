import type { Appliance, ApplianceVariant, PowerState, RoomId } from '@/types'
import type { TKey } from '@/i18n'

export function getVariant(appliance: Appliance): ApplianceVariant {
  if (appliance.status === 'offline') return 'offline'
  if (appliance.status === 'danger') return 'danger'
  if (appliance.status === 'warning') return 'warning'
  if (appliance.power === 'ON') return 'active'
  // '대기'는 고장도 꺼짐도 아니다. 색을 완전히 빼지 않고 낮은 강조로만 표현한다.
  if (appliance.power === 'STANDBY') return 'standby'
  return 'off'
}

export const POWER_KEY: Record<PowerState, TKey> = {
  ON: 'appliance.on',
  OFF: 'appliance.off',
  STANDBY: 'appliance.standby',
}

export const ROOM_KEY: Record<RoomId, TKey> = {
  kitchen: 'room.kitchen',
  bathroom: 'room.bathroom',
}
