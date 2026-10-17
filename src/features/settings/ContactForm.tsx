import { useState, type FormEvent } from 'react'
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

  const input = cn('min-w-0 flex-1 bg-transparent text-right text-ink outline-none placeholder:text-ink-3', big ? 'text-xl' : 'text-[1rem]')
  const row = cn('flex items-center gap-4 pl-4', big ? 'min-h-16' : 'min-h-[3.25rem]')
  const label = cn('w-24 shrink-0 text-ink', big ? 'text-xl' : 'text-[1rem]')

  return (
    <section>
      <h3 className="mb-1.5 px-4 text-[0.8125rem] font-medium text-ink-3">{title}</h3>
      {!editing && contact ? (
        <div className="inset-list overflow-hidden rounded-xl bg-surface">
          <div className={row}>
            <span className={label}>이름</span>
            <span className={cn('row-sep flex flex-1 justify-end self-stretch items-center pr-4 text-ink-2', big ? 'text-xl' : 'text-[1rem]')}>{contact.name}</span>
          </div>
          <div className={row}>
            <span className={label}>휴대폰</span>
            <span className={cn('tabular row-sep flex flex-1 justify-end self-stretch items-center pr-4 text-ink-2', big ? 'text-xl' : 'text-[1rem]')}>{maskPhone(contact.phone)}</span>
          </div>
          <button type="button" onClick={() => { setEditing(true); setMessage(null) }}
            className={cn('press w-full pl-4 text-left text-brand-ink', big ? 'min-h-16 text-xl' : 'min-h-[3.25rem] text-[1rem]')}>
            <span className="row-sep flex h-full items-center">번호 변경</span>
          </button>
        </div>
      ) : (
        <form onSubmit={submit} noValidate>
          <div className="inset-list overflow-hidden rounded-xl bg-surface">
            <label className={row}>
              <span className={label}>이름</span>
              <span className="row-sep flex flex-1 self-stretch items-center pr-4">
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={20} autoComplete="off" placeholder="김보호" className={input} />
              </span>
            </label>
            <label className={row}>
              <span className={label}>휴대폰</span>
              <span className="row-sep flex flex-1 self-stretch items-center pr-4">
                <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="off" maxLength={13}
                  placeholder="010-0000-0000" className={cn(input, 'tabular')} />
              </span>
            </label>
          </div>
          {error && <p role="alert" className="mt-1.5 px-4 text-[0.875rem] font-medium text-danger">{error}</p>}
          <div className="mt-4 flex gap-2">
            {contact && <Button size={big ? 'xl' : 'lg'} onClick={() => { setEditing(false); setError(null) }}>취소</Button>}
            <Button type="submit" variant="primary" size={big ? 'xl' : 'lg'} disabled={busy} className="flex-1">
              {busy ? '저장 중…' : '저장하고 확인 문자 받기'}
            </Button>
          </div>
        </form>
      )}
      <p className="mt-1.5 px-4 text-[0.8125rem] leading-snug text-ink-3">{description}</p>
      {message && <p role="status" className="mt-2 px-4 text-[0.875rem] text-ok">{message}</p>}
    </section>
  )
}
