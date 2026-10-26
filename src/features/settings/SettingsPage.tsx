import { useState, type ComponentProps } from 'react'
import { useSearchParams } from 'react-router'
import { Check, ChevronRight, Info, Languages, Mic, Phone, ShieldCheck, SlidersHorizontal, SunMoon } from 'lucide-react'
import { PageHeader, FontScaleControl } from '@/app/PageHeader'
import { Segmented } from '@/components/ui/Segmented'
import { Toggle } from '@/components/ui/Toggle'
import { ListGroup, ListRow, SymbolIcon } from '@/components/ui/List'
import { ContactForm } from './ContactForm'
import { PolicyForm } from './PolicyForm'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import type { Language, Mode, Theme } from '@/types'
import { PERMISSIONS } from '@/features/onboarding/permissions'
import { speechSupported } from '@/features/voice/speech'
import { cn } from '@/lib/cn'

type SymColor = ComponentProps<typeof SymbolIcon>['color']

const SECTIONS = [
  { id: 'display', label: '화면', Icon: SunMoon, color: 'blue' },
  { id: 'contacts', label: '비상 연락처', Icon: Phone, color: 'green' },
  { id: 'permissions', label: '앱 권한', Icon: ShieldCheck, color: 'indigo' },
  { id: 'voice', label: '음성', Icon: Mic, color: 'red' },
  { id: 'policy', label: '안전 정책', Icon: SlidersHorizontal, color: 'gray' },
  { id: 'language', label: '언어', Icon: Languages, color: 'blue' },
  { id: 'about', label: '정보', Icon: Info, color: 'gray' },
] as const satisfies readonly { id: string; label: string; Icon: unknown; color: SymColor }[]
type SectionId = (typeof SECTIONS)[number]['id']

const PERMISSION_COLOR: Record<(typeof PERMISSIONS)[number]['key'], SymColor> = {
  presence: 'blue', mic: 'red', tts: 'orange', contacts: 'green',
}

/** 설정 — iPad 설정 앱처럼 왼쪽 목록 / 오른쪽 내용 */
export function SettingsPage() {
  const [params, setParams] = useSearchParams()
  const { elderly } = usePreferences()
  const { contacts } = useHome()
  const raw = params.get('section')
  const visible = SECTIONS.filter((s) => !(elderly && s.id === 'policy'))   // 어르신 모드에서는 관리자 설정 숨김
  const section: SectionId = visible.some((s) => s.id === raw) ? (raw as SectionId) : 'display'

  return (
    <div className="flex flex-col wall:h-full">
      <PageHeader title="설정" />
      <div className="grid grid-cols-1 gap-6 px-5 pt-5 pb-6 md:grid-cols-12 md:px-8 wall:min-h-0 wall:flex-1 wall:pb-7 wall:short:pt-4">
        <nav aria-label="설정 항목" className="md:col-span-4">
          <div className="inset-list overflow-hidden rounded-xl bg-surface">
            {visible.map(({ id, label, Icon, color }) => {
              const on = section === id
              return (
                <button key={id} type="button" onClick={() => setParams({ section: id })} aria-current={on ? 'page' : undefined}
                  className={cn('flex w-full items-center gap-3 pl-3 text-left', on ? 'bg-brand text-white' : 'press text-ink hover:bg-sunken')}>
                  <SymbolIcon icon={Icon} color={color} />
                  <span className={cn('flex flex-1 items-center gap-2 pr-3', elderly ? 'min-h-16 text-xl short:min-h-14' : 'min-h-12 text-[1rem]', !on && 'row-sep')}>
                    <span className="flex-1">{label}</span>
                    {id === 'contacts' && !contacts.guardian && <span className={cn('h-2.5 w-2.5 rounded-full', on ? 'bg-white' : 'bg-warn')} aria-label="등록 필요" />}
                    <ChevronRight className={cn('h-4 w-4 md:hidden', on ? 'text-white' : 'text-ink-3')} strokeWidth={2.4} aria-hidden="true" />
                  </span>
                </button>
              )
            })}
          </div>
        </nav>
        <div className="flex flex-col gap-6 md:col-span-8 wall:min-h-0 wall:overflow-y-auto wall:pr-1">
          {section === 'display' && <DisplaySection />}
          {section === 'contacts' && <ContactsSection />}
          {section === 'permissions' && <PermissionsSection onContacts={() => setParams({ section: 'contacts' })} />}
          {section === 'voice' && <VoiceSection />}
          {section === 'policy' && <PolicyForm />}
          {section === 'language' && <LanguageSection />}
          {section === 'about' && <AboutSection />}
        </div>
      </div>
    </div>
  )
}

