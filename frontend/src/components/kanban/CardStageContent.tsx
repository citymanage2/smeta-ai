import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { WorkflowCard } from '../../types/workflow'
import { useKanbanStore } from '../../stores/kanban'
import { downloadSlotFile } from '../../api/projects'
import { TaskStatusBadge } from './TaskStatusBadge'
import { TaskDetailModal } from '../TaskDetailModal'

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

// -------- Стадия «Перечень» --------
function ListStage({ card }: Props) {
  const { startTask, submittingCardIds, pendingListTasks, clearPendingListTask } = useKanbanStore()
  const pending = pendingListTasks[card.id]
  const [taskType, setTaskType] = useState<'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND'>(
    pending?.task_type ?? 'LIST_FROM_PROJECT'
  )
  const [file, setFile] = useState<File | null>(pending?.file ?? null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [showChangeFile, setShowChangeFile] = useState(false)
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [showRetryForm, setShowRetryForm] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const retryFileRef = useRef<HTMLInputElement>(null)
  const submitting = submittingCardIds.has(card.id)
  const task = card.list_task

  // Синхронизируем, если pending появился после монтирования (повторный рендер)
  useEffect(() => {
    if (pending && !file) {
      setTaskType(pending.task_type)
      setFile(pending.file)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.id])

  const typeLabel = task?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : task?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : null

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    if (f && f.size > FILE_SIZE_LIMIT) {
      setFileError('Файл превышает 50 МБ')
      setFile(null)
    } else {
      setFileError(null)
      setFile(f)
      setShowChangeFile(false)
    }
  }

  // Состояние: задача не создана — форма запуска
  if (task === null) {
    const hasPendingFile = !!pending && !!file && !showChangeFile
    return (
      <div>
        {(['LIST_FROM_PROJECT', 'LIST_FROM_GRAND'] as const).map((t) => (
          <label key={t} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', marginBottom: '5px', cursor: 'pointer' }}>
            <input type="radio" value={t} checked={taskType === t} onChange={() => setTaskType(t)} />
            {t === 'LIST_FROM_PROJECT' ? 'Перечень из проекта' : 'Перечень из Гранд-сметы'}
          </label>
        ))}

        <div style={{ marginTop: '6px', overflow: 'hidden', maxWidth: '100%' }}>
          {hasPendingFile ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '5px 8px' }}>
              <span style={{ fontSize: '13px' }}>📎</span>
              <span style={{ fontSize: '12px', color: '#1e293b', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file!.name}
              </span>
              <button
                onClick={() => setShowChangeFile(true)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', fontSize: '11px', padding: '0', flexShrink: 0 }}
              >
                Изменить
              </button>
            </div>
          ) : (
            <>
              <input
                ref={fileRef}
                type="file"
                style={{ fontSize: '12px', maxWidth: '100%' }}
                onChange={handleFileChange}
              />
              {fileError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileError}</div>}
            </>
          )}
        </div>

        <div style={{ marginTop: '8px' }}>
          <ActionButton
            onClick={async () => {
              if (!file) return
              const f = file
              setFile(null)
              setShowChangeFile(false)
              if (fileRef.current) fileRef.current.value = ''
              clearPendingListTask(card.id)
              await startTask(card.id, { task_type: taskType, file: f })
            }}
            disabled={!file || submitting}
          >
            {submitting ? 'Создаю…' : 'Создать перечень'}
          </ActionButton>
        </div>
      </div>
    )
  }

  // Состояние: в очереди или выполняется — только прогресс
  if (task.status === 'pending' || task.status === 'processing') {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
          <TaskStatusBadge task={task} />
          {task.progress_message && (
            <span style={{
              fontSize: '11px',
              color: '#92400e',
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              minWidth: 0,
            }}>
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
        {typeLabel && (
          <div style={{ fontSize: '10px', color: '#7c3aed', fontWeight: 700, marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {typeLabel}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
          <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600, flex: 1 }}>● Готово</span>
          <DownloadBtn onClick={() => safeDownload(task.id, 'result')} title="Скачать перечень" />
          <ArrowBtn onClick={() => setTaskModalOpen(true)} title="Открыть задачу" />
        </div>
        <TaskDetailModal taskId={task.id} isOpen={taskModalOpen} onClose={() => setTaskModalOpen(false)} />
      </div>
    )
  }

  // Состояние: ошибка / отменено — повтор
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <TaskStatusBadge task={task} />
        <ArrowBtn onClick={() => setTaskModalOpen(true)} />
      </div>
      {!showRetryForm && (
        <ActionButton
          onClick={() => {
            setTaskType(task.task_type as 'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND')
            setShowRetryForm(true)
          }}
          disabled={submitting}
        >
          Повторить
        </ActionButton>
      )}
      {showRetryForm && (
        <div style={{ marginTop: '8px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '10px' }}>
          <div style={{ overflow: 'hidden', maxWidth: '100%' }}>
            <input
              ref={retryFileRef}
              type="file"
              style={{ fontSize: '12px', maxWidth: '100%' }}
              onChange={handleFileChange}
            />
            {fileError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileError}</div>}
          </div>
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <ActionButton
              onClick={async () => {
                if (!file) return
                const f = file
                setShowRetryForm(false)
                setFile(null)
                if (retryFileRef.current) retryFileRef.current.value = ''
                await startTask(card.id, { task_type: task.task_type as 'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND', file: f })
              }}
              disabled={!file || submitting}
            >
              {submitting ? 'Запускаю…' : 'Запустить'}
            </ActionButton>
            <ActionButton
              variant="secondary"
              onClick={() => { setShowRetryForm(false); setFile(null); setFileError(null) }}
            >
              Отмена
            </ActionButton>
          </div>
        </div>
      )}
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
            <TaskStatusBadge task={task} />
            {task.progress_message && (
              <span style={{ fontSize: '11px', color: '#92400e', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
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
