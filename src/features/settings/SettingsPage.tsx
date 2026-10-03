import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { ChevronRight, Info, Languages, Mic, MonitorSmartphone, Phone, SlidersHorizontal } from 'lucide-react'
import { PageHeader, FontScaleControl } from '@/app/PageHeader'
import { Segmented } from '@/components/ui/Segmented'
import { Toggle } from '@/components/ui/Toggle'
import { ContactForm } from './ContactForm'
import { PolicyForm } from './PolicyForm'
import { useHome } from '@/store/HomeStore'
import { usePreferences } from '@/store/PreferencesContext'
import type { Language, Mode } from '@/types'
import { cn } from '@/lib/cn'

const SECTIONS = [
  { id: 'display', label: '화면', Icon: MonitorSmartphone },
  { id: 'contacts', label: '비상 연락처', Icon: Phone },
  { id: 'voice', label: '음성', Icon: Mic },
  { id: 'policy', label: '안전 정책', Icon: SlidersHorizontal },
  { id: 'language', label: '언어', Icon: Languages },
  { id: 'about', label: '정보', Icon: Info },
] as const
type SectionId = (typeof SECTIONS)[number]['id']

/** 설정 — 태블릿 설정 앱처럼 왼쪽 목록 / 오른쪽 내용 두 칸 구성 */
export function SettingsPage() {
  const [params, setParams] = useSearchParams()
  const { elderly } = usePreferences()
  const { contacts } = useHome()
  const raw = params.get('section')
  const visible = SECTIONS.filter((s) => !(elderly && s.id === 'policy'))   // 어르신 모드에서는 관리자 설정 숨김
  const section: SectionId = visible.some((s) => s.id === raw) ? (raw as SectionId) : 'display'

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="설정" />
      <div className="grid min-h-0 flex-1 grid-cols-12 gap-5 px-8 pt-5 pb-7">
        <nav aria-label="설정 항목" className="col-span-4 self-start rounded-3xl bg-surface p-2">
          {visible.map(({ id, label, Icon }) => (
            <button key={id} type="button" onClick={() => setParams({ section: id })}
              aria-current={section === id ? 'page' : undefined}
              className={cn('flex w-full items-center gap-3 rounded-2xl px-4 text-left', elderly ? 'min-h-16 text-xl' : 'min-h-13 text-[1rem]',
                section === id ? 'bg-brand-soft font-semibold text-brand' : 'text-ink hover:bg-sunken')}>
              <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
              <span className="flex-1">{label}</span>
              {id === 'contacts' && !contacts.guardian && <span className="h-2 w-2 rounded-full bg-warn" aria-label="등록 필요" />}
              <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" aria-hidden="true" />
            </button>
          ))}
        </nav>
        <div className="col-span-8 min-h-0 overflow-y-auto pr-1">
          {section === 'display' && <DisplaySection />}
          {section === 'contacts' && <ContactsSection />}
          {section === 'voice' && <VoiceSection />}
          {section === 'policy' && <PolicyForm />}
          {section === 'language' && <LanguageSection />}
          {section === 'about' && <AboutSection />}
        </div>
      </div>
    </div>
  )
}

