import type { ko } from './ko'

/**
 * 영어 사전은 부분 사전이다. 없는 키는 자동으로 한국어로 폴백된다.
 * (기획서: 언어 기능 우선순위 낮음 / 구조만 확장 가능하게)
 */
export const en: Partial<Record<keyof typeof ko, string>> = {
  'nav.home': 'Home',
  'nav.kitchen': 'Kitchen',
  'nav.bathroom': 'Bathroom',
  'nav.history': 'History',
  'nav.history.elderly': 'Safety log',
  'nav.settings': 'Settings',
  'nav.connected': 'Connected',

  'room.kitchen': 'Kitchen',
  'room.bathroom': 'Bathroom',

  'onboarding.title': 'Welcome to HomeVIS',
  'onboarding.subtitle': 'Choose the screen that suits you best.',
  'onboarding.select': 'Choose',
  'onboarding.footer': 'You can change this anytime in Settings.',

  'status.normal': 'Normal',
  'status.warning': 'Caution',
  'status.danger': 'Danger',
  'status.offline': 'Offline',
  'status.success': 'Done',

  'home.summary.overall': 'Overall status',
  'home.summary.safe': 'Your home is safe',
  'home.summary.devices': 'Connected devices',
  'home.summary.alerts': 'Active safety alerts',
  'home.appliances': 'Connected appliances & devices',

  'settings.title': 'Settings',
  'settings.mode': 'Display mode',
  'settings.mode.normal': 'Standard',
  'settings.mode.elderly': 'Large text',
  'settings.fontSize': 'Text size',
  'settings.language': 'Language',
  'settings.voice': 'Voice',
  'settings.footer': 'Settings are saved automatically.',

  'common.close': 'Close',
  'common.cancel': 'Cancel',
}
