import React, { useState } from 'react'
import { createPortal } from 'react-dom'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Trash2, LayoutList } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { WorkflowCard } from '../../types/workflow'
import { CardStageContent } from './CardStageContent'
import { useKanbanStore } from '../../stores/kanban'

interface Props {
  card: WorkflowCard
  isOverlay?: boolean
}

function KanbanCardInner({ card, isOverlay = false }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: card.id,
    data: { card },
  })
  const deleteCard = useKanbanStore((s) => s.deleteCard)
  const navigate = useNavigate()
  const [showConfirm, setShowConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleDeleteConfirm = async () => {
    setDeleting(true)
    try {
      await deleteCard(card.id)
    } finally {
      setDeleting(false)
      setShowConfirm(false)
    }
  }

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

  const trashStyle: React.CSSProperties = {
    cursor: 'pointer',
    color: '#cbd5e1',
    flexShrink: 0,
    lineHeight: 1,
    marginTop: '1px',
    background: 'none',
    border: 'none',
    padding: 0,
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          {!isOverlay && (
            <button
              style={{ ...trashStyle, color: '#cbd5e1' }}
              title="Открыть карточку"
              onClick={(e) => {
                e.stopPropagation()
                navigate(`/projects/${card.project_id}/cards/${card.id}`)
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#cbd5e1' }}
            >
              <LayoutList size={14} />
            </button>
          )}
          {!isOverlay && (
            <button
              style={trashStyle}
              title="Удалить карточку"
              onClick={(e) => { e.stopPropagation(); setShowConfirm(true) }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#ef4444' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#cbd5e1' }}
            >
              <Trash2 size={14} />
            </button>
          )}
          <span
            {...listeners}
            style={gripStyle}
            title="Перетащить"
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#94a3b8' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#cbd5e1' }}
          >
            <GripVertical size={16} />
          </span>
        </div>
      </div>

      {!isOverlay && (
        <div style={dividerStyle}>
          <CardStageContent card={card} />
        </div>
      )}

      {showConfirm && createPortal(
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(15,23,42,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => !deleting && setShowConfirm(false)}
        >
          <div
            style={{
              background: 'rgba(255,255,255,0.95)',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              borderRadius: '16px',
              padding: '28px 28px 24px',
              width: '360px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.16)',
              border: '1px solid rgba(226,232,240,0.7)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <Trash2 size={18} color="#ef4444" />
              <span style={{ fontWeight: 700, fontSize: '15px', color: '#0f172a' }}>Удалить карточку?</span>
            </div>
            <p style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6, margin: '0 0 20px' }}>
              Карточка <strong>«{card.name}»</strong> и все связанные задачи будут удалены безвозвратно.
            </p>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                disabled={deleting}
                onClick={() => setShowConfirm(false)}
                style={{
                  background: 'rgba(241,245,249,0.9)',
                  border: '1px solid rgba(226,232,240,0.8)',
                  borderRadius: '8px',
                  padding: '7px 18px',
                  fontSize: '13px',
                  fontWeight: 500,
                  color: '#475569',
                  cursor: deleting ? 'not-allowed' : 'pointer',
                  opacity: deleting ? 0.6 : 1,
                }}
              >
                Отмена
              </button>
              <button
                disabled={deleting}
                onClick={handleDeleteConfirm}
                style={{
                  background: deleting ? '#fca5a5' : '#ef4444',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '7px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#fff',
                  cursor: deleting ? 'not-allowed' : 'pointer',
                  transition: 'background 0.15s',
                }}
              >
                {deleting ? 'Удаление…' : 'Удалить'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
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
  prev.card.completeness_task?.progress_message === next.card.completeness_task?.progress_message &&
  prev.card.estimate_task?.status === next.card.estimate_task?.status &&
  prev.card.estimate_task?.progress_message === next.card.estimate_task?.progress_message &&
  prev.card.optimization_task?.status === next.card.optimization_task?.status &&
  prev.card.optimization_task?.progress_message === next.card.optimization_task?.progress_message
)
