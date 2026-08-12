import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ChevronDown, ChevronUp, Download, Edit3, Eye, FileText } from 'lucide-react'
import { KanbanStage, TaskBrief, WorkflowCard } from '../../types/workflow'
import { describeEta } from '../../utils/eta'
import { useKanbanStore } from '../../stores/kanban'
import { downloadSlotFile } from '../../api/projects'
import { restartTask, resumeTask } from '../../api/tasks'
import { formatApiDetail } from '../../utils/formatError'
import {
  CardDetail,
  StageDetail,
  downloadInputFileById,
  downloadSlotFileById,
  getCardFilesMeta,
} from '../../api/workflowCards'
import { TaskStatusBadge } from './TaskStatusBadge'
import { LumaSpin } from '../ui/LumaSpin'
import { ProgressCounter } from './ProgressCounter'
import { kindFromTaskType } from '../../api/documents'
import UsageChips from '../card/UsageChips'
import { stageUsage } from '../../utils/usageMetrics'
// Соответствие «стадия → задача», состояния узлов и их подписи — одни на весь
// проект, живут рядом со степпером.
import {
  NodeIcon,
  PIPELINE_STAGES,
  STATE_STYLE,
  computeNodeState,
  defaultStage,
  stageCaption,
  stageTask,
} from '../pipeline/PipelineStepper'
import { computeGuard } from '../../stores/kanban'

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
/**
 * Какой документ открыть страницей редактора.
 *
 * Адресуется карточкой и типом документа, а не задачей: заголовок и имя файла
 * страница собирает сама, поэтому здесь только то, чего ей неоткуда взять —
 * тип задачи (из него тип документа) и слот файла.
 */
