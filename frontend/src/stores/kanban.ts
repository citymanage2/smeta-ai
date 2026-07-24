import { create } from 'zustand'
import {
  WorkflowCard,
  KanbanStage,
  GuardResult,
  StartTaskPayload,
} from '../types/workflow'
import {
  getWorkflowCards,
  createWorkflowCard,
  updateWorkflowCard,
  deleteWorkflowCard,
  startTask as apiStartTask,
} from '../api/workflowCards'

export interface PendingListTask {
  task_type: 'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND'
  files: File[]
}

interface KanbanStore {
  cards: WorkflowCard[]
  loading: boolean
  movingCardId: string | null
  submittingCardIds: Set<string>
  pendingListTasks: Record<string, PendingListTask>
  currentProjectId: string | null

  fetchCards: (projectId: string, signal?: AbortSignal) => Promise<void>
  createCard: (projectId: string, name: string, stage?: string) => Promise<WorkflowCard>
  moveCard: (cardId: string, toStage: KanbanStage, bypassSoft?: boolean) => Promise<GuardResult>
  startTask: (cardId: string, payload: StartTaskPayload) => Promise<WorkflowCard>
  deleteCard: (cardId: string) => Promise<void>
  clearCards: () => void
  setPendingListTask: (cardId: string, info: PendingListTask) => void
  clearPendingListTask: (cardId: string) => void
}

function computeGuard(card: WorkflowCard, toStage: KanbanStage): GuardResult {
  if (toStage === 'completeness') {
    const t = card.list_task
    if (!t) return { allowed: false, blockType: 'hard', message: 'Сначала создайте Перечень' }
    if (t.status === 'pending') return { allowed: false, blockType: 'hard', message: 'Перечень ещё не запущен' }
    if (t.status === 'processing') return { allowed: false, blockType: 'hard', message: 'Перечень ещё обрабатывается' }
    if (t.status === 'paused') return { allowed: false, blockType: 'hard', message: 'Перечень на паузе (баланс API) — продолжится автоматически' }
    if (t.status === 'failed') return { allowed: false, blockType: 'hard', message: 'Перечень завершился с ошибкой — исправьте' }
    if (t.status === 'cancelled') return { allowed: false, blockType: 'hard', message: 'Перечень отменён — создайте заново' }
    return { allowed: true, blockType: null, message: '' }
  }

  if (toStage === 'estimate') {
    const lt = card.list_task
    if (!lt) return { allowed: false, blockType: 'hard', message: 'Сначала создайте Перечень' }
    if (lt.status === 'pending') return { allowed: false, blockType: 'hard', message: 'Перечень ещё не запущен' }
    if (lt.status === 'processing') return { allowed: false, blockType: 'hard', message: 'Перечень ещё обрабатывается' }
    if (lt.status === 'paused') return { allowed: false, blockType: 'hard', message: 'Перечень на паузе (баланс API) — продолжится автоматически' }
    if (lt.status === 'failed') return { allowed: false, blockType: 'hard', message: 'Перечень завершился с ошибкой — исправьте' }
    if (lt.status === 'cancelled') return { allowed: false, blockType: 'hard', message: 'Перечень отменён — создайте заново' }
    // list completed — проверяем completeness (soft)
    const ct = card.completeness_task
    if (!ct) return { allowed: false, blockType: 'soft', message: 'Полнота не проверена. Создать смету на основе перечня?' }
    if (ct.status !== 'completed') return { allowed: false, blockType: 'soft', message: 'Полнота не завершена. Создать смету на основе перечня?' }
    return { allowed: true, blockType: null, message: '' }
  }

  // optimization — всегда разрешён
  return { allowed: true, blockType: null, message: '' }
}

export const useKanbanStore = create<KanbanStore>((set, get) => ({
  cards: [],
  loading: false,
  movingCardId: null,
  submittingCardIds: new Set(),
  pendingListTasks: {},
  currentProjectId: null,

  fetchCards: async (projectId, _signal) => {
    if (get().movingCardId !== null) return
    set({ currentProjectId: projectId })
    try {
      const cards = await getWorkflowCards(projectId)
      // Игнорируем ответ, если пользователь уже перешёл на другой проект
      if (get().currentProjectId !== projectId) return
      set({ cards })
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'CanceledError') return
      if (err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError') return
    }
  },

  createCard: async (projectId, name, stage) => {
    const card = await createWorkflowCard(projectId, name, stage)
    set((s) => ({ cards: [...s.cards, card] }))
    return card
  },

  moveCard: async (cardId, toStage, bypassSoft = false) => {
    const card = get().cards.find((c) => c.id === cardId)
    if (!card) return { allowed: false, blockType: 'hard' as const, message: 'Смета не найдена' }

    const guard = computeGuard(card, toStage)

    if (!guard.allowed && guard.blockType === 'hard') return guard
    if (guard.blockType === 'soft' && !bypassSoft) return guard

    set({ movingCardId: cardId })
    try {
      const updated = await updateWorkflowCard(cardId, { stage: toStage })
      set((s) => ({
        cards: s.cards.map((c) => (c.id === cardId ? updated : c)),
      }))
      return { allowed: true, blockType: null, message: '' }
    } finally {
      set({ movingCardId: null })
    }
  },

  startTask: async (cardId, payload) => {
    const { submittingCardIds } = get()
    if (submittingCardIds.has(cardId)) {
      throw new Error('Задача уже запускается')
    }
    set((s) => ({ submittingCardIds: new Set([...s.submittingCardIds, cardId]) }))
    try {
      const updated = await apiStartTask(cardId, payload)
      set((s) => ({
        cards: s.cards.map((c) => (c.id === cardId ? updated : c)),
      }))
      return updated
    } finally {
      set((s) => {
        const next = new Set(s.submittingCardIds)
        next.delete(cardId)
        return { submittingCardIds: next }
      })
    }
  },

  deleteCard: async (cardId) => {
    await deleteWorkflowCard(cardId)
    set((s) => {
      const { [cardId]: _, ...restPending } = s.pendingListTasks
      return { cards: s.cards.filter((c) => c.id !== cardId), pendingListTasks: restPending }
    })
  },

  clearCards: () => set({ cards: [], movingCardId: null, currentProjectId: null }),

  setPendingListTask: (cardId, info) => {
    set((s) => ({ pendingListTasks: { ...s.pendingListTasks, [cardId]: info } }))
  },

  clearPendingListTask: (cardId) => {
    set((s) => {
      const { [cardId]: _, ...rest } = s.pendingListTasks
      return { pendingListTasks: rest }
    })
  },
}))
