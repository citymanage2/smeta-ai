/**
 * Список смет: колонка «Сумма» и строка «Сумма затрат».
 *
 * План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фазы 5 и 6.
 *
 * До этой правки колонка «Сумма» всегда показывала прочерк, хотя сумма
 * сформированной сметы в системе есть. Рядом с ней теперь стоят затраты на ИИ,
 * и перепутать их нельзя: одно — деньги заказчика, другое — наша себестоимость.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { TaskBrief, TaskUsage, WorkflowCard } from '../types/workflow'

// Карточка рисует раскрывающиеся секции, которые лезут в сеть за метаданными
// файлов. Списку смет это не нужно — здесь проверяются числа в строке.
vi.mock('../components/kanban/CardStageContent', () => ({
  CardStageContent: () => null,
}))

vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn().mockResolvedValue([]),
  getCardFilesMeta: vi.fn().mockResolvedValue(null),
}))

import { SmetaList } from '../components/SmetaList'
import { useKanbanStore } from '../stores/kanban'

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

function card(over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'c1',
    project_id: 'p1',
    name: 'АР',
    stage: 'estimate',
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

function renderWith(cards: WorkflowCard[]) {
  useKanbanStore.setState({ cards, loading: false })
  return render(
    <MemoryRouter>
      <SmetaList projectId="p1" onCardCreated={() => {}} />
    </MemoryRouter>,
  )
}

describe('колонка «Сумма»', () => {
  it('AC-7: показывает сумму сформированной сметы', () => {
    renderWith([card({ estimate_task: task({ cost: 1234567.89 }) })])
    expect(screen.getByText('1 234 568 ₽')).toBeTruthy()
  })

  it('AC-7: сумма оптимизации важнее суммы сметы', () => {
    renderWith([
      card({
        estimate_task: task({ id: 'e', cost: 1000000 }),
        optimization_task: task({ id: 'o', cost: 850000 }),
      }),
    ])
    expect(screen.getByText('850 000 ₽')).toBeTruthy()
    expect(screen.queryByText('1 000 000 ₽')).toBeNull()
  })

  it('сметы ещё нет — прочерк, а не ноль', () => {
    renderWith([card()])
    expect(screen.getByText('—')).toBeTruthy()
    expect(screen.queryByText('0 ₽')).toBeNull()
  })
})

describe('строка «Сумма затрат»', () => {
  it('показывает токены, доллары и время по всей смете', () => {
    renderWith([
      card({
        estimate_task: task({
          cost: 1000,
          usage: usage({
            tokens: 1_200_000, cost_usd: 9.84, queue_seconds: 180, work_seconds: 840,
          }),
        }),
      }),
    ])
    expect(screen.getByText('Сумма затрат:')).toBeTruthy()
    expect(screen.getByText('1.2M')).toBeTruthy()
    expect(screen.getByText('$9.84')).toBeTruthy()
    expect(screen.getByText('3 мин')).toBeTruthy()
    expect(screen.getByText('14 мин')).toBeTruthy()
  })

  it('AC-2: смета без затрат не показывает пустую строку чипов', () => {
    renderWith([card({ estimate_task: task({ cost: 1000 }) })])
    expect(screen.queryByTestId('usage-chips')).toBeNull()
  })
})
