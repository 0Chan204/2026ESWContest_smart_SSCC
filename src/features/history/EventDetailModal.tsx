import { X } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { StatusBadge } from '@/components/StatusBadge'
import { formatDateTime } from '@/lib/format'
import { ROOM_KEY } from '@/lib/appliance'
import { usePreferences } from '@/store/PreferencesContext'
import type { SafetyLog } from '@/types'

/**
 * 처리 이력 상세.
 * 목록은 단순하게(4개 컬럼), 상세는 상세하게 — 결과/판단 근거/관련 기기를 여기서 보여준다.
 */
export function EventDetailModal({ log, onClose }: { log: SafetyLog | null; onClose: () => void }) {
  const { t, elderly } = usePreferences()
  if (!log) return null

  return (
    <Modal open onClose={onClose} labelledBy="event-detail-title" size="md">
      <header className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
        <h2 id="event-detail-title" className="text-lg font-bold text-gray-900">
          {t('history.detail.title')}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close')}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <dl className="divide-y divide-gray-100 px-6 py-2">
        <Row label={t('history.detail.time')} value={formatDateTime(log.datetime)} mono />
        <Row label={t('history.detail.room')} value={t(ROOM_KEY[log.room])} />
        <Row label={t('history.detail.type')} value={t('history.type')} />
        <Row label={t('history.detail.content')} value={log.content} />
        <div className="flex items-start justify-between gap-4 py-2.5">
          <dt className="shrink-0 text-sm text-gray-500">{t('history.detail.result')}</dt>
          <dd><StatusBadge status={log.result === 'canceled' ? 'canceled' : log.result} /></dd>
        </div>
        <div className="py-2.5">
          <dt className="mb-1.5 text-sm text-gray-500">{t('history.detail.reasoning')}</dt>
          <dd>
            <ul className="space-y-1">
              {log.reasoning.map((reason) => (
                <li key={reason} className="text-sm font-medium break-keep text-gray-800">· {reason}</li>
              ))}
            </ul>
          </dd>
        </div>
        <Row label={t('history.detail.devices')} value={log.relatedDevices.join(', ')} />
        {/* 어르신 모드에서는 전문 용어인 'AI 신뢰도'를 표시하지 않는다 */}
        {!elderly && <Row label={t('history.detail.confidence')} value={`${log.confidence}%`} mono />}
      </dl>

      <div className="px-6 pt-3 pb-6">
        <button
          type="button"
          onClick={onClose}
          className="bg-brand hover:bg-brand-dark min-h-12 w-full rounded-xl font-semibold text-white transition-colors"
        >
          {t('common.close')}
        </button>
      </div>
    </Modal>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-sm text-gray-500">{label}</dt>
      <dd className={`text-right text-sm font-medium break-keep text-gray-800 ${mono ? 'tabular' : ''}`}>
        {value}
      </dd>
    </div>
  )
}
