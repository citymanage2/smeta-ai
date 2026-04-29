import React from 'react'
import { useDroppable } from '@dnd-kit/core'
import { Plus } from 'lucide-react'
import { WorkflowCard, KanbanStage } from '../../types/workflow'
import { KanbanCard } from './KanbanCard'

const STAGE_LABELS: Record<KanbanStage, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

const STAGE_COLORS: Record<KanbanStage, string> = {
  list: '#8B5CF6',
  completeness: '#3B82F6',
  estimate: '#F59E0B',
  optimization: '#10B981',
}

interface Props {
  stage: KanbanStage
  cards: WorkflowCard[]
  onAddCard?: () => void
}

export function KanbanColumn({ stage, cards, onAddCard }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: stage })
  const color = STAGE_COLORS[stage]

  const columnStyle: React.CSSProperties = {
    background: isOver ? 'rgba(241,245,249,0.55)' : 'rgba(255,255,255,0.28)',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderRadius: '20px',
    padding: '20px',
    minWidth: '260px',
    flex: '1',
    maxWidth: '340px',
    border: isOver ? '2px dashed #93c5fd' : '1px solid rgba(226,232,240,0.65)',
    transition: 'background 0.15s, border 0.15s',
    boxShadow: '0 4px 24px rgba(0,0,0,0.04)',
  }

  const headerStyle: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  }

  const headerLeftStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  }

  const dotStyle: React.CSSProperties = {
    width: '12px',
    height: '12px',
    borderRadius: '50%',
    backgroundColor: color,
    flexShrink: 0,
  }

  const titleStyle: React.CSSProperties = {
    fontWeight: 600,
    fontSize: '14px',
    color: '#1e293b',
    letterSpacing: '-0.01em',
  }

  const badgeStyle: React.CSSProperties = {
    background: 'rgba(226,232,240,0.8)',
    borderRadius: '20px',
    padding: '2px 9px',
    fontSize: '12px',
    fontWeight: 500,
    color: '#64748b',
  }

  const addButtonStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '28px',
    height: '28px',
    borderRadius: '50%',
    background: 'rgba(255,255,255,0.6)',
    border: '1px solid rgba(226,232,240,0.8)',
    cursor: 'pointer',
    transition: 'background 0.15s',
    flexShrink: 0,
    padding: 0,
  }

  const emptyStyle: React.CSSProperties = {
    color: '#94a3b8',
    fontSize: '13px',
    textAlign: 'center',
    padding: '28px 0',
    fontStyle: 'italic',
  }

  return (
    <div style={columnStyle} ref={setNodeRef}>
      <div style={headerStyle}>
        <div style={headerLeftStyle}>
          <div style={dotStyle} />
          <span style={titleStyle}>{STAGE_LABELS[stage]}</span>
          <span style={badgeStyle}>{cards.length}</span>
        </div>
        {onAddCard && (
          <button
            onClick={onAddCard}
            style={addButtonStyle}
            title="Добавить карточку"
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.9)'
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.6)'
            }}
          >
            <Plus size={14} color="#475569" />
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {cards.map((card) => (
          <KanbanCard key={card.id} card={card} />
        ))}
      </div>

      {cards.length === 0 && (
        <div style={emptyStyle}>
          {stage === 'list' || stage === 'optimization' ? 'Нажмите + чтобы начать' : 'Перетащите карточку'}
        </div>
      )}
    </div>
  )
}
