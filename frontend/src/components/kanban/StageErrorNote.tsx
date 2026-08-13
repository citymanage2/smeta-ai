import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { formatTaskError } from '../../utils/formatError'

/**
 * Причина падения стадии — словами, рядом со статусом «Ошибка».
 *
 * Один блок на все места, где видно упавшую задачу: список смет, карточка на
 * доске, страница сметы. Статус без причины отправлял человека искать её на
 * другом экране, а чаще — жать «Повторить» вслепую и получать то же самое.
 *
 * Понятный текст даёт `formatTaskError`; технический оригинал не выбрасывается,
 * а прячется под «Подробности» — без него нечего переслать разработчику.
 */
export function StageErrorNote({ message }: { message?: string | null }) {
  const [showRaw, setShowRaw] = useState(false)
  if (!message) return null

  const friendly = formatTaskError(message)
  const hasRaw = friendly.trim() !== message.trim()

  return (
    <div
      data-testid="stage-error-note"
      style={{
        display: 'flex', alignItems: 'flex-start', gap: '6px',
        background: '#fef2f2', border: '1px solid #fecaca',
        borderRadius: '6px', padding: '7px 9px', marginTop: '6px',
      }}
    >
      <AlertTriangle size={13} color="#dc2626" style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: '11px', color: '#991b1b', lineHeight: 1.5 }}>{friendly}</div>
        {hasRaw && (
          <>
            <button
              type="button"
              onClick={() => setShowRaw(v => !v)}
              style={{
                background: 'none', border: 'none', padding: '2px 0 0',
                cursor: 'pointer', color: '#b91c1c', fontSize: '10px',
                textDecoration: 'underline',
              }}
            >
              {showRaw ? 'Скрыть подробности' : 'Подробности'}
            </button>
            {showRaw && (
              <div style={{
                marginTop: '4px', fontSize: '10px', color: '#7f1d1d',
                lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                maxHeight: '160px', overflowY: 'auto',
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              }}>
                {message}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default StageErrorNote
