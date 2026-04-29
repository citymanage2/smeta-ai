import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { WorkflowCard } from '../../types/workflow'
import { useKanbanStore } from '../../stores/kanban'
import { downloadSlotFile } from '../../api/projects'
import { TaskStatusBadge } from './TaskStatusBadge'
import { TaskDetailModal } from '../TaskDetailModal'
import { LumaSpin } from '../ui/LumaSpin'

function safeDownload(taskId: string, slot: string) {
  downloadSlotFile(taskId, slot)
}

const FILE_SIZE_LIMIT = 50 * 1024 * 1024

interface Props {
  card: WorkflowCard
}

function ActionButton({
  onClick,
  disabled,
  variant = 'primary',
  children,
}: {
  onClick: () => void
  disabled?: boolean
  variant?: 'primary' | 'secondary' | 'outline'
  children: React.ReactNode
}) {
  const base: React.CSSProperties = {
    border: 'none',
    borderRadius: '6px',
    padding: '5px 12px',
    fontSize: '13px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    marginTop: '8px',
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

function ArrowBtn({ onClick, title = 'Посмотреть задачу' }: { onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        color: '#94a3b8',
        padding: '2px 5px',
        borderRadius: '4px',
        fontSize: '13px',
        display: 'flex',
        alignItems: 'center',
        flexShrink: 0,
        lineHeight: 1,
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget as HTMLElement
        el.style.color = '#3b82f6'
        el.style.background = '#eff6ff'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget as HTMLElement
        el.style.color = '#94a3b8'
        el.style.background = 'none'
      }}
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
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        color: '#94a3b8',
        padding: '2px 5px',
        borderRadius: '4px',
        fontSize: '14px',
        display: 'flex',
        alignItems: 'center',
        flexShrink: 0,
        lineHeight: 1,
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#94a3b8' }}
    >
      ⬇
    </button>
  )
}

function Spinner() {
  return (
    <span style={{
      display: 'inline-block',
      width: '11px',
      height: '11px',
      border: '2px solid rgba(255,255,255,0.35)',
      borderTopColor: 'rgba(255,255,255,0.9)',
      borderRadius: '50%',
      animation: 'spin 0.65s linear infinite',
      verticalAlign: 'middle',
      marginRight: '5px',
    }} />
  )
}

const TYPE_LABEL: Record<string, string> = {
  LIST_FROM_PROJECT: 'Перечень из проекта',
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
}

