import { Droplet, Flame, PersonStanding, Undo2, UserX, WifiOff } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { ListGroup, ListRow, SymbolIcon } from '@/components/ui/List'
import { useHome } from '@/store/HomeStore'

/**
 * 시연 도구. 목 데이터 소스일 때만 나타난다 (실서비스에는 없음).
 * AI 재실 판단·낙상 감지·임베디드 기기가 보내는 신호를 대신 만들어낸다.
 */
export function DemoPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { source, devices } = useHome()
  const demo = source.demo
  if (!demo) return null
  const purifier = devices.find((d) => d.kind === 'purifier')
  const run = (fn: () => void) => { fn(); onClose() }

  return (
    <Sheet open={open} onClose={onClose} variant="side" width={420} title="시연 도구" subtitle="실제 서비스에는 표시되지 않아요">
      <ListGroup title="주방">
        <ListRow wrap chevron leading={<SymbolIcon icon={UserX} color="orange" />} title="주방 이탈 · 멀리" subtitle="1분 관찰 → 3분 화력 저감 → 10분 차단 (12배속)" onClick={() => run(() => demo.leaveKitchen('far'))} />
        <ListRow wrap chevron leading={<SymbolIcon icon={UserX} color="orange" />} title="주방 이탈 · 거실 근처" subtitle="가까이 있으면 기준 시간 2배" onClick={() => run(() => demo.leaveKitchen('near'))} />
        <ListRow wrap chevron leading={<SymbolIcon icon={Undo2} color="green" />} title="주방 복귀" subtitle="위험 상태 해제" onClick={() => run(() => demo.returnKitchen())} />
        <ListRow wrap chevron leading={<SymbolIcon icon={Flame} color="red" />} title="인덕션 과열" subtitle="150°C 잠금 · 60°C 이하에서 해제" onClick={() => run(() => demo.overheat())} />
        <ListRow wrap chevron leading={<SymbolIcon icon={Droplet} color="blue" />} title="아침 자동 출수" subtitle="하루 1회 — 두 번째는 출수 안 함" onClick={() => run(() => demo.morningDispense())} />
      </ListGroup>
      <ListGroup title="욕실 · 기기" className="mt-6">
        <ListRow wrap chevron leading={<SymbolIcon icon={PersonStanding} color="red" />} title="욕실 낙상" subtitle="인덕션 비상 차단 · 보호자 문자 · 60초 후 자동 신고" onClick={() => run(() => demo.fall())} />
        <ListRow wrap chevron leading={<SymbolIcon icon={WifiOff} color="gray" />} title={purifier?.online === false ? '정수기 연결 복구' : '정수기 연결 끊김'}
          subtitle="응답 없음 표시 · 다시 연결 확인" onClick={() => run(() => { if (purifier) demo.toggleOffline(purifier.id) })} />
      </ListGroup>
    </Sheet>
  )
}
