import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface Props {
  taskId: string
  title: string
  onClose: () => void
  onSaved?: () => void
  fileSlot?: string
  fileIndex?: number
  readOnly?: boolean
}

export function EstimateEditorModal({ taskId, title, onClose, onSaved, fileSlot, fileIndex, readOnly }: Props) {
  const params = new URLSearchParams({ embed: '1' })
  if (fileSlot) params.set('file_slot', fileSlot)
  if (fileIndex !== undefined) params.set('file_index', String(fileIndex))
  if (readOnly) params.set('read_only', '1')
  const url = `/tasks/${taskId}/estimate?${params.toString()}`

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'estimate-saved' && e.data?.taskId === taskId) {
        onSaved?.()
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [taskId, onSaved])

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  return createPortal(
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 2000,
        background: 'rgba(15,23,42,0.6)',
        display: 'flex', flexDirection: 'column',
      }}
      onClick={onClose}
    >
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 20px',
          background: 'rgba(255,255,255,0.97)',
          borderBottom: '1px solid rgba(226,232,240,0.8)',
          flexShrink: 0,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <span style={{ fontWeight: 600, fontSize: '14px', color: '#1e293b' }}>{title}</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#64748b', display: 'flex', alignItems: 'center',
            borderRadius: '6px', padding: '4px',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#f1f5f9' }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'none' }}
        >
          <X size={18} />
        </button>
      </div>
      <div style={{ flex: 1, overflow: 'hidden' }} onClick={(e) => e.stopPropagation()}>
        <iframe
          src={url}
          style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
          title={title}
          allow="same-origin"
        />
      </div>
    </div>,
    document.body,
  )
}
