import { useEffect, useState, useCallback } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  closestCorners,
  DragStartEvent,
  DragEndEvent,
} from '@dnd-kit/core'
import { WorkflowCard, KanbanStage } from '../../types/workflow'
import { useKanbanStore } from '../../stores/kanban'
import { KanbanCard } from './KanbanCard'
import { KanbanColumn } from './KanbanColumn'
import { CreateCardModal } from './CreateCardModal'

const STAGES: KanbanStage[] = ['list', 'completeness', 'estimate', 'optimization']

interface Props {
  projectId: string
}

export function KanbanBoard({ projectId }: Props) {
  const { cards, loading, fetchCards, moveCard, clearCards } = useKanbanStore()
  const [activeCard, setActiveCard] = useState<WorkflowCard | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [hardBlockMsg, setHardBlockMsg] = useState<string | null>(null)
  const [softBlock, setSoftBlock] = useState<{ cardId: string; stage: KanbanStage; message: string } | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  useEffect(() => {
    clearCards()
  }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval>
    let controller = new AbortController()

    const startPolling = () => {
      controller = new AbortController()
      fetchCards(projectId)
      intervalId = setInterval(() => {
        if (!document.hidden) {
          controller.abort()
          controller = new AbortController()
          fetchCards(projectId)
        }
      }, 5000)
    }

    const handleVisibility = () => {
      if (document.hidden) {
        clearInterval(intervalId)
      } else {
        startPolling()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)
    startPolling()

    return () => {
      clearInterval(intervalId)
      controller.abort()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const card = event.active.data.current?.card as WorkflowCard | undefined
    if (card) setActiveCard(card)
  }, [])

  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    setActiveCard(null)
    const { active, over } = event
    if (!over) return

    const cardId = String(active.id)
    const targetStage = String(over.id) as KanbanStage
    const sourceCard = cards.find((c) => c.id === cardId)
    if (!sourceCard || sourceCard.stage === targetStage) return

    const guard = await moveCard(cardId, targetStage)

    if (!guard.allowed && guard.blockType === 'hard') {
      setHardBlockMsg(guard.message)
      setTimeout(() => setHardBlockMsg(null), 4000)
      return
    }

    if (guard.blockType === 'soft') {
      setSoftBlock({ cardId, stage: targetStage, message: guard.message })
    }
  }, [cards, moveCard])

  const handleSoftConfirm = useCallback(async () => {
    if (!softBlock) return
    setSoftBlock(null)
    await moveCard(softBlock.cardId, softBlock.stage, true)
  }, [softBlock, moveCard])

  const columnCards = (stage: KanbanStage) => cards.filter((c) => c.stage === stage)

  return (
    <div>
      {hardBlockMsg && (
        <div style={{
          background: '#fef2f2',
          border: '1px solid #fca5a5',
          borderRadius: '8px',
          padding: '10px 16px',
          marginBottom: '12px',
          color: '#dc2626',
          fontSize: '14px',
        }}>
          {hardBlockMsg}
        </div>
      )}

      {softBlock && (
        <div style={{
          background: '#fffbeb',
          border: '1px solid #fcd34d',
          borderRadius: '8px',
          padding: '12px 16px',
          marginBottom: '12px',
          fontSize: '14px',
          color: '#92400e',
        }}>
          <div style={{ marginBottom: '10px' }}>{softBlock.message}</div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleSoftConfirm}
              style={{
                background: '#3b82f6',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                padding: '6px 14px',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Пропустить
            </button>
            <button
              onClick={() => setSoftBlock(null)}
              style={{
                background: '#f1f5f9',
                color: '#475569',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                padding: '6px 14px',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Вернуться
            </button>
          </div>
        </div>
      )}

      {loading && cards.length === 0 && (
        <div style={{ color: '#94a3b8', fontSize: '14px', padding: '20px' }}>Загрузка…</div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start', overflowX: 'auto', paddingBottom: '8px' }}>
          {STAGES.map((stage) => (
            <KanbanColumn
              key={stage}
              stage={stage}
              cards={columnCards(stage)}
              onAddCard={stage === 'list' ? () => setShowCreateModal(true) : undefined}
            />
          ))}
        </div>

        <DragOverlay>
          {activeCard ? <KanbanCard card={activeCard} isOverlay /> : null}
        </DragOverlay>
      </DndContext>

      {showCreateModal && (
        <CreateCardModal
          projectId={projectId}
          onClose={() => setShowCreateModal(false)}
        />
      )}
    </div>
  )
}
