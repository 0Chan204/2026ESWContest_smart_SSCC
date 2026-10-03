import { Droplet, Flame, PersonStanding, Undo2, UserX, WifiOff } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { useHome } from '@/store/HomeStore'

/**
 * 시연 도구. 목 데이터 소스일 때만 나타난다 (실서비스에는 없음).
 * 실제로는 AI 재실 판단·낙상 감지·임베디드 기기가 보내는 신호를 대신 만들어낸다.
 */
export function DemoPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { source, devices } = useHome()
  const demo = source.demo
  if (!demo) return null
  const purifier = devices.find((d) => d.kind === 'purifier')

  const run = (fn: () => void) => { fn(); onClose() }
  const items = [
    { Icon: UserX, title: '주방 이탈 (멀리)', desc: '부재 1분 → 관찰, 3분 → 화력 저감, 10분 → 전원 차단 (12배속)', fn: () => demo.leaveKitchen('far') },
    { Icon: UserX, title: '주방 이탈 (거실 근처)', desc: '가까이 있으면 기준 시간이 2배로 늘어나요', fn: () => demo.leaveKitchen('near') },
    { Icon: Undo2, title: '주방 복귀', desc: '위험 상태 해제', fn: () => demo.returnKitchen() },
    { Icon: Flame, title: '인덕션 과열', desc: '150°C 도달 → 과열 잠금, 60°C 이하로 식으면 해제', fn: () => demo.overheat() },
    { Icon: PersonStanding, title: '욕실 낙상', desc: '인덕션 비상 차단 · 보호자 문자 · 60초 후 자동 신고', fn: () => demo.fall() },
    { Icon: Droplet, title: '아침 자동 출수', desc: '하루 1회 제한 — 두 번째는 출수하지 않아요', fn: () => demo.morningDispense() },
    { Icon: WifiOff, title: purifier?.online === false ? '정수기 연결 복구' : '정수기 연결 끊김', desc: '기기 오프라인 표시 확인', fn: () => purifier && demo.toggleOffline(purifier.id) },
  ]

  return (
    <Sheet open={open} onClose={onClose} variant="side" width={420} title="시연 도구"
      subtitle="AI 재실 판단 · 낙상 감지 · 기기 신호를 대신 만들어요. 실제 서비스에는 표시되지 않아요.">
      <ul className="space-y-2">
        {items.map(({ Icon, title, desc, fn }) => (
          <li key={title}>
            <button type="button" onClick={() => run(fn)}
              className="flex w-full items-start gap-4 rounded-2xl bg-sunken px-4 py-3.5 text-left hover:bg-line">
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-ink-2" aria-hidden="true" />
              <span>
                <span className="block text-[0.9375rem] font-semibold text-ink">{title}</span>
                <span className="block text-[0.8125rem] leading-snug text-ink-2">{desc}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  )
}
