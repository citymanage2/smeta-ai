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

// Сетевой слой карточек. Стор канбана — настоящий: «доска перечитывается»
// проверяется запросом карточек, а не вызовом метода стора.
vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn().mockResolvedValue([]),
  createWorkflowCard: vi.fn(),
  updateWorkflowCard: vi.fn(),
  deleteWorkflowCard: vi.fn(),
  startTask: vi.fn(),
  launchTask: vi.fn(),
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

import { getWorkflowCards } from '../api/workflowCards'
import { useKanbanStore } from '../stores/kanban'
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

const initialStore = useKanbanStore.getState()

beforeEach(() => {
  vi.clearAllMocks()
  useKanbanStore.setState(initialStore, true)
  vi.mocked(resumeTask).mockResolvedValue({ task_id: 't' } as never)
  vi.mocked(getWorkflowCards).mockResolvedValue([])
})

const PAUSED_STAGES: {
  label: string
  card: WorkflowCard
  taskId: string
  /** Кнопка первого запуска стадии — на паузе её быть не должно. */
  freshStart?: RegExp
}[] = [
  {
    label: 'Смета',
    card: makeCard('estimate', {
      estimate_task_id: 't3',
      estimate_task: task('paused', 'ESTIMATE_FROM_LIST', 't3'),
    }),
    taskId: 't3',
    freshStart: /Создать смету/,
  },
  {
    label: 'Полнота',
    card: makeCard('completeness', {
      completeness_task_id: 't2',
      completeness_task: task('paused', 'CHECK_LIST_COMPLETENESS', 't2'),
    }),
    taskId: 't2',
    freshStart: /Запустить проверку полноты/,
  },
  {
    label: 'Перечень',
    card: makeCard('list', { list_task: task('paused', 'LIST_FROM_GRAND', 't1') }),
    taskId: 't1',
  },
  {
    label: 'Оптимизация',
    card: makeCard('optimization', {
      optimization_task_id: 't4',
      optimization_task: task('paused', 'ESTIMATE_OPTIMIZATION', 't4'),
    }),
    taskId: 't4',
  },
]

describe.each(PAUSED_STAGES)('Канбан — стадия «$label» на паузе по балансу API', ({ card, taskId, freshStart }) => {
  it('«Продолжить сейчас» возобновляет задачу стадии и перечитывает доску', async () => {
    await renderStage(card)

    fireEvent.click(screen.getByRole('button', { name: /Продолжить сейчас/ }))

    await waitFor(() => expect(resumeTask).toHaveBeenCalledWith(taskId))
    await waitFor(() => expect(getWorkflowCards).toHaveBeenCalledWith('proj-1'))
  })

  if (freshStart) {
    it('не предлагает запустить стадию заново', async () => {
      await renderStage(card)

      expect(screen.queryByRole('button', { name: freshStart })).not.toBeInTheDocument()
    })
  }
})

describe('Канбан — задача на паузе по балансу API', () => {
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
})
