import { useEffect, useRef, useState } from 'react'
import { formatTaskError } from '../utils/formatError'
import { createPortal } from 'react-dom'
import { getTaskStatus, getTaskResults, downloadInputFile, downloadResult, cancelTask, restartTask, TaskStatusResponse } from '../api/tasks'
import { TaskResult, TASK_TYPE_LABELS, STATUS_LABELS } from '../types'
import { LumaSpin } from './ui/LumaSpin'

interface Props {
  taskId: string
  isOpen: boolean
  onClose: () => void
}

const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  pending:    { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  processing: { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  completed:  { bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  failed:     { bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
  cancelled:  { bg: '#f8fafc', text: '#64748b', border: '#cbd5e1' },
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

const SLOT_LABELS: Record<string, string> = {
  source:    'Источник',
  result:    'Результат',
  estimate:  'Смета',
  optimized: 'Оптимизированная',
}

export function TaskDetailModal({ taskId, isOpen, onClose }: Props) {
  const [task, setTask] = useState<TaskStatusResponse | null>(null)
  const [results, setResults] = useState<TaskResult[]>([])
  const [loading, setLoading] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [downloadingInput, setDownloadingInput] = useState<number | null>(null)
  const [downloadingResult, setDownloadingResult] = useState<number | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

  const fetchData = async () => {
    try {
      const [t, r] = await Promise.all([getTaskStatus(taskId), getTaskResults(taskId)])
      setTask(t)
      setResults(r)
      if (t.status !== 'processing' && t.status !== 'pending') {
        stopPolling()
      }
    } catch {
      // silent
    }
  }

  useEffect(() => {
    if (!isOpen) {
      stopPolling()
      setTask(null)
      setResults([])
      return
    }

    setLoading(true)
    fetchData().finally(() => setLoading(false))

    // Poll while processing or pending
    pollingRef.current = setInterval(fetchData, 5000)

    return () => stopPolling()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, taskId])

  useEffect(() => {
    if (!isOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const statusColors = task ? (STATUS_COLORS[task.status] ?? STATUS_COLORS.pending) : null

  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.35)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1100,
        padding: '16px',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: '16px',
          padding: '28px',
          width: '580px',
          maxWidth: '95vw',
          maxHeight: '85vh',
          overflowY: 'auto',
          boxShadow: '0 20px 60px rgba(0,0,0,0.18)',
          position: 'relative',
        }}
      >
        {/* Заголовок */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '20px', gap: '12px' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>
              {task ? (TASK_TYPE_LABELS[task.task_type] ?? task.task_type) : '—'}
            </div>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', wordBreak: 'break-word' }}>
              {task?.name ?? 'Задача'}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', fontSize: '20px', padding: '2px 6px', borderRadius: '6px', flexShrink: 0, lineHeight: 1 }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#475569' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#94a3b8' }}
          >
            ×
          </button>
        </div>

        {loading && !task && (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <LumaSpin size="md" color="#3b82f6" />
          </div>
        )}

        {task && (
          <>
            {/* Статус */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '4px 10px',
                  borderRadius: '20px',
                  fontSize: '13px',
                  fontWeight: 600,
                  background: statusColors!.bg,
                  color: statusColors!.text,
                  border: `1px solid ${statusColors!.border}`,
                }}>
                  {STATUS_LABELS[task.status as keyof typeof STATUS_LABELS] ?? task.status}
                  {task.status === 'processing' && <LumaSpin size="sm" color={statusColors!.text} />}
                </span>
                <span style={{ fontSize: '12px', color: '#94a3b8' }}>{formatDate(task.created_at)}</span>
                {(task.status === 'processing' || task.status === 'pending') && (
                  <button
                    onClick={async () => {
                      setStopping(true)
                      try {
                        await cancelTask(taskId)
                        await fetchData()
                      } finally {
                        setStopping(false)
                      }
                    }}
                    disabled={stopping}
                    style={{
                      background: stopping ? '#fecaca' : '#fee2e2',
                      color: '#dc2626',
                      border: '1px solid #fca5a5',
                      borderRadius: '8px',
                      padding: '4px 12px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: stopping ? 'not-allowed' : 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                    }}
                  >
                    {stopping ? 'Останавливаю…' : '⏹ Стоп'}
                  </button>
                )}
                {(task.status === 'failed' || task.status === 'cancelled' || task.status === 'completed') && (
                  <button
                    onClick={async () => {
                      setRestarting(true)
                      try {
                        await restartTask(taskId)
                        pollingRef.current = setInterval(fetchData, 5000)
                        await fetchData()
                      } finally {
                        setRestarting(false)
                      }
                    }}
                    disabled={restarting}
                    style={{
                      background: restarting ? '#e0f2fe' : '#f0f9ff',
                      color: '#0369a1',
                      border: '1px solid #7dd3fc',
                      borderRadius: '8px',
                      padding: '4px 12px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: restarting ? 'not-allowed' : 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                    }}
                  >
                    {restarting ? 'Запускаю…' : '↺ Перезапустить'}
                  </button>
                )}
              </div>
              {task.status === 'processing' && task.progress_message && (
                <div style={{ marginTop: '8px', fontSize: '13px', color: '#475569', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '8px 12px' }}>
                  ⏳ {task.progress_message}
                </div>
              )}
              {task.status === 'failed' && task.error_message && (
                <div style={{ marginTop: '8px', fontSize: '13px', color: '#dc2626', background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '8px', padding: '8px 12px' }}>
                  {formatTaskError(task.error_message)}
                </div>
              )}
            </div>

            <div style={{ borderTop: '1px solid #f1f5f9', marginBottom: '16px' }} />

            {/* Исходные файлы */}
            {task.input_files && task.input_files.length > 0 && (
              <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                  Исходные файлы
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {task.input_files.map((f, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '8px 10px' }}>
                      <span style={{ fontSize: '16px' }}>📎</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '13px', color: '#1e293b', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
                        <div style={{ fontSize: '11px', color: '#94a3b8' }}>{formatFileSize(f.size_bytes)}</div>
                      </div>
                      <button
                        onClick={async () => {
                          setDownloadingInput(idx)
                          try { await downloadInputFile(taskId, idx, f.name) } finally { setDownloadingInput(null) }
                        }}
                        disabled={downloadingInput === idx}
                        style={{ background: 'none', border: '1px solid #e2e8f0', borderRadius: '5px', padding: '3px 8px', fontSize: '12px', color: '#64748b', cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap' }}
                      >
                        {downloadingInput === idx ? '…' : '↓ Скачать'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Результаты */}
            {results.length > 0 && (
              <div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                  Результаты
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {results.map((r) => (
                    <div key={r.file_id} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#f0fdf4', border: '1px solid #86efac', borderRadius: '8px', padding: '8px 10px' }}>
                      <span style={{ fontSize: '16px' }}>✅</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '13px', color: '#1e293b', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.file_name}</div>
                        <div style={{ fontSize: '11px', color: '#16a34a' }}>{SLOT_LABELS[r.slot] ?? r.slot}</div>
                      </div>
                      <button
                        onClick={async () => {
                          setDownloadingResult(r.file_id)
                          try { await downloadResult(r.file_id, r.file_name) } finally { setDownloadingResult(null) }
                        }}
                        disabled={downloadingResult === r.file_id}
                        style={{ background: 'none', border: '1px solid #86efac', borderRadius: '5px', padding: '3px 8px', fontSize: '12px', color: '#15803d', cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap' }}
                      >
                        {downloadingResult === r.file_id ? '…' : '↓ Скачать'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {task.status !== 'processing' && task.status !== 'pending' && results.length === 0 && (!task.input_files || task.input_files.length === 0) && (
              <div style={{ textAlign: 'center', padding: '20px 0', color: '#94a3b8', fontSize: '14px' }}>
                Нет данных
              </div>
            )}
          </>
        )}
      </div>
    </div>,
    document.body
  )
}
