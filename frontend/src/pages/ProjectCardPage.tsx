import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Download, ExternalLink, Edit3, AlertTriangle, FileText, ChevronDown, ChevronUp } from 'lucide-react'
import Layout from '../components/Layout'
import { LumaSpin } from '../components/ui/LumaSpin'
import { TaskDetailModal } from '../components/TaskDetailModal'
import { EstimateEditorModal } from '../components/card/EstimateEditorModal'
import { getCardDetail, downloadSlotFileById, downloadInputFileById, CardDetail, StageDetail } from '../api/workflowCards'
import { downloadResult, restartTask } from '../api/tasks'

const TASK_TYPE_LABELS: Record<string, string> = {
  LIST_FROM_PROJECT: 'Перечень из проекта',
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
  CHECK_LIST_COMPLETENESS: 'Проверка полноты перечня',
  CHECK_PROJECT_COMPLETENESS: 'Проверка полноты (по проекту)',
  ESTIMATE_FROM_LIST: 'Смета из перечня',
  ESTIMATE_OPTIMIZATION: 'Оптимизация сметы',
}

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

// ---------------------------------------------------------------------------
// Status dot
// ---------------------------------------------------------------------------
const STATUS_DOT: Record<string, { color: string; label: string }> = {
  completed:  { color: '#10b981', label: 'Готово' },
  processing: { color: '#3b82f6', label: 'Обрабатывается' },
  pending:    { color: '#f59e0b', label: 'В очереди' },
  failed:     { color: '#ef4444', label: 'Ошибка' },
  cancelled:  { color: '#94a3b8', label: 'Отменено' },
}

function StatusDot({ status }: { status: string }) {
  const s = STATUS_DOT[status] ?? { color: '#94a3b8', label: status }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: s.color, fontWeight: 600 }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.color, display: 'inline-block', flexShrink: 0 }} />
      {s.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Manual edit warning banner
// ---------------------------------------------------------------------------
function ManualEditWarning({ editedAt, prevStageName }: { editedAt: string; prevStageName: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: '8px',
      background: '#fffbeb', border: '1px solid #fcd34d',
      borderRadius: '8px', padding: '10px 12px', marginTop: '10px',
    }}>
      <AlertTriangle size={15} color="#d97706" style={{ flexShrink: 0, marginTop: 1 }} />
      <span style={{ fontSize: '12px', color: '#92400e', lineHeight: 1.5 }}>
        Файл на этапе <strong>«{prevStageName}»</strong> был изменён вручную {formatDate(editedAt)}.
        Для корректности рекомендуется переформировать этот этап.
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// File row inside a stage
// ---------------------------------------------------------------------------
interface FileRowProps {
  name: string
  size: number
  mime: string
  date: string
  onDownload: () => void
  onOpenEditor?: () => void
  onOpenTask?: () => void
  editorLabel?: string
}

function FileRow({ name, size, mime, date, onDownload, onOpenEditor, onOpenTask, editorLabel }: FileRowProps) {
  const isXlsx = mime.includes('spreadsheet') || mime.includes('excel') || name.endsWith('.xlsx') || name.endsWith('.xls')
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '8px',
      background: '#f8fafc', border: '1px solid #e2e8f0',
      borderRadius: '8px', padding: '8px 10px',
    }}>
      <FileText size={16} color="#64748b" style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '13px', color: '#1e293b', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {name}
        </div>
        <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '1px' }}>
          {formatSize(size)} · {date}
        </div>
      </div>
      <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
        <IconBtn title="Скачать" onClick={onDownload}><Download size={14} /></IconBtn>
        {onOpenTask && (
          <IconBtn title="Открыть задачу" onClick={onOpenTask}><ExternalLink size={14} /></IconBtn>
        )}
        {onOpenEditor && isXlsx && (
          <IconBtn title={editorLabel || 'Открыть в онлайн-редакторе'} onClick={onOpenEditor} highlight>
            <Edit3 size={14} />
          </IconBtn>
        )}
      </div>
    </div>
  )
}

function IconBtn({
  onClick, title, children, highlight,
}: { onClick: () => void; title: string; children: React.ReactNode; highlight?: boolean }) {
  const [hover, setHover] = useState(false)
  return (
    <button
      title={title}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        background: highlight
          ? hover ? '#2563eb' : '#3b82f6'
          : hover ? '#f1f5f9' : 'none',
        border: highlight ? 'none' : '1px solid #e2e8f0',
        borderRadius: '6px', padding: '5px 7px', cursor: 'pointer',
        color: highlight ? '#fff' : hover ? '#3b82f6' : '#64748b',
        display: 'flex', alignItems: 'center',
        transition: 'all 0.1s',
      }}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Stage block
