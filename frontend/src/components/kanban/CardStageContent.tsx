import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ChevronDown, ChevronUp, Download, Edit3, Eye, FileText } from 'lucide-react'
import { WorkflowCard } from '../../types/workflow'
import { useKanbanStore } from '../../stores/kanban'
import { downloadSlotFile } from '../../api/projects'
import {
  CardDetail,
  StageDetail,
  downloadInputFileById,
  downloadSlotFileById,
  getCardFilesMeta,
} from '../../api/workflowCards'
import { TaskStatusBadge } from './TaskStatusBadge'
import { EstimateEditorModal } from '../card/EstimateEditorModal'
import { GenericEditorModal } from '../card/GenericEditorModal'
import { LumaSpin } from '../ui/LumaSpin'
import { GENERIC_EDITOR_TASK_TYPES } from '../../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

function wasEditedBefore(editedAt: string | null, nextStageCreatedAt: string | null): boolean {
  if (!editedAt || !nextStageCreatedAt) return false
  return new Date(editedAt) > new Date(nextStageCreatedAt)
}

function safeDownload(taskId: string, slot: string) {
  downloadSlotFile(taskId, slot).catch((err) => {
    console.error('Ошибка скачивания файла:', err)
    alert('Не удалось скачать файл. Попробуйте позже.')
  })
}

const FILE_SIZE_LIMIT = 50 * 1024 * 1024

// ---------------------------------------------------------------------------
// UI Atoms
// ---------------------------------------------------------------------------
interface EditorModalState {
  taskId: string
  title: string
  fileSlot?: string
  fileIndex?: number
  readOnly?: boolean
  taskType?: string
}

