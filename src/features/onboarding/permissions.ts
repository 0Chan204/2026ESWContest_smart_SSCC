import { Mic, Radar, UserRound, Volume2 } from 'lucide-react'

/**
 * HomeVIS 가 쓰는 기능 권한 (플랫폼 appinfo.json 의 user_consent 에 해당).
 * 첫 실행 동의 창과 설정 > 앱 권한이 같은 목록을 쓴다.
 */
export const PERMISSIONS = [
  { key: 'presence', Icon: Radar, title: '재실 감지', desc: 'Wi-Fi 신호로 공간에 사람이 있는지 판단해요. 카메라는 쓰지 않아요.', required: true },
  { key: 'mic', Icon: Mic, title: '마이크', desc: '음성 명령을 들어요. 인식을 위해 음성이 브라우저 제공사 서버로 전송될 수 있어요. 호출어(홈비스)를 켜면 기다리는 동안에도 마이크가 켜져 있어요.', required: false },
  { key: 'tts', Icon: Volume2, title: '음성 안내', desc: '위험 알림을 소리 내어 읽어드려요. 기기에 내장된 음성만 써요.', required: false },
  { key: 'contacts', Icon: UserRound, title: '연락처', desc: '낙상이 감지되면 등록한 보호자에게 문자를 보내요.', required: false },
] as const

export type PermissionKey = (typeof PERMISSIONS)[number]['key']
