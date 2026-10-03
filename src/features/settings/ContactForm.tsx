import { useState, type FormEvent } from 'react'
import { UserRound } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { formatPhone, maskPhone, normalizePhone } from '@/lib/phone'
import type { Contact } from '@/types'
import { cn } from '@/lib/cn'

/**
 * 연락처 등록·변경 (PUT /api/v1/user · /guardian 과 같은 검증 규칙).
 * 공용 월패드 화면이므로 저장 후에는 번호 가운데를 가려서 보여준다.
 * 브라우저 자동완성에 개인 번호가 남지 않도록 autocomplete 를 끈다.
 */
export function ContactForm({ title, description, contact, onSave, big }: {
  title: string
  description: string
  contact: Contact | null
  onSave: (c: Contact) => Promise<string>
  big: boolean
}) {
  const [editing, setEditing] = useState(contact === null)
  const [name, setName] = useState(contact?.name ?? '')
  const [phone, setPhone] = useState(contact ? formatPhone(contact.phone) : '')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    const digits = normalizePhone(phone)
    if (!trimmed) return setError('이름을 입력해 주세요.')
    if (trimmed.length > 20) return setError('이름은 20자 이내로 입력해 주세요.')
    if (!digits) return setError('전화번호 형식이 올바르지 않아요. 예: 010-1234-5678')
    setError(null); setBusy(true)
    try {
      setMessage(await onSave({ name: trimmed, phone: digits }))
      setEditing(false)
    } catch {
      setError('저장하지 못했어요. 잠시 후 다시 시도해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  const input = cn('w-full rounded-xl bg-sunken px-4 text-ink outline-none placeholder:text-ink-3 focus:ring-2 focus:ring-brand',
    big ? 'min-h-14 text-xl' : 'min-h-12 text-base')

  return (
    <section className="rounded-3xl bg-surface p-6">
      <h3 className={cn('font-semibold text-ink', big ? 'text-2xl' : 'text-[1.0625rem]')}>{title}</h3>
      <p className={cn('mt-1 text-ink-2', big ? 'text-lg' : 'text-[0.875rem]')}>{description}</p>

      {!editing && contact ? (
        <div className="mt-4 flex items-center justify-between gap-4 rounded-2xl bg-sunken px-5 py-4">
          <div className="flex items-center gap-3">
            <UserRound className="h-6 w-6 text-ink-2" aria-hidden="true" />
            <div>
              <p className={cn('font-semibold text-ink', big ? 'text-xl' : 'text-base')}>{contact.name}</p>
              <p className="tabular text-[0.9375rem] text-ink-2">{maskPhone(contact.phone)}</p>
            </div>
          </div>
          <Button size={big ? 'lg' : 'md'} onClick={() => { setEditing(true); setMessage(null) }}>변경</Button>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3" noValidate>
          <label className="block">
            <span className="mb-1.5 block text-[0.875rem] font-semibold text-ink-2">이름</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={20} autoComplete="off" placeholder="예: 김보호" className={input} />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[0.875rem] font-semibold text-ink-2">휴대폰 번호</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="off" maxLength={13}
              placeholder="010-0000-0000" className={cn(input, 'tabular')} />
          </label>
          {error && <p role="alert" className="text-[0.875rem] font-medium text-danger">{error}</p>}
          <div className="flex gap-2 pt-1">
            {contact && <Button size={big ? 'lg' : 'md'} onClick={() => { setEditing(false); setError(null) }}>취소</Button>}
            <Button type="submit" variant="primary" size={big ? 'lg' : 'md'} disabled={busy} className="flex-1">
              {busy ? '저장 중…' : '저장하고 확인 문자 받기'}
            </Button>
          </div>
        </form>
      )}
      {message && <p role="status" className="mt-3 text-[0.875rem] text-ok">{message}</p>}
    </section>
  )
}