function Block({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  const { elderly } = usePreferences()
  return (
    <section className="mb-4 rounded-3xl bg-surface p-6">
      <h3 className={cn('font-semibold text-ink', elderly ? 'text-2xl' : 'text-[1.0625rem]')}>{title}</h3>
      {desc && <p className={cn('mt-1 text-ink-2', elderly ? 'text-lg' : 'text-[0.875rem]')}>{desc}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function DisplaySection() {
  const { mode, setMode, elderly } = usePreferences()
  return (
    <>
      <Block title="화면 모드" desc="어르신 모드는 꼭 필요한 정보만 크게 보여줘요.">
        <Segmented<Mode> label="화면 모드" size={elderly ? 'lg' : 'md'} value={mode ?? 'normal'} onChange={setMode}
          options={[{ value: 'normal', label: '일반' }, { value: 'elderly', label: '어르신' }]} />
      </Block>
      <Block title="글자 크기" desc={elderly ? '버튼을 눌러 글자 크기를 바꿀 수 있어요.' : '어르신 모드에서 조절할 수 있어요.'}>
        {elderly ? <FontScaleControl /> : <p className="text-[0.875rem] text-ink-3">일반 모드는 기본 크기로 표시돼요.</p>}
      </Block>
    </>
  )
}

function ContactsSection() {
  const { contacts, saveContact } = useHome()
  const { elderly } = usePreferences()
  const [who, setWho] = useState<'guardian' | 'user'>('guardian')
  return (
    <div className="space-y-4">
      <Segmented<'guardian' | 'user'> label="연락처 종류" size={elderly ? 'lg' : 'md'} value={who} onChange={setWho}
        options={[{ value: 'guardian', label: '보호자' }, { value: 'user', label: '본인' }]} />
      {who === 'guardian' ? (
        <ContactForm key="guardian" big={elderly} title="보호자" contact={contacts.guardian}
          description="낙상이 감지되면 이 번호로 확인 링크가 담긴 문자를 보내요. 지금은 1명만 등록할 수 있어요."
          onSave={(c) => saveContact('guardian', c)} />
      ) : (
        <ContactForm key="user" big={elderly} title="사용자 (본인)" contact={contacts.user}
          description="문자에 누구 댁인지 표시하는 데 쓰여요."
          onSave={(c) => saveContact('user', c)} />
      )}
      <p className="px-2 text-[0.8125rem] leading-relaxed text-ink-3">
        연락처는 이 기기에 저장하지 않고 서버에만 저장해요. 화면에는 번호 가운데를 가려서 보여드려요.
      </p>
    </div>
  )
}

function VoiceSection() {
  const { voiceEnabled, setVoiceEnabled, ttsEnabled, setTtsEnabled, elderly } = usePreferences()
  return (
    <>
      <Block title="음성 명령" desc="왼쪽 아래 마이크 버튼으로 말해서 화면을 이동하거나 조명·환풍기를 켜고 끌 수 있어요.">
        <Row label="음성 명령 사용" checked={voiceEnabled} onChange={setVoiceEnabled} big={elderly} />
        <p className="mt-3 text-[0.8125rem] leading-relaxed text-ink-3">
          브라우저 음성 인식은 인식을 위해 음성이 브라우저 제공사 서버로 전송될 수 있어요. 꺼져 있으면 예시 명령으로 동작만 보여드려요.
        </p>
      </Block>
      <Block title="위험 알림 음성 안내" desc="위험 알림이 뜨면 내용을 소리 내어 읽어드려요. 기기에 내장된 음성만 사용해요.">
        <Row label="음성 안내" checked={ttsEnabled} onChange={setTtsEnabled} big={elderly} />
      </Block>
    </>
  )
}

function LanguageSection() {
  const { language, setLanguage, elderly } = usePreferences()
  return (
    <Block title="언어" desc="메뉴와 공통 문구에 적용돼요.">
      <Segmented<Language> label="언어" size={elderly ? 'lg' : 'md'} value={language} onChange={setLanguage}
        options={[{ value: 'ko', label: '한국어' }, { value: 'en', label: 'English' }]} />
    </Block>
  )
}

function AboutSection() {
  const { source } = useHome()
  const rows: [string, string][] = [
    ['버전', 'HomeVIS 2.0'],
    ['데이터', source.kind === 'mock' ? '시연용 데이터 (백엔드 미연결)' : '백엔드 연결됨'],
    ['기준 해상도', '1280×800 · 1440×900 가로'],
    ['인덕션 원격 제어', '제공하지 않음 (조회 전용)'],
    ['외부 요청', '없음 · 광고·분석 도구 미사용'],
  ]
  return (
    <Block title="정보">
      <dl className="divide-y divide-line">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-6 py-3.5 text-[0.9375rem]">
            <dt className="text-ink-2">{k}</dt><dd className="text-right font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </Block>
  )
}

function Row({ label, checked, onChange, big }: { label: string; checked: boolean; onChange: (v: boolean) => void; big: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-2xl bg-sunken px-5 py-4">
      <span className={cn('font-semibold text-ink', big ? 'text-xl' : 'text-[0.9375rem]')}>{label}</span>
      <Toggle checked={checked} onChange={onChange} label={label} size={big ? 'lg' : 'md'} />
    </div>
  )
}
