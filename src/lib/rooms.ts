import type { FallIncident, InductionDevice, KitchenPhase, Presence, Risk } from '@/types'
import { phaseRisk } from './labels'
import { formatDuration } from './format'

/** 공간 상태를 한 문장으로. 홈·어르신 홈·음성 응답이 같은 문장을 쓴다. */
export function describeKitchen(phase: KitchenPhase, induction: InductionDevice | undefined, p: Presence | undefined) {
  const risk: Risk = phaseRisk(phase)
  const cooking = induction?.burner.deviceState === 'on'
  const people = p?.present ? '사람 있음' : p ? `비어 있음 ${p.absentSec > 0 ? formatDuration(p.absentSec) : ''}`.trim() : '확인 중'
  switch (phase) {
    case 'overheat': return { risk, short: '과열 잠금', text: '인덕션이 과열돼 잠겼어요' }
    case 'auto_off': return { risk, short: '전원 차단', text: '오래 비워서 인덕션을 껐어요' }
    case 'auto_reduced': return { risk, short: '화력 낮춤', text: `사람이 없어 화력을 낮췄어요 · ${people}` }
    case 'absence_watch': return { risk, short: '지켜보는 중', text: `조리 중인데 사람이 없어요 · ${people}` }
    default:
      return {
        risk, short: cooking ? '조리 중' : '안전해요',
        text: cooking ? `조리 중 · 화력 ${induction!.burner.level}단 · ${people}` : `인덕션 꺼짐 · ${people}`,
      }
  }
}

export function describeBathroom(fall: FallIncident | null, p: Presence | undefined) {
  if (fall?.status === 'pending') return { risk: 'danger' as Risk, short: '낙상 감지', text: '낙상 감지 · 보호자 응답 대기 중' }
  return p?.present
    ? { risk: 'normal' as Risk, short: '사용 중', text: '사용 중 · 움직임 정상' }
    : { risk: 'normal' as Risk, short: '비어 있어요', text: '비어 있음' }
}

export const HERO_TITLE: Record<Risk, string> = {
  normal: '집 안이 안전해요',
  uncertain: '일부 기기 상태를 확인할 수 없어요',
  caution: '주방을 지켜보고 있어요',
  warning: '안전을 위해 조치했어요',
  danger: '지금 확인이 필요해요',
}