// -------- Стадия «Перечень» --------
function ListStage({ card }: Props) {
  const { startTask, submittingCardIds, pendingListTasks, clearPendingListTask } = useKanbanStore()
  const pending = pendingListTasks[card.id]
  const [taskType, setTaskType] = useState<'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND'>(
    pending?.task_type ?? 'LIST_FROM_PROJECT'
  )
  const [files, setFiles] = useState<File[]>(pending?.files ?? [])
  const [fileError, setFileError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const submitting = submittingCardIds.has(card.id)
  const task = card.list_task

  // Синхронизируем: pending может появиться позже монтирования (Zustand нотифицирует до setPendingListTask)
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

  const TypeHeader = () => (
    <div style={{ fontSize: '10px', color: '#7c3aed', fontWeight: 700, marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
      {typeLabel}
    </div>
  )

  // Состояние: задача не создана — форма запуска
  if (task === null) {
    return (
      <div>
        <TypeHeader />
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

  // Состояние: в очереди или выполняется — только прогресс
  if (task.status === 'pending' || task.status === 'processing') {
    return (
      <div>
        <TypeHeader />
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
          <TaskStatusBadge task={task} />
          {task.progress_message && (
            <span style={{ fontSize: '11px', color: '#92400e', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
              {task.progress_message}
            </span>
          )}
          <ArrowBtn onClick={() => setTaskModalOpen(true)} />
        </div>
        <TaskDetailModal taskId={task.id} isOpen={taskModalOpen} onClose={() => setTaskModalOpen(false)} />
      </div>
    )
  }

  // Состояние: завершено — тип + скачать + стрелка
  if (task.status === 'completed') {
    return (
      <div>
        <TypeHeader />
        <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
          <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
          <DownloadBtn onClick={() => safeDownload(task.id, 'result')} title="Скачать перечень" />
          <ArrowBtn onClick={() => setTaskModalOpen(true)} title="Открыть задачу" />
        </div>
        <TaskDetailModal taskId={task.id} isOpen={taskModalOpen} onClose={() => setTaskModalOpen(false)} />
      </div>
    )
  }

  // Состояние: ошибка / отменено — форма повтора с файлами
  return (
    <div>
      <TypeHeader />
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap', marginBottom: '8px' }}>
        <TaskStatusBadge task={task} />
        <ArrowBtn onClick={() => setTaskModalOpen(true)} />
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
      <TaskDetailModal taskId={task.id} isOpen={taskModalOpen} onClose={() => setTaskModalOpen(false)} />
    </div>
  )
}

// -------- Стадия «Полнота» --------
function CompletenessStage({ card }: Props) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const submitting = submittingCardIds.has(card.id)
  const task = card.completeness_task
  const listTask = card.list_task
  const [listTaskModalOpen, setListTaskModalOpen] = useState(false)
  const [taskModalOpen, setTaskModalOpen] = useState(false)

  const listTypeLabel = listTask?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : listTask?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : 'Перечень'

  const getCompletenessType = () =>
    card.list_task?.task_type === 'LIST_FROM_PROJECT'
      ? 'CHECK_PROJECT_COMPLETENESS'
      : 'CHECK_LIST_COMPLETENESS'

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: '10px',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginBottom: '4px',
  }

  return (
    <div>
      {/* Блок 1: итог стадии «Перечень» */}
      {listTask !== null && listTask.status === 'completed' && (
        <div style={{ marginBottom: '10px', paddingBottom: '10px', borderBottom: '1px solid #f1f5f9' }}>
          <div style={{ ...sectionLabelStyle, color: '#7c3aed' }}>{listTypeLabel}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
            <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
            <DownloadBtn onClick={() => safeDownload(listTask.id, 'result')} title="Скачать перечень" />
            <ArrowBtn onClick={() => setListTaskModalOpen(true)} title="Открыть задачу перечня" />
          </div>
        </div>
      )}

      {/* Блок 2: задача проверки полноты */}
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
            <ArrowBtn onClick={() => setTaskModalOpen(true)} />
          </div>
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        <div>
          <div style={{ ...sectionLabelStyle, color: '#3b82f6' }}>Проверка полноты</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
            <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
            <DownloadBtn onClick={() => safeDownload(task.id, 'result')} title="Скачать результат проверки" />
            <ArrowBtn onClick={() => setTaskModalOpen(true)} title="Открыть задачу проверки" />
          </div>
        </div>
      )}

      {task !== null && (task.status === 'failed' || task.status === 'cancelled') && (
        <div>
          <div style={{ ...sectionLabelStyle, color: '#3b82f6' }}>Проверка полноты</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <TaskStatusBadge task={task} />
            <ArrowBtn onClick={() => setTaskModalOpen(true)} />
          </div>
          <ActionButton
            onClick={async () => { await startTask(card.id, { task_type: task.task_type ?? getCompletenessType() }) }}
            disabled={submitting}
          >
            {submitting ? 'Запускаю…' : 'Повторить'}
          </ActionButton>
        </div>
      )}

      {listTask !== null && (
        <TaskDetailModal taskId={listTask.id} isOpen={listTaskModalOpen} onClose={() => setListTaskModalOpen(false)} />
      )}
      {task !== null && (
        <TaskDetailModal taskId={task.id} isOpen={taskModalOpen} onClose={() => setTaskModalOpen(false)} />
      )}
    </div>
  )
}

// -------- Стадия «Смета» --------
function EstimateStage({ card }: Props) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const submitting = submittingCardIds.has(card.id)
  const task = card.estimate_task

  const listCompleted = card.list_task?.status === 'completed'
  const completenessCompleted = card.completeness_task?.status === 'completed'

  const [sourceStage, setSourceStage] = useState<1 | 2>(completenessCompleted ? 2 : 1)

  const noSource = !listCompleted && !completenessCompleted

  const handleCreate = async () => {
    await startTask(card.id, { task_type: 'ESTIMATE_FROM_LIST', source_stage: sourceStage })
  }

  const canCreate = task === null || task.status === 'failed' || task.status === 'cancelled'

  return (
    <div>
      <TaskStatusBadge task={task} />

      {canCreate && (
        <div style={{ marginTop: '8px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '10px' }}>
          {noSource ? (
            <div style={{ color: '#dc2626', fontSize: '12px' }}>Сначала завершите Перечень</div>
          ) : (
            <>
              <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '6px' }}>Источник:</div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', marginBottom: '4px', cursor: listCompleted ? 'pointer' : 'not-allowed', opacity: listCompleted ? 1 : 0.4 }}>
                <input type="radio" value={1} checked={sourceStage === 1} disabled={!listCompleted} onChange={() => setSourceStage(1)} />
                На основе перечня
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: completenessCompleted ? 'pointer' : 'not-allowed', opacity: completenessCompleted ? 1 : 0.4 }}>
                <input type="radio" value={2} checked={sourceStage === 2} disabled={!completenessCompleted} onChange={() => setSourceStage(2)} />
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

      {task !== null && task.status === 'completed' && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton variant="outline" onClick={() => safeDownload(task.id, 'estimate')}>
            Открыть смету
          </ActionButton>
        </div>
      )}
    </div>
  )
}

// -------- Стадия «Оптимизация» --------
function OptimizationStage({ card }: Props) {
  const navigate = useNavigate()
  const { startTask, submittingCardIds } = useKanbanStore()
  const submitting = submittingCardIds.has(card.id)
  const task = card.optimization_task
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const estimateCompleted = card.estimate_task?.status === 'completed'

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
      <TaskStatusBadge task={task} />

      {canStart && (
        <div style={{ marginTop: '8px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '10px' }}>
          <div style={{ marginBottom: '8px' }}>
            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>Использовать смету из предыдущей стадии:</div>
            <ActionButton
              onClick={handleUsePrevious}
              disabled={!estimateCompleted || submitting}
            >
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
          <ActionButton variant="outline" onClick={() => navigate(`/tasks/${task.id}/estimate`)}>
            Открыть смету
          </ActionButton>
        </div>
      )}
    </div>
  )
}

// -------- Диспетчер по стадии --------
export function CardStageContent({ card }: Props) {
  switch (card.stage) {
    case 'list':
      return <ListStage card={card} />
    case 'completeness':
      return <CompletenessStage card={card} />
    case 'estimate':
      return <EstimateStage card={card} />
    case 'optimization':
      return <OptimizationStage card={card} />
    default:
      return null
  }
}
