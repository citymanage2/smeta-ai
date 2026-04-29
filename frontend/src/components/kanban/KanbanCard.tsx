import React from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical } from 'lucide-react'
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

  const cardStyle: React.CSSProperties = {
    background: isOverlay || isDragging ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.68)',
    backdropFilter: 'blur(10px)',
    WebkitBackdropFilter: 'blur(10px)',
    border: '1px solid rgba(226,232,240,0.6)',
    borderRadius: '14px',
    padding: '16px',
    cursor: isOverlay ? 'grabbing' : 'default',
    boxShadow: isOverlay
      ? '0 8px 32px rgba(0,0,0,0.14)'
      : isDragging
      ? '0 4px 16px rgba(0,0,0,0.10)'
      : '0 2px 8px rgba(0,0,0,0.05)',
    opacity: isDragging ? 0.45 : 1,
    transform: CSS.Translate.toString(transform),
    userSelect: 'none',
    transition: 'box-shadow 0.2s, background 0.2s',
  }

  const headerStyle: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '12px',
    gap: '8px',
  }

  const titleStyle: React.CSSProperties = {
    fontWeight: 600,
    fontSize: '14px',
    color: '#1e293b',
    lineHeight: 1.4,
    letterSpacing: '-0.01em',
    flex: 1,
    wordBreak: 'break-word',
  }

  const gripStyle: React.CSSProperties = {
    cursor: 'grab',
    color: '#cbd5e1',
    flexShrink: 0,
    lineHeight: 1,
    marginTop: '1px',
    transition: 'color 0.15s',
  }

  const dividerStyle: React.CSSProperties = {
    borderTop: '1px solid rgba(226,232,240,0.5)',
    paddingTop: '12px',
    marginTop: '4px',
  }

  return (
    <div ref={setNodeRef} style={cardStyle} {...attributes}>
      <div style={headerStyle}>
        <span style={titleStyle}>{card.name}</span>
        <span
          {...listeners}
          style={gripStyle}
          title="Перетащить"
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.color = '#94a3b8'
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.color = '#cbd5e1'
          }}
        >
          <GripVertical size={16} />
        </span>
      </div>

      {!isOverlay && (
        <div style={dividerStyle}>
          <CardStageContent card={card} />
        </div>
      )}
    </div>
  )
}

export const KanbanCard = React.memo(KanbanCardInner, (prev, next) =>
  prev.card.id === next.card.id &&
  prev.card.stage === next.card.stage &&
  prev.card.name === next.card.name &&
  prev.card.list_task?.status === next.card.list_task?.status &&
  prev.card.list_task?.progress_message === next.card.list_task?.progress_message &&
  JSON.stringify(prev.card.list_task?.input_files) === JSON.stringify(next.card.list_task?.input_files) &&
  prev.card.completeness_task?.status === next.card.completeness_task?.status &&
  prev.card.estimate_task?.status === next.card.estimate_task?.status &&
  prev.card.optimization_task?.status === next.card.optimization_task?.status
)