interface EditorTarget {
  /** `input` — исходный файл заказчика (только просмотр). */
  fileSlot?: string
  /** Номер входного файла, когда их несколько. */
  fileIndex?: number
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

/** Прогноз готовности активной задачи — строкой под счётчиком прогресса. */
function EtaLine({ task }: { task: TaskBrief }) {
  const view = describeEta(task.eta, task.status)
  if (!view) return null
  return (
    <span
      data-testid="card-eta"
      title={view.hint}
      style={{ display: 'block', fontSize: '10px', color: '#64748b', lineHeight: '1.4' }}
    >
      Готово {view.ready}
      {view.start ? ` · ${view.start}` : ''}
    </span>
  )
}

function ArrowBtn({ onClick, title = 'Открыть смету' }: { onClick: () => void; title?: string }) {
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
            title="Открыть смету"
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
  color, label, defaultExpanded = true, task, children,
}: {
  color: string
  label: string
  defaultExpanded?: boolean
  /** Задача стадии: её затраты показываются справа в заголовке секции. */
  task?: TaskBrief | null
  children: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const usage = stageUsage(task?.usage)
  return (
    <div style={{ marginBottom: '10px', paddingBottom: '10px', borderBottom: '1px solid #f1f5f9' }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex', alignItems: 'center', gap: '8px', width: '100%',
          background: 'none', border: 'none', cursor: 'pointer',
          padding: '0 0 4px', marginBottom: expanded ? '4px' : 0,
        }}
      >
        <span style={{ fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color, textAlign: 'left' }}>
          {label}
        </span>
        {/* Затраты стадии — рядом с её названием: цифра нужна там, где на неё
            смотрят, а не на отдельном экране. */}
        <span style={{ flex: 1, display: 'flex', justifyContent: 'flex-end', minWidth: 0 }}>
          <UsageChips usage={usage} />
        </span>
        {expanded ? <ChevronUp size={11} color="#94a3b8" /> : <ChevronDown size={11} color="#94a3b8" />}
      </button>
      {expanded && children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CurrentStageUsage — затраты стадии, которую показывает карточка
// ---------------------------------------------------------------------------
const STAGE_LABEL: Record<KanbanStage, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

const STAGE_COLOR: Record<KanbanStage, string> = {
  list: '#7c3aed',
  completeness: '#3b82f6',
  estimate: '#0f766e',
  optimization: '#c2410c',
}

function CurrentStageUsage({ card }: { card: WorkflowCard }) {
  const task = stageTask(card, card.stage)
  const usage = stageUsage(task?.usage)
  if (!usage.hasData) return null
  return (
    <div
      style={{
        display: 'flex', alignItems: 'baseline', gap: '8px',
        marginTop: '10px', paddingTop: '8px', borderTop: '1px solid #f1f5f9',
      }}
    >
      <span style={{
        fontSize: '10px', fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: '0.05em', color: STAGE_COLOR[card.stage],
      }}>
        {STAGE_LABEL[card.stage]}
      </span>
      <span style={{ flex: 1, display: 'flex', justifyContent: 'flex-end', minWidth: 0 }}>
        <UsageChips usage={usage} />
      </span>
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
  onOpenEditor: (state: EditorTarget) => void
  onRestart: (taskId: string) => Promise<void>
  onResume: (taskId: string) => Promise<void>
}

/**
 * Тело стадии — её собственное содержимое, без секций предыдущих стадий.
 *
 * Два вида показывают одни и те же стадии по-разному: канбан и страница сметы
 * рисуют одну стадию с историей предыдущих, список смет проекта — все четыре
 * стадии аккордеоном. Тело общее, иначе формы запуска, пауза, ошибки и архив
 * версий разошлись бы между видами.
 *
 * `showLabel` — где название стадии пишет само тело (канбан), а где его берёт
 * на себя заголовок раскрывающейся секции (аккордеон).
 */
type StageBodyProps = StageProps & { showLabel?: boolean }

function RestartBtn({ taskId, onRestart }: { taskId: string; onRestart: (id: string) => Promise<void> }) {
  const [loading, setLoading] = useState(false)
  return (
    <button
      onClick={async () => { setLoading(true); try { await onRestart(taskId) } finally { setLoading(false) } }}
      disabled={loading}
      style={{
        marginTop: '6px',
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        background: loading ? '#e0f2fe' : '#f0f9ff',
        color: '#0369a1', border: '1px solid #7dd3fc',
        borderRadius: '6px', padding: '4px 10px',
        fontSize: '11px', fontWeight: 600,
        cursor: loading ? 'not-allowed' : 'pointer',
      }}
    >
      {loading ? 'Запускаю…' : '↺ Перезапустить'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// PausedBlock — задача остановлена по балансу API
// ---------------------------------------------------------------------------
/**
 * Пауза — не ошибка: прогресс сохранён, и поллер возобновит задачу сам, как
 * только баланс пополнят. Но ждать десять минут не всегда уместно, поэтому
 * рядом с объяснением стоит кнопка немедленного продолжения — тот же
 * `/tasks/{id}/resume`, что и на странице задачи.
 */
function PausedBlock({ taskId, onResume }: { taskId: string; onResume: (id: string) => Promise<void> }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleClick = async () => {
    setLoading(true)
    setError(null)
    try {
      await onResume(taskId)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(formatApiDetail(detail, 'Не удалось возобновить задачу. Попробуйте ещё раз.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      data-testid="kanban-paused"
      style={{
        marginTop: '6px',
        background: '#fffbeb', border: '1px solid #fcd34d',
        borderRadius: '8px', padding: '8px 10px',
      }}
    >
      <div style={{ fontSize: '11px', color: '#92400e', lineHeight: 1.45 }}>
        Баланс API Anthropic исчерпан. Прогресс сохранён — задача продолжится сама
        после пополнения счёта, уже посчитанное заново не считается.
      </div>
      {error && (
        <div style={{ color: '#dc2626', fontSize: '11px', marginTop: '4px' }}>{error}</div>
      )}
      <button
        onClick={handleClick}
        disabled={loading}
        style={{
          marginTop: '6px',
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          background: loading ? '#fcd34d' : '#d97706',
          color: '#fff', border: 'none',
          borderRadius: '6px', padding: '4px 10px',
          fontSize: '11px', fontWeight: 600,
          cursor: loading ? 'not-allowed' : 'pointer',
        }}
      >
        {loading ? 'Возобновляю…' : '▸ Продолжить сейчас'}
      </button>
    </div>
  )
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
  onOpenEditor: (state: EditorTarget) => void
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
              fileSlot: 'input',
              fileIndex: f.index,
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
  task,
  taskId,
  navigateToCard,
  onOpenEditor,
  label,
  color,
  fallbackSlot = 'result',
  defaultExpanded = false,
  footer,
}: {
  stage: StageDetail
  /** Задача стадии — из неё берутся затраты для заголовка секции. */
  task?: TaskBrief | null
  taskId: string
  navigateToCard: () => void
  onOpenEditor: (state: EditorTarget) => void
  label: string
  color: string
  fallbackSlot?: string
  defaultExpanded?: boolean
  /** Доп. блок внутри секции — например, запуск задачи следующей стадии. */
  footer?: React.ReactNode
}) {
  return (
    <CollapsibleSection color={color} label={label} defaultExpanded={defaultExpanded} task={task}>
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
          <ViewBtn onClick={() => onOpenEditor({ fileSlot: fallbackSlot, taskType: stage.task_type })} title="Открыть онлайн" />
          <ArrowBtn onClick={navigateToCard} />
        </div>
      )}
      {footer}
    </CollapsibleSection>
  )
}

// ---------------------------------------------------------------------------
// Stage: Перечень
// ---------------------------------------------------------------------------
function ListStageBody({ card, filesMeta, onOpenEditor, onRestart, onResume, showLabel = true }: StageBodyProps) {
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

  // Идём прямо на страницу сметы, на нужный этап: адрес задачи туда же
  // и редиректит, но лишним переходом и морганием экрана.
  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=list`)

  useEffect(() => {
    if (pending && files.length === 0) {
      setTaskType(pending.task_type)
      setFiles(pending.files)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  const effectiveType = (task?.task_type ?? taskType) as string
  const typeLabel = TYPE_LABEL[effectiveType] ?? effectiveType
  const label = showLabel ? <SectionLabel color="#7c3aed">{typeLabel}</SectionLabel> : null

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
        {label}
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
        {label}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', flexWrap: 'nowrap' }}>
          <LumaSpin size="sm" color="#d97706" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: 'block', fontSize: '11px', color: '#92400e', whiteSpace: 'normal', lineHeight: '1.4', paddingTop: '1px' }}>
              {task.progress_message || 'В очереди…'}
            </span>
            <ProgressCounter data={task.progress_data} />
            <EtaLine task={task} />
          </div>
          <ArrowBtn onClick={navigateToCard} />
        </div>
      </div>
    )
  }

  if (task.status === 'completed') {
    return (
      <div>
        {label}

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
                    fileSlot: 'input',
                    fileIndex: f.index,
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
              <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'result', taskType: task.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
            </div>
          )
        )}

        {showWarning && nextStage && (
          <ManualEditWarning editedAt={sourceStage!.manually_edited_at!} prevStageName="Перечень" />
        )}
        <RestartBtn taskId={task.id} onRestart={onRestart} />
      </div>
    )
  }

  // Пауза по балансу: форму повторного запуска не показываем — она создала бы
  // задачу с нуля вместо продолжения с сохранённого чекпоинта.
  if (task.status === 'paused') {
    return (
      <div>
        {label}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
          <TaskStatusBadge task={task} />
          <ArrowBtn onClick={navigateToCard} />
        </div>
        <PausedBlock taskId={task.id} onResume={onResume} />
      </div>
    )
  }

  // Ошибка / отменено
  return (
    <div>
      {label}
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
function CompletenessStage({ card, filesMeta, onOpenEditor, onRestart, onResume }: StageProps) {
  const navigate = useNavigate()
  const listTask = card.list_task

  // Идём прямо на страницу сметы, на нужный этап: адрес задачи туда же
  // и редиректит, но лишним переходом и морганием экрана.
  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=completeness`)

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const sourceStage = filesMeta?.source_stage
  const completenessStage = filesMeta?.completeness_stage

  const listEditedWarning = sourceStage?.manually_edited_at && completenessStage
    ? wasEditedBefore(sourceStage.manually_edited_at, completenessStage.task_created_at)
    : false

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
        <CollapsibleSection color="#7c3aed" label={listTypeLabel} defaultExpanded={!!listEditedWarning} task={listTask}>
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
              <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'result', taskType: listTask.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
            </div>
          )}
          {listEditedWarning && (
            <ManualEditWarning editedAt={sourceStage!.manually_edited_at!} prevStageName="Перечень" />
          )}
        </CollapsibleSection>
      )}

      <CompletenessStageBody
        card={card}
        filesMeta={filesMeta}
        onOpenEditor={onOpenEditor}
        onRestart={onRestart}
        onResume={onResume}
      />
    </div>
  )
}

function CompletenessStageBody({ card, filesMeta, onOpenEditor, onRestart, onResume, showLabel = true }: StageBodyProps) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const navigate = useNavigate()
  const submitting = submittingCardIds.has(card.id)
  const task = card.completeness_task

  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=completeness`)

  const getCompletenessType = () =>
    card.list_task?.task_type === 'LIST_FROM_PROJECT'
      ? 'CHECK_PROJECT_COMPLETENESS'
      : 'CHECK_LIST_COMPLETENESS'

  const completenessStage = filesMeta?.completeness_stage
  const nextStage: StageDetail | null = filesMeta?.estimate_stage ?? filesMeta?.optimization_stage ?? null

  const completenessEditedWarning = completenessStage?.manually_edited_at && nextStage
    ? wasEditedBefore(completenessStage.manually_edited_at, nextStage.task_created_at)
    : false

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: '10px', fontWeight: 700, textTransform: 'uppercase',
    letterSpacing: '0.05em', marginBottom: '4px',
  }
  const label = (text: string) =>
    showLabel ? <div style={{ ...sectionLabelStyle, color: '#3b82f6' }}>{text}</div> : null

  return (
    <div>
      {task === null && (
        <ActionButton onClick={async () => { await startTask(card.id, { task_type: getCompletenessType() }) }} disabled={submitting}>
          {submitting ? 'Запускаю…' : 'Запустить проверку полноты'}
        </ActionButton>
      )}

      {task !== null && (task.status === 'pending' || task.status === 'processing') && (
        <div>
          {label('Проверка полноты')}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
            <LumaSpin size="sm" color="#d97706" />
            <div style={{ flex: 1, minWidth: 0 }}>
              {task.progress_message && (
                <span style={{ display: 'block', fontSize: '11px', color: '#92400e', whiteSpace: 'normal', lineHeight: '1.4' }}>
                  {task.progress_message}
                </span>
              )}
              <ProgressCounter data={task.progress_data} />
            <EtaLine task={task} />
            </div>
            <ArrowBtn onClick={navigateToCard} />
          </div>
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        <div>
          {label('Полнота')}
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
              <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'result', taskType: task.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
            </div>
          )}
          {completenessEditedWarning && (
            <ManualEditWarning editedAt={completenessStage!.manually_edited_at!} prevStageName="Проверка полноты" />
          )}
          <RestartBtn taskId={task.id} onRestart={onRestart} />
        </div>
      )}

      {task !== null && task.status === 'paused' && (
        <div>
          {label('Проверка полноты')}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <TaskStatusBadge task={task} />
            <ArrowBtn onClick={navigateToCard} />
          </div>
          <PausedBlock taskId={task.id} onResume={onResume} />
        </div>
      )}

      {task !== null && (task.status === 'failed' || task.status === 'cancelled') && (
        <div>
          {label('Проверка полноты')}
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
function EstimateStage({ card, filesMeta, onOpenEditor, onRestart, onResume }: StageProps) {
  const navigate = useNavigate()
  const listTask = card.list_task
  const completenessTask = card.completeness_task

  // Идём прямо на страницу сметы, на нужный этап: адрес задачи туда же
  // и редиректит, но лишним переходом и морганием экрана.
  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=estimate`)

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const sourceMetaStage = filesMeta?.source_stage
  const completenessMetaStage = filesMeta?.completeness_stage
  const estimateMetaStage = filesMeta?.estimate_stage

  const listEditedWarning = sourceMetaStage?.manually_edited_at && estimateMetaStage
    ? wasEditedBefore(sourceMetaStage.manually_edited_at, estimateMetaStage.task_created_at)
    : false

  const completenessEditedWarning = completenessMetaStage?.manually_edited_at && estimateMetaStage
    ? wasEditedBefore(completenessMetaStage.manually_edited_at, estimateMetaStage.task_created_at)
    : false

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
        <CollapsibleSection color="#7c3aed" label={listTypeLabel} defaultExpanded={!!listEditedWarning} task={listTask}>
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
              <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'result', taskType: listTask.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
            </div>
          )}
          {listEditedWarning && (
            <ManualEditWarning editedAt={sourceMetaStage!.manually_edited_at!} prevStageName="Перечень" />
          )}
        </CollapsibleSection>
      )}

      {/* Полнота (если есть) */}
      {completenessTask !== null && completenessTask.status === 'completed' && (
        <CollapsibleSection color="#3b82f6" label="Полнота" defaultExpanded={!!completenessEditedWarning} task={completenessTask}>
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
              <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'result', taskType: completenessTask.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
            </div>
          )}
          {completenessEditedWarning && (
            <ManualEditWarning editedAt={completenessMetaStage!.manually_edited_at!} prevStageName="Проверка полноты" />
          )}
        </CollapsibleSection>
      )}

      <EstimateStageBody
        card={card}
        filesMeta={filesMeta}
        onOpenEditor={onOpenEditor}
        onRestart={onRestart}
        onResume={onResume}
      />
    </div>
  )
}

