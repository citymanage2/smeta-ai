/**
 * Закреплённые шапки списка смет.
 *
 * При прокрутке страницы проекта сверху остаются: строка «Сметы (N) +
 * Добавить смету» и заголовок таблицы «Смета / Стадии / Сумма».
 *
 * Отдельно стережём overflow у карточки таблицы: `overflow: hidden` или
 * `overflowX: auto` делают её собственным окном прокрутки, и заголовок
 * перестаёт прилипать к верху страницы — визуально это ломается тихо.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn(),
  createWorkflowCard: vi.fn(),
  updateWorkflowCard: vi.fn(),
  deleteWorkflowCard: vi.fn(),
  startCardTask: vi.fn(),
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

import { getWorkflowCards } from '../api/workflowCards'
import { SmetaList } from '../components/SmetaList'
import { WorkflowCard, KanbanStage } from '../types/workflow'

function makeCard(): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'Липовка кровля',
    stage: 'list' as KanbanStage,
    list_task_id: null,
    completeness_task_id: null,
    estimate_task_id: null,
    optimization_task_id: null,
    list_task: null,
    completeness_task: null,
    estimate_task: null,
    optimization_task: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
  } as WorkflowCard
}

function renderList(stickyTop = 50) {
  return render(
    <MemoryRouter>
      <SmetaList projectId="proj-1" onCardCreated={() => {}} stickyTop={stickyTop} />
    </MemoryRouter>,
  )
}

describe('SmetaList — закреплённые шапки', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getWorkflowCards).mockResolvedValue([makeCard()])
  })

  it('строка «Сметы (N)» прилипает под шапками родителя', async () => {
    renderList(50)

    const title = await screen.findByRole('heading', { name: /Сметы \(1\)/ })
    const row = title.parentElement as HTMLElement

    expect(row.style.position).toBe('sticky')
    expect(row.style.top).toBe('50px')
  })

  it('заголовок таблицы прилипает ниже строки «Сметы (N)»', async () => {
    renderList(50)

    const header = await screen.findByRole('columnheader', { name: 'Смета' })
    expect(header.style.position).toBe('sticky')
    // Высота строки «Сметы (N)» в jsdom нулевая, поэтому этаж совпадает с
    // отметкой родителя. Проверяем, что заголовок вообще участвует в стопке.
    expect(header.style.top).toBe('50px')
    // Фон обязателен: без него строки таблицы просвечивают сквозь заголовок.
    expect(header.style.backgroundColor).toBeTruthy()
  })

  it('карточка таблицы не создаёт своё окно прокрутки', async () => {
    renderList()

    const header = await screen.findByRole('columnheader', { name: 'Смета' })
    const table = header.closest('table') as HTMLElement

    await waitFor(() => expect(table).toBeInTheDocument())

    for (let el = table.parentElement; el && el.tagName !== 'BODY'; el = el.parentElement) {
      const { overflow, overflowX, overflowY } = (el as HTMLElement).style
      expect([overflow, overflowX, overflowY].filter(Boolean)).toEqual([])
    }
  })
})
