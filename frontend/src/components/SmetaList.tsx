import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useKanbanStore } from '../stores/kanban'
import { WorkflowCard, KanbanStage, TaskBrief } from '../types/workflow'
import { CreateCardModal } from './kanban/CreateCardModal'

const STAGE_LABELS: Record<KanbanStage, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

// Состояние текущей стадии — по статусу задачи соответствующего этапа.
const STATE_STYLE: Record<string, { label: string; color: string }> = {
  completed: { label: 'Готово', color: '#10b981' },
  processing: { label: 'Идёт', color: '#3b82f6' },
  pending: { label: 'В очереди', color: '#f59e0b' },
  paused: { label: 'На паузе', color: '#b45309' },
  failed: { label: 'Ошибка', color: '#ef4444' },
  cancelled: { label: 'Отменено', color: '#94a3b8' },
}

const WAITING_STATE = { label: 'Ожидает', color: '#94a3b8' }

function stageTask(card: WorkflowCard): TaskBrief | null {
  switch (card.stage) {
    case 'list':
      return card.list_task
    case 'completeness':
      return card.completeness_task
    case 'estimate':
      return card.estimate_task
    case 'optimization':
      return card.optimization_task
    default:
      return null
  }
}

function StateBadge({ card }: { card: WorkflowCard }) {
  const task = stageTask(card)
  const s = task ? (STATE_STYLE[task.status] ?? WAITING_STATE) : WAITING_STATE
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: s.color, fontWeight: 600 }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.color, display: 'inline-block', flexShrink: 0 }} />
      {s.label}
    </span>
  )
}

interface Props {
  projectId: string
  /** Вызывается после создания сметы — родитель переключает вид на канбан,
   *  где отложенный файл перечня подхватывается и запускается (Фаза 3 уберёт этот прыжок). */
  onCardCreated: () => void
}

export function SmetaList({ projectId, onCardCreated }: Props) {
  const { cards, loading, fetchCards } = useKanbanStore()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const navigate = useNavigate()

  // Поллинг через тот же стор, что и канбан — данные не дублируются.
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | undefined

    const poll = () => {
      if (!document.hidden) fetchCards(projectId)
    }

    const handleVisibility = () => {
      if (document.hidden) {
        if (intervalId !== undefined) { clearInterval(intervalId); intervalId = undefined }
      } else if (intervalId === undefined) {
        fetchCards(projectId)
        intervalId = setInterval(poll, 5000)
      }
    }

    fetchCards(projectId)
    intervalId = setInterval(poll, 5000)
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      if (intervalId !== undefined) clearInterval(intervalId)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  const headerCellStyle: React.CSSProperties = {
    textAlign: 'left',
    fontSize: '12px',
    fontWeight: 600,
    color: '#94a3b8',
    padding: '10px 16px',
    borderBottom: '1px solid #e2e8f0',
  }

  const cellStyle: React.CSSProperties = {
    fontSize: '14px',
    color: '#1e293b',
    padding: '14px 16px',
    borderBottom: '1px solid #f1f5f9',
    verticalAlign: 'middle',
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', margin: 0 }}>
          Сметы ({cards.length})
        </h2>
        <button
          onClick={() => setShowCreateModal(true)}
          style={{ padding: '7px 14px', backgroundColor: '#2563eb', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#fff', fontWeight: 500 }}
        >
          + Добавить смету
        </button>
      </div>

      {loading && cards.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
          Загрузка…
        </div>
      ) : cards.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
          Смет в проекте пока нет. Нажмите «+ Добавить смету».
        </div>
      ) : (
        <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={headerCellStyle}>Смета</th>
                  <th style={headerCellStyle}>Этап</th>
                  <th style={headerCellStyle}>Состояние</th>
                  <th style={{ ...headerCellStyle, textAlign: 'right' }}>Сумма</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  <tr
                    key={card.id}
                    onClick={() => navigate(`/projects/${card.project_id}/cards/${card.id}`)}
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f8fafc')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    <td style={{ ...cellStyle, fontWeight: 600 }}>{card.name}</td>
                    <td style={{ ...cellStyle, color: '#475569' }}>{STAGE_LABELS[card.stage]}</td>
                    <td style={cellStyle}><StateBadge card={card} /></td>
                    <td style={{ ...cellStyle, textAlign: 'right', color: '#94a3b8' }}>—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showCreateModal && (
        <CreateCardModal
          projectId={projectId}
          stage="list"
          onClose={() => setShowCreateModal(false)}
          onCreated={() => { setShowCreateModal(false); onCardCreated() }}
        />
      )}
    </div>
  )
}
