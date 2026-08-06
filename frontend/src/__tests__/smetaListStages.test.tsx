/**
 * Стадии сметы прямо на странице проекта (планы 2026-08-04 и
 * 2026-08-06-kartochki-smet-v-proekte).
 *
 * Смета — карточка: имя, сумма, затраты и четыре стадии секциями. Дорожки-
 * таймлайна нет, состояние стадии написано в заголовке её секции.
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
import { MAIN_PADDING_X } from '../components/layoutMetrics'
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

/** Карточка сметы целиком — в ней и шапка, и стадии. */
function cardBox(): HTMLElement {
  return screen.getByRole('article')
}

describe('SmetaList — карточки смет на странице проекта', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
  })

  it('каждая смета — карточка в сетке по три в ряд', async () => {
    const { container } = await renderList()
    const grid = container.querySelector('.smeta-grid')
    expect(grid).toBeTruthy()
    expect(within(grid as HTMLElement).getAllByRole('article')).toHaveLength(1)
  })

  it('поля по бокам — 8px: сетка выходит за общие поля страницы и рисует свои', async () => {
    const { container } = await renderList()
    const root = container.firstElementChild as HTMLElement
    const gridWrap = (container.querySelector('.smeta-grid') as HTMLElement).parentElement as HTMLElement

    // Видимое поле = отступ страницы + отрицательный margin списка + его паддинг.
    const field = MAIN_PADDING_X
      + parseFloat(root.style.marginLeft)
      + parseFloat(getComputedStyle(gridWrap).paddingLeft)
    expect(field).toBe(8)
  })

  it('показывает все четыре стадии в карточке', async () => {
    await renderList()
    for (const label of ['Перечень из Гранд-сметы', 'Полнота', 'Смета', 'Оптимизация']) {
      expect(within(cardBox()).getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('показывает состояние каждой стадии: готовые — «Готово», незапущенная — «Ожидает»', async () => {
    await renderList()
    const box = cardBox()
    // Перечень и Полнота завершены.
    expect(within(box).getAllByText('Готово').length).toBeGreaterThanOrEqual(2)
    // Смета и Оптимизация ещё не запускались.
    expect(within(box).getAllByText('Ожидает').length).toBeGreaterThanOrEqual(2)
  })

  it('дорожки стадий над карточкой больше нет — состояние только в заголовках секций', async () => {
    await renderList()
    // У дорожки узел «Смета» имел подпись состояния отдельно от заголовка
    // секции. Теперь на стадию приходится ровно один заголовок.
    expect(within(cardBox()).getAllByTitle(/^Смета: /)).toHaveLength(1)
    expect(screen.queryByRole('table')).toBeNull()
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

  it('клик по заблокированной стадии никуда не ведёт', async () => {
    await renderList(makeCard({
      list_task: null,
      list_task_id: null,
      completeness_task: null,
      completeness_task_id: null,
      stage: 'list',
    }))
    fireEvent.click(screen.getByTitle('Полнота: Сначала создайте Перечень'))
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('клик по названию сметы открывает карточку сметы', async () => {
    await renderList()
    fireEvent.click(screen.getByRole('button', { name: /Липовка кровля/ }))
    expect(mockNavigate).toHaveBeenCalledWith('/projects/proj-1/cards/card-1')
  })

  it('клик по секции стадии разворачивает её и не уводит со страницы проекта', async () => {
    await renderList()
    fireEvent.click(screen.getByTitle('Перечень из Гранд-сметы: Готово'))
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('раскрыта активная стадия — у неё виден контент', async () => {
    await renderList()
    // Перечень и полнота готовы, смета не запускалась → активная «Смета».
    await waitFor(() => {
      expect(screen.getByText('Создать смету')).toBeInTheDocument()
    })
  })
})
