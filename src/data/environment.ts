import type { Environment, RoomId } from '@/types'

export const BASE_ENVIRONMENT: Record<RoomId, Environment> = {
  kitchen: {
    room: 'kitchen',
    metrics: [
      { key: 'lux', value: '420', unit: 'lux', status: 'normal' },
      { key: 'temp', value: '24.6', unit: '°C', status: 'normal' },
      { key: 'humidity', value: '48', unit: '%', status: 'normal' },
      { key: 'air', value: '좋음', unit: '', status: 'normal' },
    ],
  },
  bathroom: {
    room: 'bathroom',
    metrics: [
      { key: 'humidity', value: '62', unit: '%', status: 'warning' },
      { key: 'temp', value: '23.8', unit: '°C', status: 'normal' },
      { key: 'air', value: '양호', unit: '', status: 'normal' },
    ],
  },
}
