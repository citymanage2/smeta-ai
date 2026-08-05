import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useKanbanStore } from '../stores/kanban'
import { CreateCardModal } from './kanban/CreateCardModal'
// Дорожка стадий и правило выбора показываемой стадии — те же, что на странице сметы.
import { CompactPipeline, defaultStage } from './pipeline/PipelineStepper'
import { CardStageContent } from './kanban/CardStageContent'
import { useMeasuredHeight } from '../hooks/useMeasuredHeight'
import UsageChips from './card/UsageChips'
import { cardEstimateCost, cardUsage, formatRub } from '../utils/usageMetrics'
import { WorkflowCard } from '../types/workflow'

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
  /** Готовое значение `top` для первой шапки списка: высота закреплённых шапок
   *  родителя минус верхний отступ окна прокрутки (`MAIN_PADDING_TOP`).
   *  Бывает отрицательным — так и должно быть, компенсация паддинга. */
  stickyTop?: number
}

export function SmetaList({ projectId, onCardCreated, stickyTop = 0 }: Props) {
  const { cards, loading, fetchCards } = useKanbanStore()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const navigate = useNavigate()
  // Заголовок таблицы прилипает под строкой «Сметы (N)» — её высоту меряем.
  const { ref: titleRef, height: titleHeight } = useMeasuredHeight<HTMLDivElement>()

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
    // Закреплённая ячейка: при borderCollapse рамка отрывается от th, поэтому
    // нижняя линия нарисована тенью — она едет вместе с шапкой.
    boxShadow: 'inset 0 -1px 0 #e2e8f0',
    position: 'sticky',
    top: stickyTop + titleHeight,
    zIndex: 10,
    backgroundColor: '#fff',
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
      <div
        ref={titleRef}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: stickyTop,
          zIndex: 20,
          backgroundColor: '#f8fafc',
          paddingBottom: '12px',
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

      {loading && cards.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
          Загрузка…
        </div>
      ) : cards.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
          Смет в проекте пока нет. Нажмите «+ Добавить смету».
        </div>
      ) : (
        // Ни overflow: hidden, ни overflowX: auto здесь быть не может: любой из
        // них делает карточку своим окном прокрутки, и заголовок таблицы
        // перестаёт прилипать к верху страницы. Скруглённые углы шапки
        // рисуются на самих ячейках.
        <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ ...headerCellStyle, borderTopLeftRadius: '12px' }}>Смета</th>
                  <th style={headerCellStyle}>Стадии</th>
                  <th style={{ ...headerCellStyle, textAlign: 'right', borderTopRightRadius: '12px' }}>Сумма</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  // Строка целиком не кликабельна: под ней живут раскрывающиеся
                  // секции с файлами, и общий onClick перехватывал бы их клики.
                  <React.Fragment key={card.id}>
                    <tr>
                      <td style={{ ...cellStyle, borderBottom: 'none', fontWeight: 600, verticalAlign: 'top' }}>
                        <button
                          onClick={() => navigate(`/projects/${card.project_id}/cards/${card.id}`)}
                          title="Открыть смету"
                          style={{
                            display: 'inline-flex', alignItems: 'center', gap: '5px',
                            background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                            font: 'inherit', color: '#1e293b', fontWeight: 600, textAlign: 'left',
                          }}
                          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#2563eb' }}
                          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#1e293b' }}
                        >
                          {card.name}
                          <span style={{ color: '#94a3b8', fontSize: '13px' }}>↗</span>
                        </button>
                      </td>
                      <td style={{ ...cellStyle, borderBottom: 'none' }}>
                        <CompactPipeline card={card} />
                        {/* Затраты на ИИ по всей смете — под дорожкой стадий, а не
                            в колонке «Сумма»: там деньги заказчика, здесь наша
                            себестоимость, и путать их нельзя. */}
                        <div style={{ marginTop: '6px' }}>
                          <UsageChips usage={cardUsage(card)} variant="total" />
                        </div>
                      </td>
                      <td style={{ ...cellStyle, borderBottom: 'none', textAlign: 'right', verticalAlign: 'top' }}>
                        <EstimateSum card={card} />
                      </td>
                    </tr>
                    {/* Те же свёрнутые секции стадий с файлами, что и внутри сметы. */}
                    <tr>
                      <td colSpan={3} style={{ padding: '0 16px 14px', borderBottom: '1px solid #f1f5f9' }}>
                        <CardStageContent card={{ ...card, stage: defaultStage(card) }} />
                      </td>
                    </tr>
                  </React.Fragment>
                ))}
              </tbody>
            </table>
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