function EstimateStageBody({ card, filesMeta, onOpenEditor, onRestart, onResume, showLabel = true }: StageBodyProps) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const navigate = useNavigate()
  const submitting = submittingCardIds.has(card.id)
  const task = card.estimate_task
  const listTask = card.list_task
  const completenessTask = card.completeness_task

  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=estimate`)

  const listCompleted = listTask?.status === 'completed'
  const completenessCompleted = completenessTask?.status === 'completed'

  const [sourceStageNum, setSourceStageNum] = useState<1 | 2>(completenessCompleted ? 2 : 1)

  const noSource = !listCompleted && !completenessCompleted

  const estimateMetaStage = filesMeta?.estimate_stage
  const nextStage: StageDetail | null = filesMeta?.optimization_stage ?? null

  const estimateEditedWarning = estimateMetaStage?.manually_edited_at && nextStage
    ? wasEditedBefore(estimateMetaStage.manually_edited_at, nextStage.task_created_at)
    : false

  const canCreate = task === null || task.status === 'failed' || task.status === 'cancelled'

  const handleCreate = async () => {
    await startTask(card.id, { task_type: 'ESTIMATE_FROM_LIST', source_stage: sourceStageNum })
  }

  return (
    <div>
      {showLabel && (
        <div style={{
          fontSize: '10px', fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.05em', marginBottom: '4px', color: '#0f766e',
        }}>
          Смета из перечня
        </div>
      )}

      {task !== null && (task.status === 'pending' || task.status === 'processing') && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', flexWrap: 'nowrap' }}>
          <LumaSpin size="sm" color="#d97706" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: 'block', fontSize: '11px', color: '#92400e', whiteSpace: 'normal', lineHeight: '1.4', paddingTop: '1px' }}>
              {task.progress_message || 'В очереди…'}
            </span>
            <ProgressCounter data={task.progress_data} />
            <EtaLine task={task} />
          </div>
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
            <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'result', taskType: task.task_type })} title="Открыть онлайн" />
            <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
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

      {task !== null && task.status === 'paused' && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <TaskStatusBadge task={task} />
            <ArrowBtn onClick={navigateToCard} />
          </div>
          <PausedBlock taskId={task.id} onResume={onResume} />
        </div>
      )}

      {estimateEditedWarning && nextStage && (
        <ManualEditWarning editedAt={estimateMetaStage!.manually_edited_at!} prevStageName="Смета из перечня" />
      )}

      {task !== null && task.status === 'completed' && (
        <RestartBtn taskId={task.id} onRestart={onRestart} />
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
function OptimizationStage({ card, filesMeta, onOpenEditor, onRestart, onResume }: StageProps) {
  const navigate = useNavigate()
  const task = card.optimization_task
  const listTask = card.list_task
  const completenessTask = card.completeness_task
  const estimateTask = card.estimate_task

  // Идём прямо на страницу сметы, на нужный этап: адрес задачи туда же
  // и редиректит, но лишним переходом и морганием экрана.
  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=optimization`)

  const sourceMetaStage = filesMeta?.source_stage
  const completenessMetaStage = filesMeta?.completeness_stage
  const estimateMetaStage = filesMeta?.estimate_stage

  const hasSourcePipeline = !!(listTask && listTask.status === 'completed')

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const canStart = task === null || task.status === 'failed' || task.status === 'cancelled'
  // Секция «Смета» показывается, только если смета уже готова на предыдущей стадии.
  const hasEstimateSection = !!(estimateTask && estimateTask.status === 'completed' && estimateMetaStage)
  // Блок запуска живёт внутри секции «Смета» — прямо под сметой, которую оптимизируем.
  // Готового результата в этот момент быть не может (`canStart` и «завершено»
  // исключают друг друга), поэтому в секцию уезжает всё тело стадии целиком.
  const nested = canStart && hasEstimateSection

  const body = (
    <OptimizationStageBody
      card={card}
      filesMeta={filesMeta}
      onOpenEditor={onOpenEditor}
      onRestart={onRestart}
      onResume={onResume}
      nested={nested}
    />
  )

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
          task={listTask}
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
          task={completenessTask}
          taskId={completenessTask.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Полнота"
          color="#3b82f6"
          fallbackSlot="result"
          defaultExpanded={false}
        />
      )}

      {/* Смета (если есть из стадии Смета) — блок запуска оптимизации живёт внутри */}
      {hasEstimateSection && (
        <ResultFilesSection
          stage={estimateMetaStage!}
          task={estimateTask}
          taskId={estimateTask!.id}
          navigateToCard={navigateToCard}
          onOpenEditor={onOpenEditor}
          label="Смета"
          color="#0f766e"
          fallbackSlot="result"
          defaultExpanded={nested}
          footer={nested ? body : undefined}
        />
      )}

      {/* Оптимизация — на уровне стадии, если смета из предыдущей стадии недоступна */}
      {!nested && body}
    </div>
  )
}