/** iOS 의 하나만 고르는 목록 (선택된 줄에 파란 체크) */
function Choice<T extends string>({ title, footer, value, options, onChange }: {
  title: string; footer?: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  const { elderly } = usePreferences()
  return (
    <ListGroup title={title} footer={footer}>
      {options.map((o) => (
        <ListRow key={o.value} big={elderly} title={o.label} onClick={() => onChange(o.value)}
          trailing={<Check className={cn('h-5 w-5 text-brand-ink', value !== o.value && 'invisible')} strokeWidth={2.6} aria-label={value === o.value ? '선택됨' : undefined} />} />
      ))}
    </ListGroup>
  )
}

function DisplaySection() {
  const { mode, setMode, elderly, theme, setTheme } = usePreferences()
  return (
    <>
      <Choice<Theme> title="테마" footer="시스템은 기기 설정을 따라가요." value={theme} onChange={setTheme}
        options={[{ value: 'light', label: '라이트' }, { value: 'dark', label: '다크' }, { value: 'system', label: '시스템' }]} />
      <Choice<Mode> title="화면 모드" footer="어르신 모드는 꼭 필요한 정보만 크게 보여줘요." value={mode ?? 'normal'} onChange={setMode}
        options={[{ value: 'normal', label: '일반' }, { value: 'elderly', label: '어르신' }]} />
      {elderly && (
        <ListGroup title="글자 크기">
          <ListRow big title="크기" trailing={<FontScaleControl />} />
        </ListGroup>
      )}
    </>
  )
}

function ContactsSection() {
  const { contacts, saveContact } = useHome()
  const { elderly } = usePreferences()
  const [who, setWho] = useState<'guardian' | 'user'>('guardian')
  return (
    <>
      <Segmented<'guardian' | 'user'> label="연락처 종류" size={elderly ? 'lg' : 'md'} value={who} onChange={setWho}
        options={[{ value: 'guardian', label: '보호자' }, { value: 'user', label: '본인' }]} />
      {who === 'guardian' ? (
        <ContactForm key="guardian" big={elderly} title="보호자" contact={contacts.guardian}
          description="낙상이 감지되면 이 번호로 확인 링크가 담긴 문자를 보내요. 지금은 1명만 등록할 수 있어요. 번호는 서버에만 저장하고 화면에는 가운데를 가려서 보여드려요."
          onSave={(c) => saveContact('guardian', c)} />
      ) : (
        <ContactForm key="user" big={elderly} title="본인" contact={contacts.user}
          description="문자에 누구 댁인지 표시하는 데 쓰여요."
          onSave={(c) => saveContact('user', c)} />
      )}
    </>
  )
}

function VoiceSection() {
  const { voiceEnabled, setVoiceEnabled, wakeWordEnabled, setWakeWordEnabled, ttsEnabled, setTtsEnabled, elderly } = usePreferences()
  const supported = speechSupported()
  return (
    <>
      <ListGroup title="음성 명령" footer="마이크 버튼으로 화면 이동, 조명·환풍기·공기청정기 조작을 할 수 있어요. 인식을 위해 음성이 브라우저 제공사 서버로 전송될 수 있어요. 꺼져 있으면 예시 명령으로 동작만 보여드려요.">
        <ListRow big={elderly} title="음성 명령 사용" trailing={<Toggle checked={voiceEnabled} onChange={setVoiceEnabled} label="음성 명령 사용" size={elderly ? 'lg' : 'md'} />} />
      </ListGroup>
      <ListGroup title="호출어" footer={!supported ? '이 브라우저는 음성 인식을 지원하지 않아요.'
        : '켜 두면 “홈비스”라고 부를 때까지 마이크가 계속 켜져 있고, 기다리는 동안의 음성도 인식을 위해 브라우저 제공사 서버로 전송돼요.'}>
        <ListRow big={elderly} title="호출어로 부르기 (홈비스)" subtitle={voiceEnabled ? undefined : '음성 명령을 먼저 켜 주세요'}
          trailing={<Toggle checked={wakeWordEnabled && voiceEnabled} disabled={!voiceEnabled || !supported} onChange={setWakeWordEnabled}
            label="호출어로 부르기" size={elderly ? 'lg' : 'md'} />} />
      </ListGroup>
      <ListGroup title="위험 알림" footer="위험 알림이 뜨면 내용을 읽어드려요. 기기에 내장된 음성만 사용해요.">
        <ListRow big={elderly} title="음성 안내" trailing={<Toggle checked={ttsEnabled} onChange={setTtsEnabled} label="음성 안내" size={elderly ? 'lg' : 'md'} />} />
      </ListGroup>
    </>
  )
}

/** 앱 권한 — 첫 실행 동의 창에서 받은 권한을 하나씩 바꾼다. 모든 항목이 실제 동작에 연결돼 있다. */
function PermissionsSection({ onContacts }: { onContacts: () => void }) {
  const { voiceEnabled, setVoiceEnabled, ttsEnabled, setTtsEnabled, elderly } = usePreferences()
  const { contacts } = useHome()
  const size = elderly ? 'lg' : 'md'
  return (
    <ListGroup title="앱 권한" footer="첫 실행 때 받은 동의를 여기서 바꿀 수 있어요.">
      {PERMISSIONS.map(({ key, Icon, title, desc }) => (
        <ListRow key={key} big={elderly} wrap leading={<SymbolIcon icon={Icon} color={PERMISSION_COLOR[key]} />} title={title} subtitle={desc}
          trailing={
            key === 'presence' ? <span className="shrink-0 text-[0.875rem] text-ink-3">항상 사용</span>
            : key === 'mic' ? <Toggle checked={voiceEnabled} onChange={setVoiceEnabled} label="마이크" size={size} />
            : key === 'tts' ? <Toggle checked={ttsEnabled} onChange={setTtsEnabled} label="음성 안내" size={size} />
            : contacts.guardian ? <span className="shrink-0 text-[0.875rem] text-ink-3">등록됨</span>
            : <button type="button" onClick={onContacts} className="press shrink-0 text-[0.9375rem] font-semibold text-brand-ink">등록</button>
          } />
      ))}
    </ListGroup>
  )
}

function LanguageSection() {
  const { language, setLanguage } = usePreferences()
  return (
    <Choice<Language> title="언어" footer="메뉴와 공통 문구에 적용돼요." value={language} onChange={setLanguage}
      options={[{ value: 'ko', label: '한국어' }, { value: 'en', label: 'English' }]} />
  )
}

function AboutSection() {
  const { source } = useHome()
  const { elderly } = usePreferences()
  return (
    <ListGroup title="정보">
      <ListRow big={elderly} title="버전" value="HomeVIS 5.0" />
      <ListRow big={elderly} title="데이터" value={source.kind === 'mock' ? '시연용 (백엔드 미연결)' : '백엔드 연결됨'} />
      <ListRow big={elderly} title="화면" value="월패드 · 태블릿 · 휴대폰" />
      <ListRow big={elderly} title="인덕션 원격 제어" value="제공 안 함" />
      <ListRow big={elderly} title="외부 요청" value="없음" />
    </ListGroup>
  )
}
