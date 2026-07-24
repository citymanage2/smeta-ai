import { useEffect, useState, useCallback } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  pointerWithin,
  closestCenter,
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
  const [showCreateOptimizationModal, setShowCreateOptimizationModal] = useState(false)
  const [hardBlockMsg, setHardBlockMsg] = useState<string | null>(null)
  const [softBlock, setSoftBlock] = useState<{ cardId: string; stage: KanbanStage; message: string } | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  useEffect(() => {
    clearCards()
  }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | undefined
    let controller = new AbortController()

    const startPolling = () => {
      if (intervalId !== undefined) clearInterval(intervalId)
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
        intervalId = undefined
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
    <div style={{
      background: 'linear-gradient(135deg, #ede9fe 0%, #f8fafc 45%, #d1fae5 100%)',
      borderRadius: '16px',
      padding: '20px',
      minHeight: '400px',
    }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '16px',
      }}>
        <h2 style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#1e293b' }}>Сметы</h2>
        <span style={{ fontSize: '13px', color: '#64748b' }}>{cards.length}</span>
      </div>

      {hardBlockMsg && (
        <div style={{
          background: 'rgba(254,242,242,0.85)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
          border: '1px solid rgba(252,165,165,0.6)',
          borderRadius: '12px',
          padding: '12px 16px',
          marginBottom: '16px',
          color: '#dc2626',
          fontSize: '14px',
          fontWeight: 500,
        }}>
          {hardBlockMsg}
        </div>
      )}

      {softBlock && (
        <div style={{
          background: 'rgba(255,251,235,0.9)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
          border: '1px solid rgba(252,211,77,0.7)',
          borderRadius: '12px',
          padding: '14px 16px',
          marginBottom: '16px',
          fontSize: '14px',
          color: '#92400e',
        }}>
          <div style={{ marginBottom: '12px', fontWeight: 500 }}>{softBlock.message}</div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleSoftConfirm}
              style={{
                background: '#3b82f6',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '6px 16px',
                fontSize: '13px',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              Пропустить
            </button>
            <button
              onClick={() => setSoftBlock(null)}
              style={{
                background: 'rgba(255,255,255,0.7)',
                color: '#475569',
                border: '1px solid rgba(226,232,240,0.8)',
                borderRadius: '8px',
                padding: '6px 16px',
                fontSize: '13px',
                fontWeight: 500,
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
        collisionDetection={(args) => {
          const hits = pointerWithin(args)
          return hits.length > 0 ? hits : closestCenter(args)
        }}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start', overflowX: 'auto', paddingBottom: '8px' }}>
          {STAGES.map((stage) => (
            <KanbanColumn
              key={stage}
              stage={stage}
              cards={columnCards(stage)}
              onAddCard={
                stage === 'list' ? () => setShowCreateModal(true) :
                stage === 'optimization' ? () => setShowCreateOptimizationModal(true) :
                undefined
              }
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
          stage="list"
          onClose={() => setShowCreateModal(false)}
        />
      )}

      {showCreateOptimizationModal && (
        <CreateCardModal
          projectId={projectId}
          stage="optimization"
          onClose={() => setShowCreateOptimizationModal(false)}
        />
      )}
    </div>
  )
}
