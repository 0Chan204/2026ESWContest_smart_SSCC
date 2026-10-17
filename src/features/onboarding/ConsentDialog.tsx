import { toast } from 'sonner'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/Button'
import { ListGroup, ListRow, SymbolIcon } from '@/components/ui/List'
import { usePreferences } from '@/store/PreferencesContext'
import { PERMISSIONS } from './permissions'

const COLOR = { presence: 'blue', mic: 'red', tts: 'orange', contacts: 'green' } as const

/**
 * 첫 실행 권한 동의 창.
 * 답하기 전에는 닫히지 않는다. 허용하면 마이크(음성 명령)·음성 안내가 실제로 켜지고,
 * 나중에 설정 > 앱 권한에서 하나씩 바꿀 수 있다.
 */
export function ConsentDialog() {
  const { answerConsent, elderly } = usePreferences()
  const answer = (granted: boolean) => {
    answerConsent(granted)
    toast.success(granted ? '권한을 허용했어요.' : '설정 > 앱 권한에서 언제든 바꿀 수 있어요.')
  }
  return (
    <Sheet open onClose={() => { /* 답하기 전에는 닫지 않는다 */ }} hideClose dismissOnBackdrop={false} urgent
      width={elderly ? 620 : 500} title="HomeVIS 권한" subtitle="집을 지키는 데 아래 기능을 써요."
      footer={(
        <div className="flex gap-2">
          <Button size={elderly ? 'xl' : 'lg'} className="flex-1" onClick={() => answer(false)}>허용 안 함</Button>
          <Button variant="primary" size={elderly ? 'xl' : 'lg'} className="flex-1" onClick={() => answer(true)}>허용</Button>
        </div>
      )}>
      <ListGroup footer="설정 > 앱 권한에서 하나씩 바꿀 수 있어요.">
        {PERMISSIONS.map(({ key, Icon, title, desc, required }) => (
          <ListRow key={key} big={elderly} wrap leading={<SymbolIcon icon={Icon} color={COLOR[key]} />}
            title={<>{title}{required && <span className="ml-1.5 text-[0.8125rem] text-ink-3">필수</span>}</>} subtitle={desc} />
        ))}
      </ListGroup>
    </Sheet>
  )
}
