/**
 * Стадии сметы прямо на странице проекта (планы 2026-08-04 и
 * 2026-08-06-kartochki-smet-v-proekte).
 *
 * Смета — карточка: имя, сумма, затраты и четыре стадии секциями. Дорожки-
 * таймлайна нет, состояние стадии написано в заголовке её секции.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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

describe('SmetaList — карточки смет на странице проекта', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
  })

  it('клик по названию сметы открывает карточку сметы', async () => {
    await renderList()
    fireEvent.click(screen.getByRole('button', { name: /Липовка кровля/ }))
    expect(mockNavigate).toHaveBeenCalledWith('/projects/proj-1/cards/card-1')
  })
})