function ActionButton({
  onClick, disabled, variant = 'primary', children,
}: {
  onClick: () => void
  disabled?: boolean
  variant?: 'primary' | 'secondary' | 'outline'
  children: React.ReactNode
}) {
  const base: React.CSSProperties = {
    border: 'none', borderRadius: '6px', padding: '5px 12px',
    fontSize: '13px', cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1, marginTop: '8px',
  }
  const variants: Record<string, React.CSSProperties> = {
    primary: { background: '#3b82f6', color: '#fff' },
    secondary: { background: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0' },
    outline: { background: '#fff', color: '#3b82f6', border: '1px solid #93c5fd' },
  }
  return (
    <button style={{ ...base, ...variants[variant] }} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

function ArrowBtn({ onClick, title = 'Открыть карточку' }: { onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: 'none', border: 'none', cursor: 'pointer',
        color: '#94a3b8', padding: '2px 5px', borderRadius: '4px',
        fontSize: '13px', display: 'flex', alignItems: 'center', flexShrink: 0, lineHeight: 1,
      }}
      onMouseEnter={(e) => { const el = e.currentTarget as HTMLElement; el.style.color = '#3b82f6'; el.style.background = '#eff6ff' }}
      onMouseLeave={(e) => { const el = e.currentTarget as HTMLElement; el.style.color = '#94a3b8'; el.style.background = 'none' }}
    >
      ↗
    </button>
  )
}

function DownloadBtn({ onClick, title = 'Скачать' }: { onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: 'none', border: 'none', cursor: 'pointer',
        color: '#94a3b8', padding: '2px 5px', borderRadius: '4px',
        fontSize: '14px', display: 'flex', alignItems: 'center', flexShrink: 0, lineHeight: 1,
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#94a3b8' }}
    >
      ⬇
    </button>
  )
}

function ViewBtn({ onClick, title = 'Открыть онлайн' }: { onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: '#3b82f6', border: 'none', cursor: 'pointer',
        color: '#fff', padding: '2px 5px', borderRadius: '4px',
        display: 'flex', alignItems: 'center', flexShrink: 0,
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#2563eb' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = '#3b82f6' }}
    >
      <Eye size={11} />
    </button>
  )
}

function Spinner() {
  return (
    <span style={{
      display: 'inline-block', width: '11px', height: '11px',
      border: '2px solid rgba(255,255,255,0.35)', borderTopColor: 'rgba(255,255,255,0.9)',
      borderRadius: '50%', animation: 'spin 0.65s linear infinite',
      verticalAlign: 'middle', marginRight: '5px',
    }} />
  )
}

// ---------------------------------------------------------------------------
// ManualEditWarning
// ---------------------------------------------------------------------------
function ManualEditWarning({ editedAt, prevStageName }: { editedAt: string; prevStageName: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: '6px',
      background: '#fffbeb', border: '1px solid #fcd34d',
      borderRadius: '6px', padding: '7px 9px', marginTop: '8px',
    }}>
      <AlertTriangle size={13} color="#d97706" style={{ flexShrink: 0, marginTop: 1 }} />
      <span style={{ fontSize: '11px', color: '#92400e', lineHeight: 1.5 }}>
        Этап <strong>«{prevStageName}»</strong> изменён вручную {formatDate(editedAt)}. Рекомендуется переформировать этот этап.
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FileRowCompact (compact — для канбана)
// ---------------------------------------------------------------------------
interface FileRowProps {
  name: string
  size: number
  mime: string
  date: string
  onDownload: () => void
  onOpenEditor?: () => void
  onOpenViewer?: () => void
  onOpenTask?: () => void
}

function FileRowCompact({ name, size, mime, date, onDownload, onOpenEditor, onOpenViewer, onOpenTask }: FileRowProps) {
  const isXlsx = mime.includes('spreadsheet') || mime.includes('excel') || name.endsWith('.xlsx') || name.endsWith('.xls')
  const [hover, setHover] = useState(false)
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: '5px',
        background: hover ? '#f1f5f9' : '#f8fafc',
        border: '1px solid #e2e8f0', borderRadius: '6px',
        padding: '5px 7px', transition: 'background 0.1s',
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <FileText size={12} color="#94a3b8" style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '11px', color: '#1e293b', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {name}
        </div>
        <div style={{ fontSize: '10px', color: '#94a3b8' }}>
          {formatSize(size)} · {date}
        </div>
      </div>
      <div style={{ display: 'flex', gap: '2px', flexShrink: 0 }}>
        <button
          title="Скачать"
          onClick={onDownload}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '2px 4px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#94a3b8' }}
        >
          <Download size={11} />
        </button>
        {onOpenTask && (
          <button
            title="Открыть карточку"
            onClick={onOpenTask}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '2px 4px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#94a3b8' }}
          >
            ↗
          </button>
        )}
        {onOpenViewer && isXlsx && (
          <button
            title="Просмотр (без редактирования)"
            onClick={onOpenViewer}
            style={{ background: '#64748b', border: 'none', cursor: 'pointer', color: '#fff', padding: '2px 5px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
          >
            <Eye size={11} />
          </button>
        )}
        {onOpenEditor && isXlsx && (
          <button
            title="Открыть в онлайн-редакторе"
            onClick={onOpenEditor}
            style={{ background: '#3b82f6', border: 'none', cursor: 'pointer', color: '#fff', padding: '2px 5px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
          >
            <Edit3 size={11} />
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SectionLabel
// ---------------------------------------------------------------------------
function SectionLabel({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <div style={{ fontSize: '10px', color, fontWeight: 700, marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CollapsibleSection — предыдущие стадии внутри карточки
// ---------------------------------------------------------------------------
function CollapsibleSection({
  color, label, defaultExpanded = true, children,
}: {
  color: string
  label: string
  defaultExpanded?: boolean
  children: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div style={{ marginBottom: '10px', paddingBottom: '10px', borderBottom: '1px solid #f1f5f9' }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex', alignItems: 'center', gap: '4px', width: '100%',
          background: 'none', border: 'none', cursor: 'pointer',
          padding: '0 0 4px', marginBottom: expanded ? '4px' : 0,
        }}
      >
        <span style={{ fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color, flex: 1, textAlign: 'left' }}>
          {label}
        </span>
        {expanded ? <ChevronUp size={11} color="#94a3b8" /> : <ChevronDown size={11} color="#94a3b8" />}
      </button>
      {expanded && children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
const TYPE_LABEL: Record<string, string> = {
  LIST_FROM_PROJECT: 'Перечень из проекта',
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
}

interface StageProps {
  card: WorkflowCard
  filesMeta: CardDetail | null
  onOpenEditor: (state: EditorModalState) => void
}

// ---------------------------------------------------------------------------
// InputFilesSection — секция "Исходный файл" (read-only просмотр)
// ---------------------------------------------------------------------------
function InputFilesSection({
  stage,
  taskId,
  navigateToCard,
  onOpenEditor,
  label = 'Исходный файл',
  color = '#94a3b8',
}: {
  stage: StageDetail
  taskId: string
  navigateToCard: () => void
  onOpenEditor: (state: EditorModalState) => void
  label?: string
  color?: string
}) {
  if (stage.input_files.length === 0) return null
  return (
    <CollapsibleSection color={color} label={label} defaultExpanded={false}>
      {stage.input_files.map(f => (
        <div key={f.index} style={{ marginBottom: '3px' }}>
          <FileRowCompact
            name={f.name}
            size={f.size_bytes}
            mime={f.mime_type}
            date={formatDate(stage.task_created_at)}
            onDownload={() => downloadInputFileById(taskId, f.index)}
            onOpenTask={navigateToCard}
            onOpenViewer={() => onOpenEditor({
              taskId,
              title: `${label} — ${f.name}`,
              fileSlot: 'input',
              fileIndex: f.index,
              readOnly: true,
              taskType: stage.task_type,
            })}
          />
        </div>
      ))}
    </CollapsibleSection>
  )
}

// ---------------------------------------------------------------------------
// ResultFilesSection — секция с файлами результата (с редактором)
// ---------------------------------------------------------------------------
function ResultFilesSection({
  stage,
  taskId,
  navigateToCard,
  onOpenEditor,
  label,
  color,
  fallbackSlot = 'result',
  defaultExpanded = false,
}: {
  stage: StageDetail
  taskId: string
  navigateToCard: () => void
  onOpenEditor: (state: EditorModalState) => void
  label: string
  color: string
  fallbackSlot?: string
  defaultExpanded?: boolean
}) {
  return (
    <CollapsibleSection color={color} label={label} defaultExpanded={defaultExpanded}>
      {stage.result_files.length > 0 ? (
        stage.result_files.map(f => (
          <div key={f.result_id} style={{ marginBottom: '3px' }}>
            <FileRowCompact
              name={f.file_name}
              size={f.size_bytes}
              mime={f.mime_type}
              date={formatDate(f.created_at)}
              onDownload={() => downloadSlotFileById(taskId, f.slot)}
              onOpenTask={navigateToCard}
              onOpenEditor={() => onOpenEditor({
                taskId,
                title: `${label} — ${f.file_name}`,
                fileSlot: f.slot,
                taskType: stage.task_type,
              })}
            />
          </div>
        ))
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
          <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
          <DownloadBtn onClick={() => safeDownload(taskId, fallbackSlot)} title={`Скачать ${label.toLowerCase()}`} />
          <ViewBtn onClick={() => onOpenEditor({ taskId, title: label, fileSlot: fallbackSlot, taskType: stage.task_type })} title="Открыть онлайн" />
          <ArrowBtn onClick={navigateToCard} />
        </div>
      )}
    </CollapsibleSection>
  )
}

// ---------------------------------------------------------------------------
// Stage: Перечень
// ---------------------------------------------------------------------------
function ListStage({ card, filesMeta, onOpenEditor }: StageProps) {
  const { startTask, submittingCardIds, pendingListTasks, clearPendingListTask } = useKanbanStore()
  const navigate = useNavigate()
  const pending = pendingListTasks[card.id]
  const [taskType, setTaskType] = useState<'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND'>(
    pending?.task_type ?? 'LIST_FROM_PROJECT'
  )
  const [files, setFiles] = useState<File[]>(pending?.files ?? [])
  const [fileError, setFileError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const submitting = submittingCardIds.has(card.id)
  const task = card.list_task

  const navigateToCard = () => task?.id ? navigate(`/tasks/${task.id}/status`) : navigate(`/projects/${card.project_id}/cards/${card.id}`)

  useEffect(() => {
    if (pending && files.length === 0) {
      setTaskType(pending.task_type)
      setFiles(pending.files)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  const effectiveType = (task?.task_type ?? taskType) as string
  const typeLabel = TYPE_LABEL[effectiveType] ?? effectiveType

  const handleAddFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const added = Array.from(e.target.files ?? [])
    const oversized = added.find(f => f.size > FILE_SIZE_LIMIT)
    if (oversized) {
      setFileError('Файл превышает 50 МБ')
    } else {
      setFileError(null)
      setFiles(prev => [...prev, ...added])
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  const removeFile = (idx: number) => setFiles(prev => prev.filter((_, i) => i !== idx))

  const FileList = ({ editable = true }: { editable?: boolean }) => (
    <>
      {files.map((f, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '4px 8px', marginBottom: '4px', maxWidth: '100%' }}>
          <span style={{ fontSize: '12px', flexShrink: 0 }}>📎</span>
          <span style={{ fontSize: '11px', color: '#1e293b', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{f.name}</span>
          {editable && (
            <button onClick={() => removeFile(i)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', fontSize: '14px', lineHeight: 1, padding: '0 2px', flexShrink: 0 }}>✕</button>
          )}
        </div>
      ))}
    </>
  )

  const AddFileBtn = () => (
    <button
      onClick={() => fileRef.current?.click()}
      style={{ width: '100%', fontSize: '12px', color: '#3b82f6', background: 'none', border: '1px dashed #93c5fd', borderRadius: '6px', padding: '4px 8px', cursor: 'pointer', marginBottom: '6px' }}
    >
      + Добавить файл
    </button>
  )

  const sourceStage = filesMeta?.source_stage
  const nextStage: StageDetail | null = filesMeta?.completeness_stage ?? filesMeta?.estimate_stage ?? filesMeta?.optimization_stage ?? null
  const showWarning = sourceStage?.manually_edited_at
    ? wasEditedBefore(sourceStage.manually_edited_at, nextStage?.task_created_at ?? null)
    : false

  if (task === null) {
    return (
      <div>
        <SectionLabel color="#7c3aed">{typeLabel}</SectionLabel>
        <FileList />
        <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={handleAddFiles} />
        <AddFileBtn />
        {fileError && <div style={{ color: '#dc2626', fontSize: '11px', marginBottom: '6px' }}>{fileError}</div>}
        {submitError && <div style={{ color: '#dc2626', fontSize: '11px', marginBottom: '6px' }}>{submitError}</div>}
        <ActionButton
          onClick={async () => {
            if (files.length === 0 || submitting) return
            setSubmitError(null)
            const toSend = [...files]
            clearPendingListTask(card.id)
            try {
              await startTask(card.id, { task_type: taskType, files: toSend })
            } catch {
              setSubmitError('Не удалось создать задачу. Попробуйте ещё раз.')
            }
          }}
          disabled={files.length === 0 || submitting}
        >
          {submitting ? <><Spinner />Создаю…</> : 'Создать перечень'}
        </ActionButton>
      </div>
    )
  }

  if (task.status === 'pending' || task.status === 'processing') {
    return (
      <div>
        <SectionLabel color="#7c3aed">{typeLabel}</SectionLabel>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', flexWrap: 'nowrap' }}>
          <LumaSpin size="sm" color="#d97706" />
          <span style={{ fontSize: '11px', color: '#92400e', flex: 1, minWidth: 0, whiteSpace: 'normal', lineHeight: '1.4', paddingTop: '1px' }}>
            {task.progress_message || 'В очереди…'}
          </span>
          <ArrowBtn onClick={navigateToCard} />
        </div>
      </div>
    )
  }

  if (task.status === 'completed') {
    return (
      <div>
        <SectionLabel color="#7c3aed">{typeLabel}</SectionLabel>

        {/* Исходный файл */}
        {sourceStage && sourceStage.input_files.length > 0 && (
          <div style={{ marginBottom: '6px' }}>
            <div style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '4px' }}>Исходный файл:</div>
            {sourceStage.input_files.map(f => (
              <div key={f.index} style={{ marginBottom: '3px' }}>
                <FileRowCompact
                  name={f.name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(sourceStage.task_created_at)}
                  onDownload={() => downloadInputFileById(task.id, f.index)}
                  onOpenTask={navigateToCard}
                  onOpenViewer={() => onOpenEditor({
                    taskId: task.id,
                    title: `Исходный файл — ${f.name}`,
                    fileSlot: 'input',
                    fileIndex: f.index,
                    readOnly: true,
                    taskType: task.task_type,
                  })}
                />
              </div>
            ))}
          </div>
        )}

        {/* Перечень (результат) */}
        {sourceStage && sourceStage.result_files.length > 0 ? (
          <div style={{ marginBottom: '4px' }}>
            <div style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '4px' }}>Перечень:</div>
            {sourceStage.result_files.map(f => (
              <div key={f.result_id} style={{ marginBottom: '3px' }}>
                <FileRowCompact
                  name={f.file_name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(f.created_at)}
                  onDownload={() => downloadSlotFileById(task.id, f.slot)}
                  onOpenTask={navigateToCard}
                  onOpenEditor={() => onOpenEditor({
                    taskId: task.id,
                    title: `Перечень — ${f.file_name}`,
                    fileSlot: 'result',
                    taskType: task.task_type,
                  })}
                />
              </div>
            ))}
          </div>
        ) : (
          !sourceStage && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(task.id, 'result')} title="Скачать перечень" />
              <ViewBtn onClick={() => onOpenEditor({ taskId: task.id, title: 'Перечень', fileSlot: 'result', taskType: task.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
            </div>
          )
        )}

        {showWarning && nextStage && (
          <ManualEditWarning editedAt={sourceStage!.manually_edited_at!} prevStageName="Перечень" />
        )}
      </div>
    )
  }

  // Ошибка / отменено
  return (
    <div>
      <SectionLabel color="#7c3aed">{typeLabel}</SectionLabel>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap', marginBottom: '8px' }}>
        <TaskStatusBadge task={task} />
        <ArrowBtn onClick={navigateToCard} />
      </div>
      <FileList />
      <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={handleAddFiles} />
      <AddFileBtn />
      {fileError && <div style={{ color: '#dc2626', fontSize: '11px', marginBottom: '6px' }}>{fileError}</div>}
      {submitError && <div style={{ color: '#dc2626', fontSize: '11px', marginBottom: '6px' }}>{submitError}</div>}
      <ActionButton
        onClick={async () => {
          if (files.length === 0 || submitting) return
          setSubmitError(null)
          const toSend = [...files]
          try {
            await startTask(card.id, { task_type: task.task_type as 'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND', files: toSend })
          } catch {
            setSubmitError('Не удалось запустить задачу. Попробуйте ещё раз.')
          }
        }}
        disabled={files.length === 0 || submitting}
      >
        {submitting ? <><Spinner />Запускаю…</> : 'Повторить'}
      </ActionButton>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stage: Полнота
// ---------------------------------------------------------------------------
function CompletenessStage({ card, filesMeta, onOpenEditor }: StageProps) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const navigate = useNavigate()
  const submitting = submittingCardIds.has(card.id)
  const task = card.completeness_task
  const listTask = card.list_task

  const navigateToCard = () => task?.id ? navigate(`/tasks/${task.id}/status`) : navigate(`/projects/${card.project_id}/cards/${card.id}`)

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const getCompletenessType = () =>
    card.list_task?.task_type === 'LIST_FROM_PROJECT'
      ? 'CHECK_PROJECT_COMPLETENESS'
      : 'CHECK_LIST_COMPLETENESS'

  const sourceStage = filesMeta?.source_stage
  const completenessStage = filesMeta?.completeness_stage
  const nextStage: StageDetail | null = filesMeta?.estimate_stage ?? filesMeta?.optimization_stage ?? null

  const listEditedWarning = sourceStage?.manually_edited_at && completenessStage
    ? wasEditedBefore(sourceStage.manually_edited_at, completenessStage.task_created_at)
    : false

  const completenessEditedWarning = completenessStage?.manually_edited_at && nextStage
    ? wasEditedBefore(completenessStage.manually_edited_at, nextStage.task_created_at)
    : false

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: '10px', fontWeight: 700, textTransform: 'uppercase',
    letterSpacing: '0.05em', marginBottom: '4px',
  }

  return (
    <div>
      {/* Исходный файл */}
      {listTask !== null && listTask.status === 'completed' && sourceStage && sourceStage.input_files.length > 0 && (
        <InputFilesSection
          stage={sourceStage}
          taskId={listTask.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Исходный файл"
          color="#94a3b8"
        />
      )}

      {/* Перечень */}
      {listTask !== null && listTask.status === 'completed' && (
        <CollapsibleSection color="#7c3aed" label={listTypeLabel} defaultExpanded={!!listEditedWarning}>
          {sourceStage && sourceStage.result_files.length > 0 ? (
            sourceStage.result_files.map(f => (
              <div key={f.result_id} style={{ marginBottom: '3px' }}>
                <FileRowCompact
                  name={f.file_name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(f.created_at)}
                  onDownload={() => downloadSlotFileById(listTask.id, f.slot)}
                  onOpenTask={navigateToCard}
                  onOpenEditor={() => onOpenEditor({
                    taskId: listTask.id,
                    title: `Перечень — ${f.file_name}`,
                    fileSlot: 'result',
                    taskType: listTask.task_type,
                  })}
                />
              </div>
            ))
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(listTask.id, 'result')} title="Скачать перечень" />
              <ViewBtn onClick={() => onOpenEditor({ taskId: listTask.id, title: 'Перечень', fileSlot: 'result', taskType: listTask.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
            </div>
          )}
          {listEditedWarning && (
            <ManualEditWarning editedAt={sourceStage!.manually_edited_at!} prevStageName="Перечень" />
          )}
        </CollapsibleSection>
      )}

      {/* Задача проверки полноты */}
      {task === null && (
        <ActionButton onClick={async () => { await startTask(card.id, { task_type: getCompletenessType() }) }} disabled={submitting}>
          {submitting ? 'Запускаю…' : 'Запустить проверку полноты'}
        </ActionButton>
      )}

      {task !== null && (task.status === 'pending' || task.status === 'processing') && (
        <div>
          <div style={{ ...sectionLabelStyle, color: '#3b82f6' }}>Проверка полноты</div>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
            <LumaSpin size="sm" color="#d97706" />
            {task.progress_message && (
              <span style={{ fontSize: '11px', color: '#92400e', flex: 1, minWidth: 0, whiteSpace: 'normal', lineHeight: '1.4' }}>
                {task.progress_message}
              </span>
            )}
            <ArrowBtn onClick={navigateToCard} />
          </div>
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        <div>
          <div style={{ ...sectionLabelStyle, color: '#3b82f6' }}>Полнота</div>
          {completenessStage && completenessStage.result_files.length > 0 ? (
            completenessStage.result_files.map(f => (
              <div key={f.result_id} style={{ marginBottom: '3px' }}>
                <FileRowCompact
                  name={f.file_name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(f.created_at)}
                  onDownload={() => downloadSlotFileById(task.id, f.slot)}
                  onOpenTask={navigateToCard}
                  onOpenEditor={() => onOpenEditor({
                    taskId: task.id,
                    title: `Полнота — ${f.file_name}`,
                    fileSlot: 'result',
                    taskType: task.task_type,
                  })}
                />
              </div>
            ))
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(task.id, 'result')} title="Скачать результат проверки" />
              <ViewBtn onClick={() => onOpenEditor({ taskId: task.id, title: 'Полнота', fileSlot: 'result', taskType: task.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
            </div>
          )}
          {completenessEditedWarning && (
            <ManualEditWarning editedAt={completenessStage!.manually_edited_at!} prevStageName="Проверка полноты" />
          )}
        </div>
      )}

      {task !== null && (task.status === 'failed' || task.status === 'cancelled') && (
        <div>
          <div style={{ ...sectionLabelStyle, color: '#3b82f6' }}>Проверка полноты</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <TaskStatusBadge task={task} />
            <ArrowBtn onClick={navigateToCard} />
          </div>
          <ActionButton
            onClick={async () => { await startTask(card.id, { task_type: task.task_type ?? getCompletenessType() }) }}
            disabled={submitting}
          >
            {submitting ? 'Запускаю…' : 'Повторить'}
          </ActionButton>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stage: Смета
// ---------------------------------------------------------------------------
function EstimateStage({ card, filesMeta, onOpenEditor }: StageProps) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const navigate = useNavigate()
  const submitting = submittingCardIds.has(card.id)
  const task = card.estimate_task
  const listTask = card.list_task
  const completenessTask = card.completeness_task

  const navigateToCard = () => task?.id ? navigate(`/tasks/${task.id}/status`) : navigate(`/projects/${card.project_id}/cards/${card.id}`)

  const listCompleted = listTask?.status === 'completed'
  const completenessCompleted = completenessTask?.status === 'completed'

  const [sourceStageNum, setSourceStageNum] = useState<1 | 2>(completenessCompleted ? 2 : 1)

  const noSource = !listCompleted && !completenessCompleted

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: '10px', fontWeight: 700, textTransform: 'uppercase',
    letterSpacing: '0.05em', marginBottom: '4px',
  }

  const sourceMetaStage = filesMeta?.source_stage
  const completenessMetaStage = filesMeta?.completeness_stage
  const estimateMetaStage = filesMeta?.estimate_stage
  const nextStage: StageDetail | null = filesMeta?.optimization_stage ?? null

  const listEditedWarning = sourceMetaStage?.manually_edited_at && estimateMetaStage
    ? wasEditedBefore(sourceMetaStage.manually_edited_at, estimateMetaStage.task_created_at)
    : false

  const completenessEditedWarning = completenessMetaStage?.manually_edited_at && estimateMetaStage
    ? wasEditedBefore(completenessMetaStage.manually_edited_at, estimateMetaStage.task_created_at)
    : false

  const estimateEditedWarning = estimateMetaStage?.manually_edited_at && nextStage
    ? wasEditedBefore(estimateMetaStage.manually_edited_at, nextStage.task_created_at)
    : false

  const canCreate = task === null || task.status === 'failed' || task.status === 'cancelled'

  const handleCreate = async () => {
    await startTask(card.id, { task_type: 'ESTIMATE_FROM_LIST', source_stage: sourceStageNum })
  }

  return (
    <div>
      {/* Исходный файл */}
      {listTask !== null && listTask.status === 'completed' && sourceMetaStage && sourceMetaStage.input_files.length > 0 && (
        <InputFilesSection
          stage={sourceMetaStage}
          taskId={listTask.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Исходный файл"
          color="#94a3b8"
        />
      )}

      {/* Перечень */}
      {listTask !== null && listTask.status === 'completed' && (
        <CollapsibleSection color="#7c3aed" label={listTypeLabel} defaultExpanded={!!listEditedWarning}>
          {sourceMetaStage && sourceMetaStage.result_files.length > 0 ? (
            sourceMetaStage.result_files.map(f => (
              <div key={f.result_id} style={{ marginBottom: '3px' }}>
                <FileRowCompact
                  name={f.file_name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(f.created_at)}
                  onDownload={() => downloadSlotFileById(listTask.id, f.slot)}
                  onOpenTask={navigateToCard}
                  onOpenEditor={() => onOpenEditor({
                    taskId: listTask.id,
                    title: `Перечень — ${f.file_name}`,
                    fileSlot: 'result',
                    taskType: listTask.task_type,
                  })}
                />
              </div>
            ))
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(listTask.id, 'result')} title="Скачать перечень" />
              <ViewBtn onClick={() => onOpenEditor({ taskId: listTask.id, title: 'Перечень', fileSlot: 'result', taskType: listTask.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
            </div>
          )}
          {listEditedWarning && (
            <ManualEditWarning editedAt={sourceMetaStage!.manually_edited_at!} prevStageName="Перечень" />
          )}
        </CollapsibleSection>
      )}

      {/* Полнота (если есть) */}
      {completenessTask !== null && completenessTask.status === 'completed' && (
        <CollapsibleSection color="#3b82f6" label="Полнота" defaultExpanded={!!completenessEditedWarning}>
          {completenessMetaStage && completenessMetaStage.result_files.length > 0 ? (
            completenessMetaStage.result_files.map(f => (
              <div key={f.result_id} style={{ marginBottom: '3px' }}>
                <FileRowCompact
                  name={f.file_name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(f.created_at)}
                  onDownload={() => downloadSlotFileById(completenessTask.id, f.slot)}
                  onOpenTask={navigateToCard}
                  onOpenEditor={() => onOpenEditor({
                    taskId: completenessTask.id,
                    title: `Полнота — ${f.file_name}`,
                    fileSlot: 'result',
                    taskType: completenessTask.task_type,
                  })}
                />
              </div>
            ))
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(completenessTask.id, 'result')} title="Скачать результат проверки" />
              <ViewBtn onClick={() => onOpenEditor({ taskId: completenessTask.id, title: 'Полнота', fileSlot: 'result', taskType: completenessTask.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
            </div>
          )}
          {completenessEditedWarning && (
            <ManualEditWarning editedAt={completenessMetaStage!.manually_edited_at!} prevStageName="Проверка полноты" />
          )}
        </CollapsibleSection>
      )}

      {/* Смета */}
      <div style={{ ...sectionLabelStyle, color: '#0f766e' }}>Смета из перечня</div>

      {task !== null && (task.status === 'pending' || task.status === 'processing') && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', flexWrap: 'nowrap' }}>
          <LumaSpin size="sm" color="#d97706" />
          <span style={{ fontSize: '11px', color: '#92400e', flex: 1, minWidth: 0, whiteSpace: 'normal', lineHeight: '1.4', paddingTop: '1px' }}>
            {task.progress_message || 'В очереди…'}
          </span>
          <ArrowBtn onClick={navigateToCard} />
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        estimateMetaStage && estimateMetaStage.result_files.length > 0 ? (
          estimateMetaStage.result_files.map(f => (
            <div key={f.result_id} style={{ marginBottom: '3px' }}>
              <FileRowCompact
                name={f.file_name}
                size={f.size_bytes}
                mime={f.mime_type}
                date={formatDate(f.created_at)}
                onDownload={() => downloadSlotFileById(task.id, f.slot)}
                onOpenTask={navigateToCard}
                onOpenEditor={() => onOpenEditor({
                  taskId: task.id,
                  title: `Смета — ${f.file_name}`,
                  fileSlot: f.slot,
                  taskType: task.task_type,
                })}
              />
            </div>
          ))
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
            <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
            <DownloadBtn onClick={() => safeDownload(task.id, 'result')} title="Скачать смету" />
            <ViewBtn onClick={() => onOpenEditor({ taskId: task.id, title: 'Смета из перечня', fileSlot: 'result', taskType: task.task_type })} title="Открыть онлайн" />
            <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
          </div>
        )
      )}

      {task !== null && (task.status === 'failed' || task.status === 'cancelled') && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <TaskStatusBadge task={task} />
            <ArrowBtn onClick={navigateToCard} />
          </div>
        </div>
      )}

      {estimateEditedWarning && nextStage && (
        <ManualEditWarning editedAt={estimateMetaStage!.manually_edited_at!} prevStageName="Смета из перечня" />
      )}

      {canCreate && (
        <div style={{ marginTop: task !== null && (task.status === 'failed' || task.status === 'cancelled') ? '6px' : '4px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '10px' }}>
          {noSource ? (
            <div style={{ color: '#dc2626', fontSize: '12px' }}>Сначала завершите Перечень</div>
          ) : (
            <>
              <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '6px' }}>Источник:</div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', marginBottom: '4px', cursor: listCompleted ? 'pointer' : 'not-allowed', opacity: listCompleted ? 1 : 0.4 }}>
                <input type="radio" value={1} checked={sourceStageNum === 1} disabled={!listCompleted} onChange={() => setSourceStageNum(1)} />
                На основе перечня
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: completenessCompleted ? 'pointer' : 'not-allowed', opacity: completenessCompleted ? 1 : 0.4 }}>
                <input type="radio" value={2} checked={sourceStageNum === 2} disabled={!completenessCompleted} onChange={() => setSourceStageNum(2)} />
                На основе полноты
              </label>
              <div style={{ marginTop: '8px' }}>
                <ActionButton onClick={handleCreate} disabled={submitting}>
                  {submitting ? 'Запускаю…' : 'Создать смету'}
                </ActionButton>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stage: Оптимизация
// ---------------------------------------------------------------------------
function OptimizationStage({ card, filesMeta, onOpenEditor }: StageProps) {
  const navigate = useNavigate()
  const { startTask, submittingCardIds } = useKanbanStore()
  const submitting = submittingCardIds.has(card.id)
  const task = card.optimization_task
  const listTask = card.list_task
  const completenessTask = card.completeness_task
  const estimateTask = card.estimate_task
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [archiveExpanded, setArchiveExpanded] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const navigateToCard = () => task?.id ? navigate(`/tasks/${task.id}/status`) : navigate(`/projects/${card.project_id}/cards/${card.id}`)

  const estimateCompleted = estimateTask?.status === 'completed'
  const optimizationMeta = filesMeta?.optimization_stage
  const sourceMetaStage = filesMeta?.source_stage
  const completenessMetaStage = filesMeta?.completeness_stage
  const estimateMetaStage = filesMeta?.estimate_stage

  const mainFile = optimizationMeta?.result_files.find(f => f.slot === 'optimized') ?? optimizationMeta?.result_files[0]
  const archiveFiles = optimizationMeta?.result_files.filter(f => f.slot !== 'optimized' && f.slot !== 'source') ?? []

  const hasSourcePipeline = !!(listTask && listTask.status === 'completed')

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    if (f && f.size > FILE_SIZE_LIMIT) {
      setFileError('Файл превышает 50 МБ')
      setFile(null)
    } else {
      setFileError(null)
      setFile(f)
    }
  }

  const handleUsePrevious = async () => {
    await startTask(card.id, { task_type: 'ESTIMATE_OPTIMIZATION', use_previous_stage: true })
  }

  const handleUpload = async () => {
    if (!file) return
    await startTask(card.id, { task_type: 'ESTIMATE_OPTIMIZATION', file })
    setFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const canStart = task === null || task.status === 'failed' || task.status === 'cancelled'

  return (
    <div>
      {/* Исходный файл (если карточка пришла из перечня) */}
      {hasSourcePipeline && sourceMetaStage && sourceMetaStage.input_files.length > 0 && (
        <InputFilesSection
          stage={sourceMetaStage}
          taskId={listTask!.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Исходный файл"
          color="#94a3b8"
        />
      )}

      {/* Перечень */}
      {hasSourcePipeline && sourceMetaStage && (
        <ResultFilesSection
          stage={sourceMetaStage}
          taskId={listTask!.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label={listTypeLabel}
          color="#7c3aed"
          fallbackSlot="result"
          defaultExpanded={false}
        />
      )}

      {/* Полнота (если есть) */}
      {completenessTask && completenessTask.status === 'completed' && completenessMetaStage && (
        <ResultFilesSection
          stage={completenessMetaStage}
          taskId={completenessTask.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Полнота"
          color="#3b82f6"
          fallbackSlot="result"
          defaultExpanded={false}
        />
      )}

      {/* Смета (если есть из стадии Смета) */}
      {estimateTask && estimateTask.status === 'completed' && estimateMetaStage && (
        <ResultFilesSection
          stage={estimateMetaStage}
          taskId={estimateTask.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Смета"
          color="#0f766e"
          fallbackSlot="result"
          defaultExpanded={false}
        />
      )}

      {/* Оптимизация */}
      <TaskStatusBadge task={task} />

      {canStart && (
        <div style={{ marginTop: '8px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '10px' }}>
          <div style={{ marginBottom: '8px' }}>
            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>Использовать смету из предыдущей стадии:</div>
            <ActionButton onClick={handleUsePrevious} disabled={!estimateCompleted || submitting}>
              {submitting ? 'Запускаю…' : 'Использовать смету'}
            </ActionButton>
            {!estimateCompleted && (
              <div style={{ color: '#94a3b8', fontSize: '12px', marginTop: '4px' }}>
                Сначала создайте смету на стадии «Смета»
              </div>
            )}
          </div>
          <div>
            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>Или загрузить смету с ПК:</div>
            <div style={{ overflow: 'hidden', maxWidth: '100%' }}>
              <input ref={fileRef} type="file" style={{ fontSize: '13px', maxWidth: '100%' }} onChange={handleFileChange} />
            </div>
            {fileError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileError}</div>}
            {file && (
              <div style={{ marginTop: '6px' }}>
                <ActionButton onClick={handleUpload} disabled={submitting}>
                  {submitting ? 'Запускаю…' : 'Загрузить и оптимизировать'}
                </ActionButton>
              </div>
            )}
          </div>
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        <div style={{ marginTop: '8px' }}>
          {mainFile ? (
            <div style={{ marginBottom: '6px' }}>
              <FileRowCompact
                name={mainFile.file_name}
                size={mainFile.size_bytes}
                mime={mainFile.mime_type}
                date={formatDate(mainFile.created_at)}
                onDownload={() => downloadSlotFileById(task.id, mainFile.slot)}
                onOpenTask={navigateToCard}
                onOpenEditor={() => onOpenEditor({ taskId: task.id, title: 'Оптимизация сметы' })}
              />
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '4px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(task.id, 'optimized')} title="Скачать оптимизацию" />
              <ViewBtn onClick={() => onOpenEditor({ taskId: task.id, title: 'Оптимизация сметы', fileSlot: 'optimized', taskType: task.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть карточку" />
            </div>
          )}

          {archiveFiles.length > 0 && (
            <div>
              <button
                onClick={() => setArchiveExpanded(e => !e)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '4px',
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: '#64748b', fontSize: '11px', padding: '2px 0', marginBottom: '4px',
                }}
              >
                {archiveExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                Архив версий ({archiveFiles.length})
              </button>
              {archiveExpanded && archiveFiles.map(f => (
                <div key={f.result_id} style={{ marginBottom: '3px' }}>
                  <FileRowCompact
                    name={f.file_name}
                    size={f.size_bytes}
                    mime={f.mime_type}
                    date={formatDate(f.created_at)}
                    onDownload={() => downloadSlotFileById(task.id, f.slot)}
                    onOpenTask={navigateToCard}
                    onOpenEditor={() => onOpenEditor({ taskId: task.id, title: 'Оптимизация сметы' })}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CardStageContent — диспетчер с загрузкой filesMeta
// ---------------------------------------------------------------------------
export function CardStageContent({ card }: { card: WorkflowCard }) {
  const [filesMeta, setFilesMeta] = useState<CardDetail | null>(null)
  const metaFetching = useRef(false)
  const [editorModal, setEditorModal] = useState<EditorModalState | null>(null)

  const fetchMeta = useCallback(async () => {
    if (metaFetching.current) return
    metaFetching.current = true
    try {
      const data = await getCardFilesMeta(card.id)
      setFilesMeta(data)
    } catch {
      // Молча игнорируем: fallback на упрощённый вид
    } finally {
      metaFetching.current = false
    }
  }, [card.id])

  useEffect(() => {
    fetchMeta()
  }, [fetchMeta])

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'estimate-saved') {
        fetchMeta()
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [fetchMeta])

  const stageProps: StageProps = { card, filesMeta, onOpenEditor: setEditorModal }

  return (
    <>
      {(() => {
        switch (card.stage) {
          case 'list':         return <ListStage {...stageProps} />
          case 'completeness': return <CompletenessStage {...stageProps} />
          case 'estimate':     return <EstimateStage {...stageProps} />
          case 'optimization': return <OptimizationStage {...stageProps} />
          default:             return null
        }
      })()}

      {editorModal && (
        editorModal.taskType && GENERIC_EDITOR_TASK_TYPES.has(editorModal.taskType)
          ? (
            <GenericEditorModal
              taskId={editorModal.taskId}
              title={editorModal.title}
              fileSlot={editorModal.fileSlot}
              fileIndex={editorModal.fileIndex}
              readOnly={editorModal.readOnly}
              onClose={() => setEditorModal(null)}
              onSaved={fetchMeta}
            />
          )
          : (
            <EstimateEditorModal
              taskId={editorModal.taskId}
              title={editorModal.title}
              fileSlot={editorModal.fileSlot}
              fileIndex={editorModal.fileIndex}
              readOnly={editorModal.readOnly}
              onClose={() => setEditorModal(null)}
              onSaved={fetchMeta}
            />
          )
      )}
    </>
  )
}
