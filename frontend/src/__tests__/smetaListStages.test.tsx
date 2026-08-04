/**
 * Стадии сметы прямо на странице проекта (план 2026-08-04).
 *
 * В строке сметы вместо колонок «Этап»/«Состояние» — дорожка из четырёх стадий
 * и под ней свёрнутые секции стадий с файлами. Узлы дорожки не кликабельны:
 * навигация — только по названию сметы.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn(),
  createWorkflowCard: vi.fn(),
  updateWorkflowCard: vi.fn(),
  deleteWorkflowCard: vi.fn(),
  startCardTask: vi.fn(),
  // Мета файлов не нужна: секции стадий переживают её отсутствие (fallback-вид).
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

import { getWorkflowCards } from '../api/workflowCards'
import { SmetaList } from '../components/SmetaList'
import { WorkflowCard, TaskBrief, TaskStatus, KanbanStage } from '../types/workflow'

function task(status: TaskStatus, taskType = 'LIST_FROM_GRAND'): TaskBrief {
  return {
    id: `task-${taskType}-${status}`,
    task_type: taskType,
    status,
    name: null,
    created_at: '2026-08-01T10:00:00Z',
    input_files: [],
    progress_message: null,
  }
}

/** Смета «Липовка кровля» со скриншота: перечень и полнота готовы, смета впереди. */
function makeCard(over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'Липовка кровля',
    stage: 'completeness' as KanbanStage,
    list_task_id: 't1',
    completeness_task_id: 't2',
    estimate_task_id: null,
    optimization_task_id: null,
    list_task: task('completed', 'LIST_FROM_GRAND'),
    completeness_task: task('completed', 'CHECK_LIST_COMPLETENESS'),
    estimate_task: null,
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
    ...over,
  }
}

async function renderList(card: WorkflowCard = makeCard()) {
  vi.mocked(getWorkflowCards).mockResolvedValue([card])
  const utils = render(
    <MemoryRouter>
      <SmetaList projectId="proj-1" onCardCreated={vi.fn()} />
    </MemoryRouter>
  )
  await screen.findByText('Липовка кровля')
  return utils
}

describe('SmetaList — стадии сметы на странице проекта', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
  })

  it('показывает все четыре стадии в строке сметы', async () => {
    await renderList()
    const table = screen.getByRole('table')
    for (const label of ['Перечень', 'Полнота', 'Смета', 'Оптимизация']) {
      expect(within(table).getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('показывает состояние каждой стадии: готовые — «Готово», незапущенная — «Ожидает»', async () => {
    await renderList()
    const table = screen.getByRole('table')
    // Перечень и Полнота завершены.
    expect(within(table).getAllByText('Готово').length).toBeGreaterThanOrEqual(2)
    // Смета и Оптимизация ещё не запускались.
    expect(within(table).getAllByText('Ожидает').length).toBeGreaterThanOrEqual(2)
  })

  it('колонок «Этап» и «Состояние» больше нет — вместо них «Стадии»', async () => {
    await renderList()
    expect(screen.getByRole('columnheader', { name: 'Стадии' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Этап' })).toBeNull()
    expect(screen.queryByRole('columnheader', { name: 'Состояние' })).toBeNull()
  })

  it('заблокированная стадия показана замком, а причина — подсказкой', async () => {
    // Перечня нет → «Полнота» заблокирована жёстким гейтом.
    await renderList(makeCard({
      list_task: null,
      list_task_id: null,
      completeness_task: null,
      completeness_task_id: null,
      stage: 'list',
    }))
    expect(await screen.findByTitle('Полнота: Сначала создайте Перечень')).toBeInTheDocument()
  })

  it('узлы дорожки не кликабельны — клик по стадии никуда не ведёт', async () => {
    await renderList()
    const node = screen.getByTitle('Оптимизация: Ожидает')
    fireEvent.click(node)
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('клик по названию сметы открывает карточку сметы', async () => {
    await renderList()
    fireEvent.click(screen.getByTitle('Открыть смету'))
    expect(mockNavigate).toHaveBeenCalledWith('/projects/proj-1/cards/card-1')
  })

  it('клик по секции стадии разворачивает её и не уводит со страницы проекта', async () => {
    await renderList()
    const section = await screen.findByText('Перечень из Гранд-сметы')
    fireEvent.click(section)
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('под дорожкой — секции стадий с файлами, как внутри сметы', async () => {
    await renderList()
    // Стадия по умолчанию — «Смета» (перечень и полнота готовы, смета не запускалась):
    // её контент показывает предыдущий этап свёрнутой секцией и форму запуска.
    await waitFor(() => {
      expect(screen.getByText('Перечень из Гранд-сметы')).toBeInTheDocument()
      expect(screen.getByText('Смета из перечня')).toBeInTheDocument()
      expect(screen.getByText('Создать смету')).toBeInTheDocument()
    })
  })
})
