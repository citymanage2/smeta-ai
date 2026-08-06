import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useKanbanStore } from '../stores/kanban'
import { CreateCardModal } from './kanban/CreateCardModal'
// Все четыре стадии секциями — тот же контент стадий, что и внутри сметы.
import { CardStagesAccordion } from './kanban/CardStageContent'
import { MAIN_PADDING_X } from './layoutMetrics'
import UsageChips from './card/UsageChips'
import { cardEstimateCost, cardUsage, formatRub } from '../utils/usageMetrics'
import { WorkflowCard } from '../types/workflow'

/** Поля слева и справа у сетки смет. Уже общих полей страницы: в ряду три
 *  карточки, и каждый лишний пиксель поля отъедает у них ширину. */
const GRID_GUTTER = 8

/**
 * Сумма сформированной сметы. Оптимизация важнее сметы: если смету
 * оптимизировали, в тендер идёт её сумма. Прочерк — только когда сметы ещё нет.
 */
function EstimateSum({ card }: { card: WorkflowCard }) {
  const cost = cardEstimateCost(card)
  if (cost == null) {
    return <span style={{ color: '#94a3b8' }}>—</span>
  }
  const optimized = card.optimization_task?.cost != null
  return (
    <span
      title={optimized ? 'Сумма после оптимизации' : 'Сумма сформированной сметы'}
      style={{ fontWeight: 600, color: optimized ? '#c2410c' : '#0f766e', whiteSpace: 'nowrap' }}
    >
      {formatRub(cost)}
    </span>
  )
}

interface Props {
  projectId: string
  /** Вызывается после создания сметы — родитель переключает вид на канбан,
   *  где отложенный файл перечня подхватывается и запускается (Фаза 3 уберёт этот прыжок). */
  onCardCreated: () => void
  /** Готовое значение `top` для шапки списка: высота закреплённых шапок
   *  родителя минус верхний отступ окна прокрутки (`MAIN_PADDING_TOP`).
   *  Бывает отрицательным — так и должно быть, компенсация паддинга. */
  stickyTop?: number
}

/** Одна смета: шапка с именем, суммой и затратами — и стадии секциями. */
function SmetaCard({ card }: { card: WorkflowCard }) {
  const navigate = useNavigate()
  const usage = cardUsage(card)

  return (
    <article
      style={{
        backgroundColor: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        padding: '10px 12px',
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <button
          onClick={() => navigate(`/projects/${card.project_id}/cards/${card.id}`)}
          title="Открыть смету"
          style={{
            display: 'inline-flex', alignItems: 'baseline', gap: '5px', minWidth: 0,
            background: 'none', border: 'none', padding: 0, cursor: 'pointer',
            font: 'inherit', color: '#1e293b', fontWeight: 600, fontSize: '15px', textAlign: 'left',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#2563eb' }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#1e293b' }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {card.name}
          </span>
          <span style={{ color: '#94a3b8', fontSize: '13px', flexShrink: 0 }}>↗</span>
        </button>
        {/* Сумма — справа в шапке: деньги заказчика, их сравнивают между
            карточками, поэтому место у них одно и то же в каждой. */}
        <span style={{ marginLeft: 'auto', fontSize: '14px' }}>
          <EstimateSum card={card} />
        </span>
      </div>

      {/* Затраты на ИИ по всей смете — под суммой, а не рядом: там деньги
          заказчика, здесь наша себестоимость, и путать их нельзя. */}
      {usage.hasData && (
        <div style={{ marginTop: '4px' }}>
          <UsageChips usage={usage} variant="total" />
        </div>
      )}

      <div style={{ marginTop: '8px' }}>
        <CardStagesAccordion card={card} />
      </div>
    </article>
  )
}

export function SmetaList({ projectId, onCardCreated, stickyTop = 0 }: Props) {
  const { cards, loading, fetchCards } = useKanbanStore()
  const [showCreateModal, setShowCreateModal] = useState(false)

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

  const placeholderStyle: React.CSSProperties = {
    textAlign: 'center', padding: '32px', backgroundColor: '#fff',
    borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px',
  }

  return (
    // Сетка выходит за поля страницы целиком, а своё поле в 8px рисует сама:
    // три карточки в ряд стоят того, чтобы поле было 8px вместо общих 24px.
    // Ни overflow, ни overflowX здесь быть не может — любой из них делает
    // список своим окном прокрутки, и шапка перестаёт прилипать к верху.
    <div style={{ margin: `0 ${-MAIN_PADDING_X}px` }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: stickyTop,
          zIndex: 20,
          backgroundColor: '#f8fafc',
          padding: `0 ${GRID_GUTTER}px 12px`,
        }}
      >
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

      <div style={{ padding: `0 ${GRID_GUTTER}px` }}>
        {loading && cards.length === 0 ? (
          <div style={placeholderStyle}>Загрузка…</div>
        ) : cards.length === 0 ? (
          <div style={placeholderStyle}>Смет в проекте пока нет. Нажмите «+ Добавить смету».</div>
        ) : (
          // Колонки и промежутки — в `.smeta-grid` (index.css): три в ряд,
          // на узком экране два и один. Медиазапросы инлайновым стилем не задать.
          <div className="smeta-grid">
            {cards.map((card) => (
              <SmetaCard key={card.id} card={card} />
            ))}
          </div>
        )}
      </div>

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