/**
 * Тело стадии оптимизации: блок запуска и результат.
 *
 * `nested` — тело показано внутри секции «Смета» (канбан): тогда у него своя
 * шапка «Оптимизация» и отбивка сверху. В аккордеоне стадий шапку даёт сам
 * заголовок секции, и отбивка не нужна.
 */
function OptimizationStageBody({
  card, filesMeta, onOpenEditor, onRestart, onResume, nested = false,
}: StageProps & { nested?: boolean }) {
  const navigate = useNavigate()
  const { startTask, submittingCardIds } = useKanbanStore()
  const submitting = submittingCardIds.has(card.id)
  const task = card.optimization_task
  const estimateTask = card.estimate_task
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [archiveExpanded, setArchiveExpanded] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const navigateToCard = () => navigate(`/projects/${card.project_id}/cards/${card.id}?stage=optimization`)

  const estimateCompleted = estimateTask?.status === 'completed'
  const optimizationMeta = filesMeta?.optimization_stage

  const mainFile = optimizationMeta?.result_files.find(f => f.slot === 'optimized') ?? optimizationMeta?.result_files[0]
  const archiveFiles = optimizationMeta?.result_files.filter(f => f.slot !== 'optimized' && f.slot !== 'source') ?? []

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

  const launchBlock = (
    <div style={nested
      ? { marginTop: '10px', paddingTop: '10px', borderTop: '1px solid #e2e8f0' }
      : undefined}
    >
      {nested && (
        <div style={{ fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#c2410c', marginBottom: '4px' }}>
          Оптимизация
        </div>
      )}
      <TaskStatusBadge task={task} />
      {task !== null && task.status === 'paused' && (
        <PausedBlock taskId={task.id} onResume={onResume} />
      )}
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
    </div>
  )

  return (
    <div>
      {launchBlock}

      {task !== null && task.status === 'completed' && (
        <div style={{ marginTop: '8px' }}>
          <RestartBtn taskId={task.id} onRestart={onRestart} />
          {mainFile ? (
            <div style={{ marginBottom: '6px' }}>
              <FileRowCompact
                name={mainFile.file_name}
                size={mainFile.size_bytes}
                mime={mainFile.mime_type}
                date={formatDate(mainFile.created_at)}
                onDownload={() => downloadSlotFileById(task.id, mainFile.slot)}
                onOpenTask={navigateToCard}
                onOpenEditor={() => onOpenEditor({ fileSlot: 'optimized', taskType: task.task_type })}
              />
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '4px' }}>
              <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
              <DownloadBtn onClick={() => safeDownload(task.id, 'optimized')} title="Скачать оптимизацию" />
              <ViewBtn onClick={() => onOpenEditor({ fileSlot: 'optimized', taskType: task.task_type })} title="Открыть онлайн" />
              <ArrowBtn onClick={navigateToCard} title="Открыть смету" />
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
                    onOpenEditor={() => onOpenEditor({ fileSlot: 'optimized', taskType: task.task_type })}
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
/**
 * Метаданные файлов стадий, переход в редактор и перезапуск/продолжение задачи.
 *
 * Один загрузчик на оба вида стадий (диспетчер канбана и аккордеон списка
 * смет): запрос `getCardFilesMeta` и обновление после сохранения в редакторе
 * должны работать одинаково, разойтись им нельзя.
 */
function useCardStageProps(card: WorkflowCard) {
  // Через селектор: хук работает и вне доски (список смет, карточка),
  // подписка на весь стор дёргала бы его на каждый цикл опроса карточек.
  const fetchCards = useKanbanStore(s => s.fetchCards)
  const navigate = useNavigate()
  const [filesMeta, setFilesMeta] = useState<CardDetail | null>(null)
  const metaFetching = useRef(false)

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

  const handleRestart = useCallback(async (taskId: string) => {
    await restartTask(taskId)
    await fetchMeta()
  }, [fetchMeta])

  // Доска опрашивается раз в пять секунд, но после ручного «Продолжить сейчас»
  // ждать смены статуса неприятно — перечитываем карточки сразу.
  const handleResume = useCallback(async (taskId: string) => {
    await resumeTask(taskId)
    await fetchMeta()
    await fetchCards(card.project_id)
  }, [fetchMeta, fetchCards, card.project_id])

  // Документ открывается страницей, а не окном поверх экрана: у таблицы есть
  // адрес, её можно отправить коллеге, а «Назад» браузера её закрывает.
  // Заголовок странице не передаём — она соберёт его сама из метаданных файлов,
  // иначе он жил бы в адресной строке и расходился с содержимым по ссылке.
  const openEditor = useCallback((target: EditorTarget) => {
    const kind = target.taskType ? kindFromTaskType(target.taskType) : null
    if (!kind) return
    const query = new URLSearchParams()
    if (target.fileSlot) query.set('slot', target.fileSlot)
    if (target.fileIndex !== undefined) query.set('index', String(target.fileIndex))
    const suffix = query.toString()
    navigate(`/projects/${card.project_id}/cards/${card.id}/document/${kind}${suffix ? `?${suffix}` : ''}`)
  }, [navigate, card.project_id, card.id])

  const stageProps: StageProps = {
    card, filesMeta, onOpenEditor: openEditor, onRestart: handleRestart, onResume: handleResume,
  }

  return { stageProps }
}

// ---------------------------------------------------------------------------
// CardStagesAccordion — все четыре стадии секциями (список смет проекта)
// ---------------------------------------------------------------------------

/** Название секции стадии. У перечня — с типом: «из проекта» и «из Гранд-сметы»
 *  готовятся по-разному, и в списке смет это первое, что нужно видеть. */
function stageSectionLabel(card: WorkflowCard, stage: KanbanStage): string {
  if (stage !== 'list') return STAGE_LABEL[stage]
  const type = card.list_task?.task_type
  return (type && TYPE_LABEL[type]) || STAGE_LABEL.list
}

function StageSection({
  card, stage, index, defaultExpanded, children,
}: {
  card: WorkflowCard
  stage: KanbanStage
  index: number
  defaultExpanded: boolean
  children: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const state = computeNodeState(card, stage)
  const style = STATE_STYLE[state]
  const locked = state === 'lock'
  const label = stageSectionLabel(card, stage)
  const caption = stageCaption(card, stage)
  // Заблокированную стадию не раскрываем: внутри форма запуска, а гейт всё
  // равно не пустит. Причина — в подсказке заголовка.
  const reason = locked ? computeGuard(card, stage).message : caption
  const open = expanded && !locked
  const usage = stageUsage(stageTask(card, stage)?.usage)

  return (
    <div style={{ borderTop: '1px solid #f1f5f9' }}>
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        disabled={locked}
        title={`${label}: ${reason}`}
        style={{
          display: 'flex', alignItems: 'center', gap: '7px', width: '100%',
          background: 'none', border: 'none', padding: '7px 0',
          cursor: locked ? 'not-allowed' : 'pointer', textAlign: 'left',
        }}
      >
        <span
          style={{
            width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: style.fill, border: `2px solid ${style.ring}`,
          }}
        >
          <NodeIcon state={state} index={index} scale={0.65} />
        </span>
        <span style={{
          fontSize: '10px', fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.05em', color: STAGE_COLOR[stage], minWidth: 0,
        }}>
          {label}
        </span>
        {caption && (
          <span style={{ fontSize: '10px', color: style.label, flexShrink: 0 }}>{caption}</span>
        )}
        <span style={{ flex: 1 }} />
        {!locked && (expanded ? <ChevronUp size={12} color="#94a3b8" /> : <ChevronDown size={12} color="#94a3b8" />)}
      </button>

      {/* Затраты стадии — под её названием: в 1/3 ширины они не влезают
          в одну строку с заголовком, а прятать их за раскрытием нельзя —
          цифру смотрят, не открывая стадию. */}
      {usage.hasData && (
        <div style={{ padding: '0 0 6px 25px' }}>
          <UsageChips usage={usage} />
        </div>
      )}

      {open && <div style={{ paddingBottom: '8px' }}>{children}</div>}
    </div>
  )
}

/**
 * Все четыре стадии сметы секциями — вид списка смет проекта.
 *
 * Раскрыта активная стадия (`defaultStage`), остальные свёрнуты. Дорожки-
 * таймлайна нет: состояние стадии показывает кружок в её заголовке, и второго
 * места, где то же самое написано другими словами, быть не должно.
 */
export function CardStagesAccordion({ card }: { card: WorkflowCard }) {
  const { stageProps } = useCardStageProps(card)
  // Раскрытая стадия выбирается один раз при монтировании: карточки
  // опрашиваются каждые 5 секунд, и пересчёт схлопывал бы секцию под руками.
  const [initialStage] = useState(() => defaultStage(card))

  const body: Record<KanbanStage, React.ReactNode> = {
    list: <ListStageBody {...stageProps} showLabel={false} />,
    completeness: <CompletenessStageBody {...stageProps} showLabel={false} />,
    estimate: <EstimateStageBody {...stageProps} showLabel={false} />,
    optimization: <OptimizationStageBody {...stageProps} />,
  }

  return (
    <div>
      {PIPELINE_STAGES.map((stage, i) => (
        <StageSection
          key={stage}
          card={card}
          stage={stage}
          index={i}
          defaultExpanded={stage === initialStage}
        >
          {body[stage]}
        </StageSection>
      ))}
    </div>
  )
}

export function CardStageContent({ card }: { card: WorkflowCard }) {
  const { stageProps } = useCardStageProps(card)

  return (
    <>
      {(() => {
        switch (card.stage) {
          case 'list':         return <ListStageBody {...stageProps} />
          case 'completeness': return <CompletenessStage {...stageProps} />
          case 'estimate':     return <EstimateStage {...stageProps} />
          case 'optimization': return <OptimizationStage {...stageProps} />
          default:             return null
        }
      })()}

      {/* Затраты текущей стадии. У предыдущих стадий цифры стоят в заголовках их
          свёрнутых секций; у текущей своей секции нет — её содержимое рисуется
          по-разному в пяти состояниях (не запущена, идёт, пауза, ошибка,
          готово), и вставлять чипы в каждую ветку значило бы пять шансов
          разойтись. Одна строка внизу закрывает все состояния сразу. */}
      <CurrentStageUsage card={card} />

    </>
  )
}
