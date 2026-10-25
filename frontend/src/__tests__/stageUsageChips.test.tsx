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
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

// Стор канбана — настоящий, мокается только сеть.
vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn().mockResolvedValue([]),
  createWorkflowCard: vi.fn(),
  updateWorkflowCard: vi.fn(),
  deleteWorkflowCard: vi.fn(),
  startTask: vi.fn(),
  launchTask: vi.fn(),
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

vi.mock('../api/tasks', () => ({
  restartTask: vi.fn(),
  resumeTask: vi.fn(),
}))

vi.mock('../api/projects', () => ({ downloadSlotFile: vi.fn() }))

import { CardStageContent, CardStagesAccordion } from '../components/kanban/CardStageContent'
import UsageChips from '../components/card/UsageChips'
import { stageUsage } from '../utils/usageMetrics'
import { KanbanStage, TaskBrief, TaskUsage, WorkflowCard } from '../types/workflow'
import { numbersIn } from './screenQueries'

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
  it('AC-1: у каждой стадии — её токены, деньги и время, а не соседней', () => {
    render(
      <MemoryRouter>
        <CardStagesAccordion
          card={card('estimate', {
            list_task_id: 'l',
            list_task: task({
              id: 'l', task_type: 'LIST_FROM_GRAND',
              usage: usage({ tokens: 1_200_000, cost_usd: 9.84, queue_seconds: 180, work_seconds: 840 }),
            }),
            estimate_task_id: 'e',
            estimate_task: task({
              id: 'e',
              usage: usage({ tokens: 500, cost_usd: 0.4, queue_seconds: 60, work_seconds: 300 }),
            }),
          })}
        />
      </MemoryRouter>,
    )
    // Секция стадии — её заголовок и всё, что под ним.
    const chipsOf = (stage: RegExp) => {
      const section = screen.getByRole('button', { name: stage }).parentElement as HTMLElement
      return numbersIn(within(section).getByTestId('usage-chips').textContent)
    }
    const list = chipsOf(/^Перечень/)
    const estimate = chipsOf(/^Смета/)
    // Перечень: $9.84, ожидание 3 мин, работа 14 мин; смета: 500 токенов, $0.4, 5 мин.
    expect(list).toEqual(expect.arrayContaining([9.84, 3, 14]))
    expect(list).not.toContain(0.4)
    expect(estimate).toEqual(expect.arrayContaining([500, 0.4, 5]))
    expect(estimate).not.toContain(9.84)
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
