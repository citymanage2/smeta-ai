import React from 'react'
import { useDroppable } from '@dnd-kit/core'
import { WorkflowCard, KanbanStage } from '../../types/workflow'
import { KanbanCard } from './KanbanCard'

const STAGE_LABELS: Record<KanbanStage, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

interface Props {
  stage: KanbanStage
  cards: WorkflowCard[]
  onAddCard?: () => void
}

export function KanbanColumn({ stage, cards, onAddCard }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: stage })

  const columnStyle: React.CSSProperties = {
    background: isOver ? '#f1f5f9' : '#f8fafc',
    borderRadius: '10px',
    padding: '12px',
    minWidth: '260px',
    flex: '1',
    maxWidth: '340px',
    transition: 'background 0.15s',
    border: isOver ? '2px dashed #93c5fd' : '2px solid transparent',
  }

  const headerStyle: React.CSSProperties = {
    fontWeight: 600,
    fontSize: '14px',
    color: '#475569',
    marginBottom: '12px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  }

  const badgeStyle: React.CSSProperties = {
    background: '#e2e8f0',
    borderRadius: '12px',
    padding: '2px 8px',
    fontSize: '12px',
    color: '#64748b',
  }

  return (
    <div style={columnStyle} ref={setNodeRef}>
      <div style={headerStyle}>
        <span>{STAGE_LABELS[stage]}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={badgeStyle}>{cards.length}</span>
          {stage === 'list' && onAddCard && (
            <button
              onClick={onAddCard}
              style={{
                background: '#3b82f6',
                color: '#fff',
                border: 'none',
                borderRadius: '50%',
                width: '24px',
                height: '24px',
                fontSize: '16px',
                lineHeight: '24px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 0,
              }}
              title="Добавить карточку"
            >
              +
            </button>
          )}
        </div>
      </div>

      {cards.map((card) => (
        <KanbanCard key={card.id} card={card} />
      ))}

      {cards.length === 0 && (
        <div style={{ color: '#94a3b8', fontSize: '13px', textAlign: 'center', padding: '24px 0' }}>
          {stage === 'list' ? 'Нажмите + чтобы начать' : 'Перетащите карточку'}
        </div>
      )}
    </div>
  )
}
