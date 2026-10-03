import type { Device, Risk } from '@/types'
import { formatDuration, formatWhen } from './format'

const SPEED = { 1: '약', 2: '중', 3: '강' } as const

export interface DeviceSummary {
  /** 켜져서 동작 중인지 (아이콘 포인트 색) */
  active: boolean
  /** 큰 글씨 상태 */
  status: string
  /** 보조 설명 */
  detail: string
  risk: Risk
}

/** 기기 상태를 사람이 읽는 문장으로. 모든 화면(타일·상세·음성 응답)이 같은 문구를 쓴다. */
export function summarize(d: Device): DeviceSummary {
  if (!d.online) return { active: false, status: '연결 끊김', detail: '기기 전원과 Wi-Fi 를 확인해 주세요', risk: 'uncertain' }
  switch (d.kind) {
    case 'induction': {
      const b = d.burner
      const t = `${Math.round(b.temperature)}°C`
      if (b.deviceState === 'overheated') return { active: true, status: '과열 잠금', detail: `${t} · 식을 때까지 켤 수 없어요`, risk: 'danger' }
      if (b.deviceState === 'cooling') return { active: false, status: '식는 중', detail: `${t} · 아직 뜨거워요`, risk: 'normal' }
      if (b.deviceState === 'on') return { active: true, status: `화력 ${b.level}단`, detail: `${t} · ${formatDuration(b.activeSec)}째 조리 중`, risk: 'normal' }
      return { active: false, status: '꺼짐', detail: `표면 ${t}`, risk: 'normal' }
    }
    case 'purifier':
      if (d.dispensing) return { active: true, status: '출수 중', detail: '물을 따르고 있어요', risk: 'normal' }
      return {
        active: false, status: '대기 중',
        detail: d.lastDispense ? `${formatWhen(d.lastDispense.at)} ${d.lastDispense.auto ? '자동 ' : ''}출수 ${d.lastDispense.ml}mL` : '출수 기록 없음',
        risk: 'normal',
      }
    case 'fan':
      return d.on
        ? { active: true, status: `풍량 ${SPEED[d.speed]}`, detail: d.auto ? '조리에 맞춰 자동 운전 중' : '직접 설정한 풍량', risk: 'normal' }
        : { active: false, status: '꺼짐', detail: d.auto ? '조리를 시작하면 자동으로 켜져요' : '자동 운전 꺼짐', risk: 'normal' }
    case 'light':
      return d.on
        ? { active: true, status: `밝기 ${d.brightness}%`, detail: d.auto ? '사람이 있어 자동으로 켜짐' : '직접 켬', risk: 'normal' }
        : { active: false, status: '꺼짐', detail: d.auto ? '사람이 들어오면 자동으로 켜져요' : '자동 점등 꺼짐', risk: 'normal' }
  }
}

export const FAN_SPEED_LABEL = SPEED

/** 원격 제어를 허용하는 기기 (인덕션·정수기는 조회 전용) */
export function isControllable(d: Device): boolean {
  return d.kind === 'fan' || d.kind === 'light'
}
