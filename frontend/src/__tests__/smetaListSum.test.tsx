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
import { TaskBrief, WorkflowCard } from '../types/workflow'

// Карточка рисует раскрывающиеся секции, которые лезут в сеть за метаданными
// файлов. Списку смет это не нужно — здесь проверяются числа в шапке карточки.
vi.mock('../components/kanban/CardStageContent', () => ({
  CardStageContent: () => null,
  CardStagesAccordion: () => null,
}))

vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn().mockResolvedValue([]),
  getCardFilesMeta: vi.fn().mockResolvedValue(null),
}))

import { SmetaList } from '../components/SmetaList'
import { useKanbanStore } from '../stores/kanban'

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
  it('AC-2: смета без затрат не показывает пустую строку чипов', () => {
    renderWith([card({ estimate_task: task({ cost: 1000 }) })])
    expect(screen.queryByTestId('usage-chips')).toBeNull()
  })
})
