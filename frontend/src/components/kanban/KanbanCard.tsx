import React from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { WorkflowCard } from '../../types/workflow'
import { CardStageContent } from './CardStageContent'

interface Props {
  card: WorkflowCard
  isOverlay?: boolean
}

function KanbanCardInner({ card, isOverlay = false }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: card.id,
    data: { card },
  })

  const style: React.CSSProperties = {
    background: '#fff',
    border: '1px solid #e2e8f0',
    borderRadius: '8px',
    padding: '12px',
    marginBottom: '8px',
    cursor: isOverlay ? 'grabbing' : 'grab',
    boxShadow: isOverlay
      ? '0 4px 12px rgba(0,0,0,0.15)'
      : '0 1px 3px rgba(0,0,0,0.06)',
    opacity: isOverlay ? 0.85 : isDragging ? 0.4 : 1,
    transform: CSS.Translate.toString(transform),
    userSelect: 'none',
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
        <span style={{ fontWeight: 500, fontSize: '14px', color: '#1e293b', flex: 1, marginRight: '8px', wordBreak: 'break-word' }}>
          {card.name}
        </span>
        {/* Drag handle */}
        <span
          {...listeners}
          style={{ cursor: 'grab', color: '#94a3b8', fontSize: '16px', flexShrink: 0, lineHeight: 1 }}
          title="Перетащить"
        >
          ⠿
        </span>
      </div>
      {!isOverlay && <CardStageContent card={card} />}
    </div>
  )
}

export const KanbanCard = React.memo(KanbanCardInner, (prev, next) =>
  prev.card.id === next.card.id &&
  prev.card.stage === next.card.stage &&
  prev.card.name === next.card.name &&
  prev.card.list_task?.status === next.card.list_task?.status &&
  prev.card.completeness_task?.status === next.card.completeness_task?.status &&
  prev.card.estimate_task?.status === next.card.estimate_task?.status &&
  prev.card.optimization_task?.status === next.card.optimization_task?.status
)