// ---------------------------------------------------------------------------
interface StageBlockProps {
  number: number
  title: string
  optional?: boolean
  status?: string
  missing?: boolean
  children: React.ReactNode
  warning?: React.ReactNode
}

function StageBlock({ number, title, optional, status, missing, children, warning }: StageBlockProps) {
  return (
    <div style={{
      background: missing ? '#f8fafc' : 'rgba(255,255,255,0.88)',
      backdropFilter: missing ? 'none' : 'blur(8px)',
      WebkitBackdropFilter: missing ? 'none' : 'blur(8px)',
      border: `1px solid ${missing ? '#e2e8f0' : 'rgba(226,232,240,0.7)'}`,
      borderRadius: '14px',
      padding: '16px 18px',
      opacity: missing ? 0.55 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: missing ? 0 : '12px' }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
          background: missing ? '#e2e8f0' : '#3b82f6',
          color: missing ? '#94a3b8' : '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '13px', fontWeight: 700,
        }}>
          {number}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span style={{ fontWeight: 600, fontSize: '14px', color: missing ? '#94a3b8' : '#1e293b' }}>
            {title}
          </span>
          {optional && !missing && (
            <span style={{ marginLeft: 6, fontSize: '11px', color: '#94a3b8', fontWeight: 400 }}>(выполнено)</span>
          )}
          {optional && missing && (
            <span style={{ marginLeft: 6, fontSize: '11px', color: '#cbd5e1', fontWeight: 400 }}>(не запущено)</span>
          )}
        </div>
        {status && !missing && <StatusDot status={status} />}
      </div>
      {!missing && children}
      {warning}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connector arrow between stages
// ---------------------------------------------------------------------------
function StageArrow({ active }: { active: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 28 }}>
      <div style={{
        width: 2, height: 16, background: active ? '#93c5fd' : '#e2e8f0',
        borderRadius: 1, transition: 'background 0.2s',
      }} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Restart button for failed/cancelled stages
// ---------------------------------------------------------------------------
function RestartButton({ taskId, restarting, onRestart }: { taskId: string; restarting: boolean; onRestart: (id: string) => void }) {
  return (
    <button
      onClick={() => onRestart(taskId)}
      disabled={restarting}
      style={{
        marginTop: '10px',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        background: restarting ? '#e0f2fe' : '#f0f9ff',
        color: '#0369a1',
        border: '1px solid #7dd3fc',
        borderRadius: '8px',
        padding: '5px 12px',
        fontSize: '12px',
        fontWeight: 600,
        cursor: restarting ? 'not-allowed' : 'pointer',
      }}
    >
      {restarting ? 'Запускаю…' : '↺ Перезапустить'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Optimization stage — all version files + collapsible
// ---------------------------------------------------------------------------
function OptimizationStageContent({
  stage,
  onOpenEditor,
  onOpenTask,
}: {
  stage: StageDetail
  onOpenEditor: () => void
  onOpenTask: () => void
}) {
  const [expanded, setExpanded] = useState(true)
  const mainFile = stage.result_files.find(f => f.slot === 'optimized') ?? stage.result_files[0]
  const archiveFiles = stage.result_files.filter(f => f.slot !== 'optimized' && f.slot !== 'source')

  return (
    <div>
      {mainFile && (
        <div style={{ marginBottom: '8px' }}>
          <div style={{ fontSize: '11px', color: '#7c3aed', fontWeight: 700, marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Текущая версия
          </div>
          <FileRow
            name={mainFile.file_name}
            size={mainFile.size_bytes}
            mime={mainFile.mime_type}
            date={formatDate(mainFile.created_at)}
            onDownload={() => downloadSlotFileById(stage.task_id, mainFile.slot)}
            onOpenTask={onOpenTask}
            onOpenEditor={onOpenEditor}
            editorLabel="Открыть в редакторе (с версиями и сравнением)"
          />
        </div>
      )}

      {archiveFiles.length > 0 && (
        <div>
          <button
            onClick={() => setExpanded(e => !e)}
            style={{
              display: 'flex', alignItems: 'center', gap: '5px',
              background: 'none', border: 'none', cursor: 'pointer',
              color: '#64748b', fontSize: '12px', padding: '2px 0', marginBottom: '6px',
            }}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            Архив версий ({archiveFiles.length})
          </button>
          {expanded && archiveFiles.map(f => (
            <div key={f.result_id} style={{ marginBottom: '5px' }}>
              <FileRow
                name={f.file_name}
                size={f.size_bytes}
                mime={f.mime_type}
                date={formatDate(f.created_at)}
                onDownload={() => downloadResult(f.result_id, f.file_name)}
                onOpenTask={onOpenTask}
                onOpenEditor={onOpenEditor}
                editorLabel="Открыть в редакторе"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
const ProjectCardPage: React.FC = () => {
  const { projectId, cardId } = useParams<{ projectId: string; cardId: string }>()
  const navigate = useNavigate()

  const [detail, setDetail] = useState<CardDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [taskModal, setTaskModal] = useState<string | null>(null)
  const [editorModal, setEditorModal] = useState<{ taskId: string; title: string; fileSlot?: string; fileIndex?: number } | null>(null)
  const [restartingTaskId, setRestartingTaskId] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!cardId) return
    try {
      setLoading(true)
      setError('')
      const data = await getCardDetail(cardId)
      setDetail(data)
    } catch {
      setError('Не удалось загрузить данные карточки')
    } finally {
      setLoading(false)
    }
  }, [cardId])

  useEffect(() => { load() }, [load])

  const handleEditorSaved = useCallback(() => {
    // Перезагружаем данные, чтобы показать обновлённый manually_edited_at
    load()
  }, [load])

  const handleRestart = useCallback(async (taskId: string) => {
    setRestartingTaskId(taskId)
    try {
      await restartTask(taskId)
      await load()
    } finally {
      setRestartingTaskId(null)
    }
  }, [load])

  if (loading) {
    return (
      <Layout>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
          <LumaSpin size="lg" color="#3b82f6" />
        </div>
      </Layout>
    )
  }

  if (error || !detail) {
    return (
      <Layout>
        <div style={{ padding: '32px', textAlign: 'center', color: '#ef4444', fontSize: '14px' }}>
          {error || 'Карточка не найдена'}
        </div>
      </Layout>
    )
  }

  const { source_stage, completeness_stage, estimate_stage, optimization_stage } = detail

  function wasEditedBefore(prevStage: StageDetail | null, currentStage: StageDetail | null): boolean {
    if (!prevStage?.manually_edited_at || !currentStage) return false
    return new Date(prevStage.manually_edited_at) > new Date(currentStage.task_created_at)
  }

  const srcBeforeCompleteness = wasEditedBefore(source_stage, completeness_stage)
  const srcBeforeEstimate = wasEditedBefore(source_stage, estimate_stage)
  const srcBeforeOptimization = wasEditedBefore(source_stage, optimization_stage)
  const compBeforeEstimate = wasEditedBefore(completeness_stage, estimate_stage)
  const compBeforeOptimization = wasEditedBefore(completeness_stage, optimization_stage)
  const estBeforeOptimization = wasEditedBefore(estimate_stage, optimization_stage)

  return (
    <Layout>
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '24px 16px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '24px' }}>
          <button
            onClick={() => navigate(`/projects/${projectId}`)}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              background: 'none', border: '1px solid #e2e8f0', borderRadius: '8px',
              padding: '6px 12px', cursor: 'pointer', color: '#64748b', fontSize: '13px',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd'; (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#e2e8f0'; (e.currentTarget as HTMLElement).style.color = '#64748b' }}
          >
            <ArrowLeft size={14} />
            К проекту
          </button>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {detail.name}
            </h1>
          </div>
        </div>

        {/* Pipeline */}
        <div>

          {/* Stage 1: Исходный файл */}
          <StageBlock
            number={1}
            title="Исходный файл"
            status={source_stage?.task_status}
            missing={!source_stage}
          >
            {source_stage && (
              <>
                {source_stage.input_files.length > 0 ? (
                  source_stage.input_files.map(f => {
                    const editedAt = source_stage.manually_edited_at
                    const inputDate = editedAt && new Date(editedAt) > new Date(source_stage.task_created_at)
                      ? editedAt
                      : source_stage.task_created_at
                    return (
                      <div key={f.index} style={{ marginBottom: '5px' }}>
                        <FileRow
                          name={f.name}
                          size={f.size_bytes}
                          mime={f.mime_type}
                          date={formatDate(inputDate)}
                          onDownload={() => downloadInputFileById(source_stage.task_id, f.index)}
                          onOpenTask={() => setTaskModal(source_stage.task_id)}
                          onOpenEditor={() => setEditorModal({
                            taskId: source_stage.task_id,
                            title: `Исходный файл — ${f.name}`,
                            fileSlot: 'input',
                            fileIndex: f.index,
                          })}
                          editorLabel="Открыть в онлайн-редакторе"
                        />
                      </div>
                    )
                  })
                ) : (
                  <div style={{ fontSize: '12px', color: '#94a3b8' }}>Файлы не загружены</div>
                )}
                {source_stage.manually_edited_at && (
                  <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '6px' }}>
                    ✎ Изменён вручную: {formatDate(source_stage.manually_edited_at)}
                  </div>
                )}
              </>
            )}
          </StageBlock>

          <StageArrow active={!!source_stage} />

          {/* Stage 2: Перечень */}
          <StageBlock
            number={2}
            title="Перечень"
            status={source_stage?.task_status}
            missing={!source_stage}
            warning={
              source_stage?.manually_edited_at ? (
                <ManualEditWarning editedAt={source_stage.manually_edited_at} prevStageName="Исходный файл" />
              ) : undefined
            }
          >
            {source_stage && (
              <div style={{ fontSize: '11px', color: '#7c3aed', fontWeight: 700, marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                {TASK_TYPE_LABELS[source_stage.task_type] ?? source_stage.task_type}
              </div>
            )}
            {source_stage && source_stage.result_files.map(f => (
              <div key={f.result_id} style={{ marginBottom: '5px' }}>
                <FileRow
                  name={f.file_name}
                  size={f.size_bytes}
                  mime={f.mime_type}
                  date={formatDate(f.created_at)}
                  onDownload={() => downloadSlotFileById(source_stage.task_id, f.slot)}
                  onOpenTask={() => setTaskModal(source_stage.task_id)}
                  onOpenEditor={() => setEditorModal({
                    taskId: source_stage.task_id,
                    title: `Перечень — ${f.file_name}`,
                  })}
                  editorLabel="Открыть перечень в онлайн-редакторе"
                />
              </div>
            ))}
            {source_stage && source_stage.result_files.length === 0 && source_stage.task_status !== 'completed' && (
              <div style={{ fontSize: '12px', color: '#94a3b8' }}>Задача ещё не завершена</div>
            )}
            {source_stage && (source_stage.task_status === 'failed' || source_stage.task_status === 'cancelled' || source_stage.task_status === 'completed' || source_stage.task_status === 'processing') && (
              <RestartButton
                taskId={source_stage.task_id}
                restarting={restartingTaskId === source_stage.task_id}
                onRestart={handleRestart}
              />
            )}
          </StageBlock>

          <StageArrow active={!!completeness_stage || !!estimate_stage} />

          {/* Stage 3: Проверка полноты (опциональная) */}
          <StageBlock
            number={3}
            title="Проверка полноты"
            optional
            status={completeness_stage?.task_status}
            missing={!completeness_stage}
            warning={
              srcBeforeCompleteness ? (
                <ManualEditWarning editedAt={source_stage!.manually_edited_at!} prevStageName="Перечень" />
              ) : undefined
            }
          >
            {completeness_stage && (
              <>
                <div style={{ fontSize: '11px', color: '#7c3aed', fontWeight: 700, marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  {TASK_TYPE_LABELS[completeness_stage.task_type] ?? completeness_stage.task_type}
                </div>
                {completeness_stage.result_files.map(f => (
                  <div key={f.result_id} style={{ marginBottom: '5px' }}>
                    <FileRow
                      name={f.file_name}
                      size={f.size_bytes}
                      mime={f.mime_type}
                      date={formatDate(f.created_at)}
                      onDownload={() => downloadSlotFileById(completeness_stage.task_id, f.slot)}
                      onOpenTask={() => setTaskModal(completeness_stage.task_id)}
                      onOpenEditor={() => setEditorModal({
                        taskId: completeness_stage.task_id,
                        title: `Полнота — ${f.file_name}`,
                      })}
                      editorLabel="Открыть файл полноты в онлайн-редакторе"
                    />
                  </div>
                ))}
                {completeness_stage.manually_edited_at && (
                  <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '6px' }}>
                    ✎ Изменён вручную: {formatDate(completeness_stage.manually_edited_at)}
                  </div>
                )}
                {(completeness_stage.task_status === 'failed' || completeness_stage.task_status === 'cancelled' || completeness_stage.task_status === 'completed' || completeness_stage.task_status === 'processing') && (
                  <RestartButton
                    taskId={completeness_stage.task_id}
                    restarting={restartingTaskId === completeness_stage.task_id}
                    onRestart={handleRestart}
                  />
                )}
              </>
            )}
          </StageBlock>

          <StageArrow active={!!estimate_stage} />

          {/* Stage 4: Смета из перечня */}
          <StageBlock
            number={4}
            title="Смета из перечня"
            status={estimate_stage?.task_status}
            missing={!estimate_stage}
            warning={
              (srcBeforeEstimate || compBeforeEstimate) ? (
                <>
                  {srcBeforeEstimate && <ManualEditWarning editedAt={source_stage!.manually_edited_at!} prevStageName="Перечень" />}
                  {compBeforeEstimate && <ManualEditWarning editedAt={completeness_stage!.manually_edited_at!} prevStageName="Проверка полноты" />}
                </>
              ) : undefined
            }
          >
            {estimate_stage && (
              <>
                {estimate_stage.result_files.map(f => (
                  <div key={f.result_id} style={{ marginBottom: '5px' }}>
                    <FileRow
                      name={f.file_name}
                      size={f.size_bytes}
                      mime={f.mime_type}
                      date={formatDate(f.created_at)}
                      onDownload={() => downloadSlotFileById(estimate_stage.task_id, f.slot)}
                      onOpenTask={() => setTaskModal(estimate_stage.task_id)}
                      onOpenEditor={() => setEditorModal({
                        taskId: estimate_stage.task_id,
                        title: `Смета — ${f.file_name}`,
                      })}
                      editorLabel="Открыть смету в онлайн-редакторе"
                    />
                  </div>
                ))}
                {estimate_stage.result_files.length === 0 && estimate_stage.task_status !== 'completed' && (
                  <div style={{ fontSize: '12px', color: '#94a3b8' }}>Задача ещё не завершена</div>
                )}
                {estimate_stage.manually_edited_at && (
                  <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '6px' }}>
                    ✎ Изменён вручную: {formatDate(estimate_stage.manually_edited_at)}
                  </div>
                )}
                {(estimate_stage.task_status === 'failed' || estimate_stage.task_status === 'cancelled' || estimate_stage.task_status === 'completed' || estimate_stage.task_status === 'processing') && (
                  <RestartButton
                    taskId={estimate_stage.task_id}
                    restarting={restartingTaskId === estimate_stage.task_id}
                    onRestart={handleRestart}
                  />
                )}
              </>
            )}
          </StageBlock>

          <StageArrow active={!!optimization_stage} />

          {/* Stage 5: Оптимизация сметы */}
          <StageBlock
            number={5}
            title="Оптимизация сметы"
            optional
            status={optimization_stage?.task_status}
            missing={!optimization_stage}
            warning={
              (srcBeforeOptimization || compBeforeOptimization || estBeforeOptimization) ? (
                <>
                  {srcBeforeOptimization && <ManualEditWarning editedAt={source_stage!.manually_edited_at!} prevStageName="Перечень" />}
                  {compBeforeOptimization && <ManualEditWarning editedAt={completeness_stage!.manually_edited_at!} prevStageName="Проверка полноты" />}
                  {estBeforeOptimization && <ManualEditWarning editedAt={estimate_stage!.manually_edited_at!} prevStageName="Смета из перечня" />}
                </>
              ) : undefined
            }
          >
            {optimization_stage && (
              <>
                <OptimizationStageContent
                  stage={optimization_stage}
                  onOpenEditor={() => setEditorModal({
                    taskId: optimization_stage.task_id,
                    title: 'Оптимизация сметы',
                  })}
                  onOpenTask={() => setTaskModal(optimization_stage.task_id)}
                />
                {optimization_stage.manually_edited_at && (
                  <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '8px' }}>
                    ✎ Изменён вручную: {formatDate(optimization_stage.manually_edited_at)}
                  </div>
                )}
                {(optimization_stage.task_status === 'failed' || optimization_stage.task_status === 'cancelled' || optimization_stage.task_status === 'completed' || optimization_stage.task_status === 'processing') && (
                  <RestartButton
                    taskId={optimization_stage.task_id}
                    restarting={restartingTaskId === optimization_stage.task_id}
                    onRestart={handleRestart}
                  />
                )}
              </>
            )}
          </StageBlock>

        </div>
      </div>

      {/* Task detail modal */}
      {taskModal && (
        <TaskDetailModal
          taskId={taskModal}
          isOpen={!!taskModal}
          onClose={() => setTaskModal(null)}
        />
      )}

      {/* Estimate editor modal (fullscreen iframe) */}
      {editorModal && (
        <EstimateEditorModal
          taskId={editorModal.taskId}
          title={editorModal.title}
          fileSlot={editorModal.fileSlot}
          fileIndex={editorModal.fileIndex}
          onClose={() => setEditorModal(null)}
          onSaved={handleEditorSaved}
        />
      )}
    </Layout>
  )
}

export default ProjectCardPage
