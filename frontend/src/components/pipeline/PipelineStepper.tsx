import React from 'react'
import { Check, Lock, AlertTriangle, Loader2 } from 'lucide-react'
import { WorkflowCard, KanbanStage, TaskBrief } from '../../types/workflow'
import { computeGuard } from '../../stores/kanban'

// ---------------------------------------------------------------------------
// Пайплайн-степпер — дорожка из 4 этапов (Фаза 3, КП-2/КП-3).
// Заменяет колоночную раскладку канбана для ВИДА ОДНОЙ СМЕТЫ.
// Продвижение автоматическое: состояние узла считается из статусов *_task,
// без drag. Блокировки переиспользуют computeGuard (тот же гейт, что и канбан).
// ---------------------------------------------------------------------------

export type NodeState = 'wait' | 'lock' | 'run' | 'done' | 'error'

export const PIPELINE_STAGES: KanbanStage[] = ['list', 'completeness', 'estimate', 'optimization']

const STAGE_LABELS: Record<KanbanStage, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

// Токены цветов — те же, что в SmetaList/канбане/brand-guidelines.
const STATE_STYLE: Record<NodeState, { ring: string; fill: string; icon: string; label: string; caption: string }> = {
  done:  { ring: '#10b981', fill: '#10b981', icon: '#ffffff', label: '#10b981', caption: 'Готово' },
  run:   { ring: '#3b82f6', fill: '#3b82f6', icon: '#ffffff', label: '#3b82f6', caption: 'Идёт' },
  error: { ring: '#ef4444', fill: '#ef4444', icon: '#ffffff', label: '#ef4444', caption: 'Ошибка' },
  lock:  { ring: '#cbd5e1', fill: '#f1f5f9', icon: '#94a3b8', label: '#94a3b8', caption: '' },
  wait:  { ring: '#cbd5e1', fill: '#ffffff', icon: '#94a3b8', label: '#64748b', caption: 'Ожидает' },
}

export function stageTask(card: WorkflowCard, stage: KanbanStage): TaskBrief | null {
  switch (stage) {
    case 'list':         return card.list_task
    case 'completeness': return card.completeness_task
    case 'estimate':     return card.estimate_task
    case 'optimization': return card.optimization_task
    default:             return null
  }
}

/**
 * Состояние узла по данным сметы:
 *  - done  — задача этапа completed;
 *  - run   — задача этапа идёт (pending/processing/paused);
 *  - error — задача этапа failed/cancelled (перезапуск живёт в контенте этапа);
 *  - lock  — этап недоступен (computeGuard даёт hard-блок для входа в этап);
 *  - wait  — доступен, но ещё не запускался.
 */
export function computeNodeState(card: WorkflowCard, stage: KanbanStage): NodeState {
  const task = stageTask(card, stage)
  if (task) {
    if (task.status === 'completed') return 'done'
    if (task.status === 'failed' || task.status === 'cancelled') return 'error'
    return 'run' // pending | processing | paused
  }
  const guard = computeGuard(card, stage)
  if (!guard.allowed && guard.blockType === 'hard') return 'lock'
  return 'wait'
}

/** Компактная подпись прогресса «N/M» для идущего узла из безопасной выжимки. */
export function nodeProgressCaption(task: TaskBrief | null): string | null {
  const pd = task?.progress_data
  if (!pd) return null
  const total = pd.total_chunks ?? pd.chunks_total
  const done = pd.chunks_done
  if (typeof total === 'number' && total > 1 && typeof done === 'number' && done >= 0) {
    return `${Math.min(done, total)}/${total}`
  }
  return null
}

function NodeIcon({ state, index }: { state: NodeState; index: number }) {
  const c = STATE_STYLE[state]
  if (state === 'done')  return <Check size={16} color={c.icon} strokeWidth={3} />
  if (state === 'error') return <AlertTriangle size={15} color={c.icon} />
  if (state === 'lock')  return <Lock size={13} color={c.icon} />
  if (state === 'run')   return <Loader2 size={15} color={c.icon} style={{ animation: 'spin 0.9s linear infinite' }} />
  // wait
  return <span style={{ fontSize: '13px', fontWeight: 700, color: c.icon }}>{index + 1}</span>
}

interface Props {
  card: WorkflowCard
  selectedStage: KanbanStage
  onSelect: (stage: KanbanStage) => void
}

export function PipelineStepper({ card, selectedStage, onSelect }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        background: 'rgba(255,255,255,0.9)',
        border: '1px solid #e2e8f0',
        borderRadius: '16px',
        padding: '18px 12px 14px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.04)',
      }}
    >
      {PIPELINE_STAGES.map((stage, i) => {
        const state = computeNodeState(card, stage)
        const style = STATE_STYLE[state]
        const selected = stage === selectedStage
        const locked = state === 'lock'
        const lockReason = locked ? computeGuard(card, stage).message : ''
        const isLast = i === PIPELINE_STAGES.length - 1
        // Коннектор «залит», если предыдущий этап завершён.
        const connectorDone = computeNodeState(card, PIPELINE_STAGES[i]) === 'done'

        return (
          <React.Fragment key={stage}>
            <button
              type="button"
              onClick={() => { if (!locked) onSelect(stage) }}
              disabled={locked}
              title={locked ? lockReason : STAGE_LABELS[stage]}
              style={{
                flex: '1 1 0',
                minWidth: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '7px',
                background: 'none',
                border: 'none',
                padding: '2px 4px',
                cursor: locked ? 'not-allowed' : 'pointer',
              }}
            >
              <span
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: '50%',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: style.fill,
                  border: `2px solid ${style.ring}`,
                  boxShadow: selected ? `0 0 0 4px ${style.ring}33` : 'none',
                  transition: 'box-shadow 0.15s',
                }}
              >
                <NodeIcon state={state} index={i} />
              </span>
              <span
                style={{
                  fontSize: '12px',
                  fontWeight: selected ? 700 : 600,
                  color: selected ? '#1e293b' : style.label,
                  textAlign: 'center',
                  lineHeight: 1.2,
                }}
              >
                {STAGE_LABELS[stage]}
              </span>
              {style.caption && !locked && (
                <span style={{ fontSize: '10px', color: style.label, fontWeight: 500 }}>
                  {state === 'run'
                    ? (nodeProgressCaption(stageTask(card, stage)) ?? style.caption)
                    : style.caption}
                </span>
              )}
              {locked && lockReason && (
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '3px',
                    fontSize: '10px',
                    color: '#94a3b8',
                    textAlign: 'center',
                    lineHeight: 1.3,
                  }}
                >
                  <Lock size={9} color="#94a3b8" style={{ flexShrink: 0 }} />
                  {lockReason}
                </span>
              )}
            </button>

            {!isLast && (
              <div
                style={{
                  flex: '0 0 auto',
                  width: 'clamp(12px, 4vw, 40px)',
                  height: 2,
                  marginTop: 18,
                  borderRadius: 1,
                  background: connectorDone ? '#10b981' : '#e2e8f0',
                  transition: 'background 0.2s',
                }}
              />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}
