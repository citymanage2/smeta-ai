/**
 * Затраты видны у каждой стадии, а не только в итоге по смете.
 *
 * План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 5 (AC-1..AC-4).
 *
 * Смысл цифры — показать, где именно утекают деньги. Поэтому проверяется
 * не «числа посчитались», а «числа стоят рядом с той стадией, к которой
 * относятся», и отдельно — что допзапросы не смешаны с основной обработкой.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

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
  restartTask: vi.fn(),
  resumeTask: vi.fn(),
}))

vi.mock('../api/projects', () => ({ downloadSlotFile: vi.fn() }))

const storeState = {
  startTask: vi.fn(),
  fetchCards: vi.fn().mockResolvedValue(undefined),
  submittingCardIds: new Set<string>(),
  pendingListTasks: {},
  clearPendingListTask: vi.fn(),
}

vi.mock('../stores/kanban', () => ({
  useKanbanStore: (selector?: (s: typeof storeState) => unknown) =>
    (selector ? selector(storeState) : storeState),
}))

import { CardStageContent } from '../components/kanban/CardStageContent'
import UsageChips from '../components/card/UsageChips'
import { stageUsage } from '../utils/usageMetrics'
import { KanbanStage, TaskBrief, TaskUsage, WorkflowCard } from '../types/workflow'

function usage(over: Partial<TaskUsage> = {}): TaskUsage {
  return {
    tokens: 0,
    cost_usd: 0,
    extra_tokens: 0,
    extra_cost_usd: 0,
    queue_seconds: null,
    work_seconds: null,
    queue_running: false,
    work_running: false,
    ...over,
  }
}

function task(over: Partial<TaskBrief> = {}): TaskBrief {
  return {
    id: 't1',
    task_type: 'ESTIMATE_FROM_LIST',
    status: 'completed',
    name: null,
    created_at: '2026-08-06T10:00:00Z',
    input_files: [],
    progress_message: null,
    ...over,
  }
}

function card(stage: KanbanStage, over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'c1',
    project_id: 'p1',
    name: 'АР',
    stage,
    list_task_id: null,
    completeness_task_id: null,
    estimate_task_id: null,
    optimization_task_id: null,
    list_task: null,
    completeness_task: null,
    estimate_task: null,
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-08-06T10:00:00Z',
    updated_at: '2026-08-06T10:00:00Z',
    ...over,
  }
}

describe('чипы стадии в карточке', () => {
  it('AC-1: текущая стадия показывает свои токены, деньги и время', () => {
    render(
      <CardStageContent
        card={card('estimate', {
          estimate_task: task({
            id: 'e',
            usage: usage({
              tokens: 1_200_000, cost_usd: 9.84, queue_seconds: 180, work_seconds: 840,
            }),
          }),
        })}
      />,
    )
    expect(screen.getByText('1.2M')).toBeTruthy()
    expect(screen.getByText('$9.84')).toBeTruthy()
    expect(screen.getByText('3 мин')).toBeTruthy()
    expect(screen.getByText('14 мин')).toBeTruthy()
  })

  it('AC-2: стадия без вызовов ИИ не рисует ни чипов, ни нулей', () => {
    render(<CardStageContent card={card('estimate', { estimate_task: task({ id: 'e' }) })} />)
    expect(screen.queryByTestId('usage-chips')).toBeNull()
  })
})

describe('UsageChips', () => {
  it('AC-4: допзапросы стоят отдельной парой, а не в основных токенах', () => {
    render(
      <UsageChips
        usage={stageUsage(usage({
          tokens: 1000, cost_usd: 2, extra_tokens: 300, extra_cost_usd: 0.75,
        }))}
      />,
    )
    // Общая цифра включает допы, но допы при этом названы отдельно.
    expect(screen.getByText('1.3K')).toBeTruthy()
    expect(screen.getByText('$2.75')).toBeTruthy()
    expect(screen.getByText('допы')).toBeTruthy()
    expect(screen.getByText('300 / $0.75')).toBeTruthy()
  })

  it('нулевые допы не занимают место в строке', () => {
    render(<UsageChips usage={stageUsage(usage({ tokens: 1000, cost_usd: 2 }))} />)
    expect(screen.queryByText('допы')).toBeNull()
  })

  it('AC-3: идущая задача подписана «идёт», а не выглядит завершённой', () => {
    render(
      <UsageChips
        usage={stageUsage(usage({ tokens: 100, cost_usd: 0.1, work_seconds: 120, work_running: true }))}
      />,
    )
    expect(screen.getByText('работа, идёт')).toBeTruthy()
  })

  it('итог проекта складывает ожидание и работу во время реализации', () => {
    render(
      <UsageChips
        usage={stageUsage(usage({ tokens: 100, cost_usd: 0.1, queue_seconds: 180, work_seconds: 420 }))}
        variant="total"
        mergeTime
      />,
    )
    expect(screen.getByText('Сумма затрат:')).toBeTruthy()
    expect(screen.getByText('время')).toBeTruthy()
    expect(screen.getByText('10 мин')).toBeTruthy()
  })
})
