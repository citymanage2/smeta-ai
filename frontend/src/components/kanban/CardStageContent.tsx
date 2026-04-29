import React, { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { WorkflowCard } from '../../types/workflow'
import { useKanbanStore } from '../../stores/kanban'
import { downloadSlotFile } from '../../api/projects'
import { deleteInputFile, addInputFile } from '../../api/tasks'
import { TaskStatusBadge } from './TaskStatusBadge'
import { TaskDetailModal } from '../TaskDetailModal'

async function safeDownload(taskId: string, slot: string) {
  try {
    await downloadSlotFile(taskId, slot)
  } catch {
    alert('Не удалось скачать файл. Попробуйте ещё раз.')
  }
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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

// -------- Стадия «Перечень» --------
function ListStage({ card }: Props) {
  const { startTask, submittingCardIds, fetchCards } = useKanbanStore()
  const [showTypeModal, setShowTypeModal] = useState(false)
  const [taskType, setTaskType] = useState<'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND'>('LIST_FROM_PROJECT')
  const [isRetry, setIsRetry] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [fileOpsLoading, setFileOpsLoading] = useState(false)
  const [fileOpsError, setFileOpsError] = useState<string | null>(null)
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const addFileRef = useRef<HTMLInputElement>(null)
  const submitting = submittingCardIds.has(card.id)
  const task = card.list_task

  const canModifyFiles = task !== null && task.status !== 'processing' && task.status !== 'pending'

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

  const handleLaunch = async () => {
    if (!file) return
    setShowTypeModal(false)
    await startTask(card.id, { task_type: taskType, file })
    setFile(null)
    setIsRetry(false)
  }

  const handleRetry = () => {
    if (task) setTaskType(task.task_type as 'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND')
    setIsRetry(true)
    setShowTypeModal(true)
  }

  const handleDeleteFile = async (fileIndex: number) => {
    if (!task) return
    setFileOpsLoading(true)
    setFileOpsError(null)
    try {
      await deleteInputFile(task.id, fileIndex)
      await fetchCards(card.project_id)
    } catch {
      setFileOpsError('Не удалось удалить файл')
    } finally {
      setFileOpsLoading(false)
    }
  }

  const handleAddFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f || !task) return
    if (f.size > FILE_SIZE_LIMIT) {
      setFileOpsError('Файл превышает 50 МБ')
      return
    }
    setFileOpsLoading(true)
    setFileOpsError(null)
    try {
      await addInputFile(task.id, f)
      await fetchCards(card.project_id)
    } catch {
      setFileOpsError('Не удалось добавить файл')
    } finally {
      setFileOpsLoading(false)
      if (addFileRef.current) addFileRef.current.value = ''
    }
  }

  const typeLabel = task?.task_type === 'LIST_FROM_PROJECT'
    ? 'Перечень из проекта'
    : task?.task_type === 'LIST_FROM_GRAND'
    ? 'Перечень из Гранд-сметы'
    : null

  return (
    <div>
      {/* Статус + прогресс + кнопка просмотра задачи */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <TaskStatusBadge task={task} />
        {task !== null && task.status === 'processing' && task.progress_message && (
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
        {task !== null && (
          <button
            onClick={() => setTaskModalOpen(true)}
            title="Посмотреть задачу"
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
              marginLeft: 'auto',
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
        )}
      </div>

      {/* Метка типа + прикреплённые файлы */}
      {task !== null && (
        <div style={{ marginTop: '8px' }}>
          {typeLabel && (
            <div style={{ fontSize: '10px', color: '#7c3aed', fontWeight: 700, marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {typeLabel}
            </div>
          )}

          {task.input_files.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {task.input_files.map((f, idx) => (
                <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '4px 7px' }}>
                  <span style={{ fontSize: '12px', flexShrink: 0 }}>📎</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '12px', color: '#1e293b', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
                    <div style={{ fontSize: '10px', color: '#94a3b8' }}>{formatFileSize(f.size_bytes)}</div>
                  </div>
                  {canModifyFiles && (
                    <button
                      onClick={() => handleDeleteFile(idx)}
                      disabled={fileOpsLoading}
                      title="Удалить файл"
                      style={{ background: 'none', border: 'none', cursor: fileOpsLoading ? 'not-allowed' : 'pointer', color: '#cbd5e1', fontSize: '12px', padding: '2px 3px', borderRadius: '3px', lineHeight: 1, flexShrink: 0 }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#dc2626' }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#cbd5e1' }}
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '12px', color: '#94a3b8', fontStyle: 'italic' }}>Нет прикреплённых файлов</div>
          )}

          {canModifyFiles && (
            <div style={{ marginTop: '5px' }}>
              <input ref={addFileRef} type="file" style={{ display: 'none' }} onChange={handleAddFile} />
              <button
                onClick={() => addFileRef.current?.click()}
                disabled={fileOpsLoading}
                style={{
                  background: 'none',
                  border: '1px dashed #cbd5e1',
                  borderRadius: '5px',
                  padding: '3px 10px',
                  fontSize: '12px',
                  color: fileOpsLoading ? '#94a3b8' : '#64748b',
                  cursor: fileOpsLoading ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                }}
              >
                {fileOpsLoading ? (
                  <>
                    <span style={{
                      display: 'inline-block',
                      width: '10px',
                      height: '10px',
                      border: '2px solid #cbd5e1',
                      borderTopColor: '#64748b',
                      borderRadius: '50%',
                      animation: 'spin 0.7s linear infinite',
                    }} />
                    Загружаю…
                  </>
                ) : '+ Добавить файл'}
              </button>
            </div>
          )}

          {fileOpsError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileOpsError}</div>}
        </div>
      )}

      {/* Кнопки действий */}
      {task === null && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton onClick={() => setShowTypeModal(true)} disabled={submitting}>
            Создать перечень
          </ActionButton>
        </div>
      )}

      {task !== null && (task.status === 'failed' || task.status === 'cancelled') && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton onClick={handleRetry} disabled={submitting}>Повторить</ActionButton>
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton variant="outline" onClick={() => safeDownload(task.id, 'result')}>
            Открыть результат
          </ActionButton>
        </div>
      )}

      {/* Форма создания / повтора */}
      {showTypeModal && (
        <div style={{ marginTop: '10px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '12px' }}>
          {!isRetry && (
            <>
              <div style={{ fontSize: '13px', color: '#475569', marginBottom: '8px', fontWeight: 500 }}>Тип перечня</div>
              {(['LIST_FROM_PROJECT', 'LIST_FROM_GRAND'] as const).map((t) => (
                <label key={t} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', marginBottom: '6px', cursor: 'pointer' }}>
                  <input type="radio" value={t} checked={taskType === t} onChange={() => setTaskType(t)} />
                  {t === 'LIST_FROM_PROJECT' ? 'Перечень из проекта' : 'Перечень из Гранд-сметы'}
                </label>
              ))}
            </>
          )}
          <div style={{ marginTop: '8px', overflow: 'hidden', maxWidth: '100%' }}>
            <input ref={fileRef} type="file" style={{ fontSize: '13px', maxWidth: '100%' }} onChange={handleFileChange} />
            {fileError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileError}</div>}
          </div>
          <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
            <ActionButton onClick={handleLaunch} disabled={!file || submitting}>
              {submitting ? 'Запускаю…' : 'Запустить'}
            </ActionButton>
            <ActionButton variant="secondary" onClick={() => { setShowTypeModal(false); setFile(null); setFileError(null) }}>
              Отмена
            </ActionButton>
          </div>
        </div>
      )}

      {/* Модальное окно задачи */}
      {task !== null && (
        <TaskDetailModal
          taskId={task.id}
          isOpen={taskModalOpen}
          onClose={() => setTaskModalOpen(false)}
        />
      )}
    </div>
  )
}

// -------- Стадия «Полнота» --------
function CompletenessStage({ card }: Props) {
  const { startTask, submittingCardIds } = useKanbanStore()
  const submitting = submittingCardIds.has(card.id)
  const task = card.completeness_task

  const getCompletenessType = () =>
    card.list_task?.task_type === 'LIST_FROM_PROJECT'
      ? 'CHECK_PROJECT_COMPLETENESS'
      : 'CHECK_LIST_COMPLETENESS'

  const handleCheck = async () => {
    await startTask(card.id, { task_type: getCompletenessType() })
  }

  const handleRetry = async () => {
    const tt = task?.task_type ?? getCompletenessType()
    await startTask(card.id, { task_type: tt })
  }

  return (
    <div>
      <TaskStatusBadge task={task} />

      {task === null && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton onClick={handleCheck} disabled={submitting}>
            {submitting ? 'Запускаю…' : 'Проверить полноту'}
          </ActionButton>
        </div>
      )}

      {task !== null && (task.status === 'failed' || task.status === 'cancelled') && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton onClick={handleRetry} disabled={submitting}>Повторить</ActionButton>
        </div>
      )}

      {task !== null && task.status === 'completed' && (
        <div style={{ marginTop: '8px' }}>
          <ActionButton variant="outline" onClick={() => safeDownload(task.id, 'result')}>
            Открыть результат
          </ActionButton>
        </div>
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
