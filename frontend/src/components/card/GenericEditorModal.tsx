import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { GenericRow } from '../../types'
import { LumaSpin } from '../ui/LumaSpin'
import GenericGrid from '../estimate/GenericGrid'
import {
  getVersions,
  getVersion,
  initVersionFromResult,
  initVersionFromInput,
  saveGenericRows,
} from '../../api/estimateVersions'

interface Props {
  taskId: string
  title: string
  fileSlot?: string
  fileIndex?: number
  readOnly?: boolean
  onClose: () => void
  onSaved?: () => void
}

export function GenericEditorModal({
  taskId,
  title,
  fileSlot = 'result',
  fileIndex = 0,
  readOnly,
  onClose,
  onSaved,
}: Props) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [rows, setRows] = useState<GenericRow[]>([])
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const cancelledRef = useRef(false)

  useEffect(() => {
    cancelledRef.current = false

    const load = async () => {
      try {
        let versionList = await getVersions(taskId, fileSlot)

        if (versionList.length === 0) {
          try {
            if (fileSlot === 'input') {
              await initVersionFromInput(taskId, fileIndex)
            } else {
              await initVersionFromResult(taskId)
            }
            versionList = await getVersions(taskId, fileSlot)
          } catch {
            // ignore — will show error below if still empty
          }
        }

        if (cancelledRef.current) return

        if (versionList.length === 0) {
          setError('Не удалось загрузить данные для редактора. Попробуйте закрыть и открыть снова.')
          setLoading(false)
          return
        }

        const active = versionList.find(v => !v.is_rolled_back) ?? versionList[0]
        const full = await getVersion(taskId, active.id)

        if (cancelledRef.current) return

        setActiveVersionId(active.id)
        setRows(full.rows as unknown as GenericRow[])
        setLoading(false)
      } catch {
        if (!cancelledRef.current) {
          setError('Ошибка загрузки. Попробуйте закрыть и открыть снова.')
          setLoading(false)
        }
      }
    }

    load()
    return () => { cancelledRef.current = true }
  }, [taskId, fileSlot, fileIndex])

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  const handleSave = async () => {
    if (!activeVersionId) return
    setSaving(true)
    try {
      await saveGenericRows(taskId, activeVersionId, rows)
      setDirty(false)
      try { window.parent.postMessage({ type: 'estimate-saved', taskId }, '*') } catch { /* ignore */ }
      onSaved?.()
    } finally {
      setSaving(false)
    }
  }

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
        onClick={e => e.stopPropagation()}
      >
        <span style={{ fontWeight: 600, fontSize: '14px', color: '#1e293b' }}>{title}</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#64748b', display: 'flex', alignItems: 'center',
            borderRadius: '6px', padding: '4px',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = '#f1f5f9' }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'none' }}
        >
          <X size={18} />
        </button>
      </div>

      <div
        style={{
          flex: 1, overflowY: 'auto',
          backgroundColor: '#f8fafc',
          padding: '16px 20px',
          boxSizing: 'border-box',
        }}
        onClick={e => e.stopPropagation()}
      >
        {loading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            padding: '12px 18px', marginBottom: '16px',
            backgroundColor: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: '10px', fontSize: '14px', color: '#1e40af',
          }}>
            <LumaSpin size="sm" color="#3b82f6" />
            Загрузка…
          </div>
        )}

        {error && (
          <div style={{
            padding: '12px 16px', marginBottom: '16px',
            backgroundColor: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: '8px', color: '#dc2626', fontSize: '14px',
          }}>
            {error}
          </div>
        )}

        {!loading && !error && rows.length > 0 && (
          <GenericGrid
            rows={rows}
            isDirty={dirty}
            isSaving={saving}
            isReadonly={readOnly}
            onRowsChange={newRows => { setRows(newRows); setDirty(true) }}
            onSave={handleSave}
          />
        )}

        {!loading && !error && rows.length === 0 && (
          <div style={{ color: '#94a3b8', fontSize: '14px' }}>Нет данных для отображения.</div>
        )}
      </div>
    </div>,
    document.body,
  )
}
