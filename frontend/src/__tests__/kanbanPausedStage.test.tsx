/**
 * Пауза по балансу API видна прямо на доске (план 2026-08-06).
 *
 * Задача при исчерпании баланса Anthropic уходит в `paused`, а не в `failed`:
 * прогресс сохранён, поллер возобновит её сам. До этого плана канбан такой
 * статус не разбирал вовсе — стадия «Смета» показывала заголовок и пустоту.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

vi.mock('../api/workflowCards', () => ({
  // Мета файлов не нужна: стадии переживают её отсутствие (fallback-вид).
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

vi.mock('../api/tasks', () => ({
  restartTask: vi.fn().mockResolvedValue({ task_id: 't' }),
  resumeTask: vi.fn().mockResolvedValue({ task_id: 't' }),
}))

vi.mock('../api/projects', () => ({ downloadSlotFile: vi.fn() }))

const fetchCards = vi.fn().mockResolvedValue(undefined)
const startTask = vi.fn()

const storeState = {
  startTask,
  fetchCards,
  submittingCardIds: new Set<string>(),
  pendingListTasks: {},
  clearPendingListTask: vi.fn(),
}

vi.mock('../stores/kanban', () => ({
  // Стадии читают стор целиком, диспетчер — селектором: поддерживаем оба вызова.
  useKanbanStore: (selector?: (s: typeof storeState) => unknown) =>
    (selector ? selector(storeState) : storeState),
}))

import { resumeTask } from '../api/tasks'
import { CardStageContent } from '../components/kanban/CardStageContent'
import { WorkflowCard, TaskBrief, TaskStatus, KanbanStage } from '../types/workflow'

function task(status: TaskStatus, taskType: string, id = `task-${taskType}`): TaskBrief {
  return {
    id,
    task_type: taskType,
    status,
    name: null,
    created_at: '2026-08-06T10:00:00Z',
    input_files: [],
    progress_message: null,
  }
}

function makeCard(stage: KanbanStage, over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'Липовка кровля',
    stage,
    list_task_id: 't1',
    completeness_task_id: null,
    estimate_task_id: null,
    optimization_task_id: null,
    list_task: task('completed', 'LIST_FROM_GRAND', 't1'),
    completeness_task: null,
    estimate_task: null,
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-08-06T10:00:00Z',
    updated_at: '2026-08-06T10:00:00Z',
    ...over,
  }
}

async function renderStage(card: WorkflowCard) {
  render(<CardStageContent card={card} />)
  // Ждём провалившийся запрос меты, чтобы не ловить act-предупреждения.
  await waitFor(() => expect(screen.getByText(/На паузе/)).toBeInTheDocument())
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(resumeTask).mockResolvedValue({ task_id: 't' } as never)
})

describe('Канбан — задача на паузе по балансу API', () => {
  it('стадия «Смета»: бейдж, пояснение про баланс и кнопка продолжения', async () => {
    await renderStage(makeCard('estimate', {
      estimate_task_id: 't3',
      estimate_task: task('paused', 'ESTIMATE_FROM_LIST', 't3'),
    }))

    expect(screen.getByTestId('kanban-paused')).toBeInTheDocument()
    expect(screen.getByText(/баланс api/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Продолжить сейчас/ })).toBeInTheDocument()
  })

  it('стадия «Смета» на паузе не предлагает создать смету заново', async () => {
    await renderStage(makeCard('estimate', {
      estimate_task_id: 't3',
      estimate_task: task('paused', 'ESTIMATE_FROM_LIST', 't3'),
    }))

    expect(screen.queryByRole('button', { name: /Создать смету/ })).not.toBeInTheDocument()
  })

  it('клик по «Продолжить сейчас» зовёт resumeTask с id задачи', async () => {
    await renderStage(makeCard('estimate', {
      estimate_task_id: 't3',
      estimate_task: task('paused', 'ESTIMATE_FROM_LIST', 't3'),
    }))

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(resumeTask).toHaveBeenCalledWith('t3'))
  })

  it('после успешного продолжения доска перечитывается', async () => {
    await renderStage(makeCard('estimate', {
      estimate_task_id: 't3',
      estimate_task: task('paused', 'ESTIMATE_FROM_LIST', 't3'),
    }))

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(fetchCards).toHaveBeenCalledWith('proj-1'))
  })

  it('ошибка продолжения показывается текстом, кнопка снова доступна', async () => {
    vi.mocked(resumeTask).mockRejectedValue(new Error('boom'))
    await renderStage(makeCard('estimate', {
      estimate_task_id: 't3',
      estimate_task: task('paused', 'ESTIMATE_FROM_LIST', 't3'),
    }))

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(screen.getByText(/Не удалось возобновить/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Продолжить сейчас/ })).toBeEnabled()
  })

  it('стадия «Полнота»: пауза видна и управляема', async () => {
    await renderStage(makeCard('completeness', {
      completeness_task_id: 't2',
      completeness_task: task('paused', 'CHECK_LIST_COMPLETENESS', 't2'),
    }))

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(resumeTask).toHaveBeenCalledWith('t2'))
    expect(screen.queryByRole('button', { name: /Запустить проверку полноты/ })).not.toBeInTheDocument()
  })

  it('стадия «Перечень»: пауза видна и управляема', async () => {
    await renderStage(makeCard('list', {
      list_task: task('paused', 'LIST_FROM_GRAND', 't1'),
    }))

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(resumeTask).toHaveBeenCalledWith('t1'))
  })

  it('стадия «Оптимизация»: пауза видна и управляема', async () => {
    await renderStage(makeCard('optimization', {
      optimization_task_id: 't4',
      optimization_task: task('paused', 'ESTIMATE_OPTIMIZATION', 't4'),
    }))

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(resumeTask).toHaveBeenCalledWith('t4'))
  })
})
