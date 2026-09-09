/**
 * Оптимизация запускается кнопкой, а не сама (план 2026-09-09).
 *
 * Раньше «Использовать смету» одновременно прикрепляло смету и ставило задачу
 * в очередь: этап показывал «Идёт», хотя команды никто не давал. Теперь
 * прикрепление и запуск — два действия, и между ними задача живёт в статусе
 * `not_started`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

vi.mock('../api/workflowCards', () => ({
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

vi.mock('../api/tasks', () => ({
  restartTask: vi.fn().mockResolvedValue({ task_id: 't' }),
  resumeTask: vi.fn().mockResolvedValue({ task_id: 't' }),
}))

vi.mock('../api/projects', () => ({ downloadSlotFile: vi.fn() }))

const startTask = vi.fn().mockResolvedValue(undefined)
const launchTask = vi.fn().mockResolvedValue(undefined)
const fetchCards = vi.fn().mockResolvedValue(undefined)

const storeState = {
  startTask,
  launchTask,
  fetchCards,
  submittingCardIds: new Set<string>(),
  pendingListTasks: {},
  clearPendingListTask: vi.fn(),
}

vi.mock('../stores/kanban', () => ({
  useKanbanStore: (selector?: (s: typeof storeState) => unknown) =>
    (selector ? selector(storeState) : storeState),
  computeGuard: () => ({ allowed: true, blockType: null, message: '' }),
}))

import { CardStageContent } from '../components/kanban/CardStageContent'
import { computeNodeState } from '../components/pipeline/PipelineStepper'
import { WorkflowCard, TaskBrief, TaskStatus, KanbanStage } from '../types/workflow'

function task(status: TaskStatus, taskType: string, id = `task-${taskType}`): TaskBrief {
  return {
    id,
    task_type: taskType,
    status,
    name: null,
    created_at: '2026-09-09T10:00:00Z',
    input_files: status === 'not_started'
      ? [{ name: 'Смета_из_перечня.xlsx', mime_type: 'application/vnd.ms-excel', size_bytes: 100 }]
      : [],
    progress_message: null,
  }
}

function makeCard(stage: KanbanStage, over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'АР',
    stage,
    list_task_id: 't1',
    completeness_task_id: null,
    estimate_task_id: 't3',
    optimization_task_id: null,
    list_task: task('completed', 'LIST_FROM_GRAND', 't1'),
    completeness_task: null,
    estimate_task: task('completed', 'ESTIMATE_FROM_LIST', 't3'),
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-09-09T10:00:00Z',
    updated_at: '2026-09-09T10:00:00Z',
    ...over,
  }
}

const notStartedCard = () => makeCard('optimization', {
  optimization_task_id: 't4',
  optimization_task: task('not_started', 'ESTIMATE_OPTIMIZATION', 't4'),
})

beforeEach(() => {
  vi.clearAllMocks()
  storeState.submittingCardIds = new Set<string>()
})

describe('Оптимизация — запуск только по кнопке', () => {
  it('прикреплённая, но не запущенная смета показывает кнопку «Начать оптимизацию»', async () => {
    render(<CardStageContent card={notStartedCard()} />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Начать оптимизацию/ })).toBeInTheDocument()
    )
    expect(screen.getByText(/Не запущено/)).toBeInTheDocument()
    expect(screen.getByText(/Смета_из_перечня\.xlsx/)).toBeInTheDocument()
  })

  it('пока смета не запущена, форма выбора источника не предлагается заново', async () => {
    render(<CardStageContent card={notStartedCard()} />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Начать оптимизацию/ })).toBeInTheDocument()
    )
    expect(screen.queryByRole('button', { name: /Использовать смету/ })).not.toBeInTheDocument()
  })

  it('клик по кнопке запускает задачу этапа', async () => {
    render(<CardStageContent card={notStartedCard()} />)

    const button = await screen.findByRole('button', { name: /Начать оптимизацию/ })
    fireEvent.click(button)

    await waitFor(() => expect(launchTask).toHaveBeenCalledWith('card-1', 'ESTIMATE_OPTIMIZATION'))
    // Прикрепление — отдельное действие: кнопка запуска его не повторяет.
    expect(startTask).not.toHaveBeenCalled()
  })

  it('«Использовать смету» только прикрепляет — очередь не трогает', async () => {
    render(<CardStageContent card={makeCard('optimization')} />)

    const button = await screen.findByRole('button', { name: /Использовать смету/ })
    fireEvent.click(button)

    await waitFor(() => expect(startTask).toHaveBeenCalledWith('card-1', {
      task_type: 'ESTIMATE_OPTIMIZATION',
      use_previous_stage: true,
    }))
    expect(launchTask).not.toHaveBeenCalled()
  })

  it('узел этапа с незапущенной задачей — «Ожидает», а не «Идёт»', () => {
    expect(computeNodeState(notStartedCard(), 'optimization')).toBe('wait')
    // Запущенная — как была.
    const running = makeCard('optimization', {
      optimization_task_id: 't4',
      optimization_task: task('pending', 'ESTIMATE_OPTIMIZATION', 't4'),
    })
    expect(computeNodeState(running, 'optimization')).toBe('run')
  })
})
