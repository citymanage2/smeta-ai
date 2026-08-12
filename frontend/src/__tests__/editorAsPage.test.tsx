/**
 * Редактор открывается страницей, а не окном поверх экрана.
 *
 * План `plans/2026-08-13-redaktor-stranicej.md`. Раньше «Открыть онлайн»
 * рисовало модалку внутри карточки: у документа не было адреса, ссылку коллеге
 * отправить было нельзя, а «Назад» уводило с экрана целиком.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Метаданные — внутри фабрики: `vi.mock` поднимается выше объявлений модуля.
vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn().mockResolvedValue([]),
  getCardFilesMeta: vi.fn().mockResolvedValue({
    id: 'card-1',
    project_id: 'proj-1',
    name: 'АР',
    stage: 'list',
    source_stage: {
      task_id: 't1',
      task_type: 'LIST_FROM_GRAND',
      task_status: 'completed',
      task_name: null,
      task_created_at: '2026-08-01T10:00:00Z',
      manually_edited_at: null,
      input_files: [{ index: 0, name: 'Гранд.xlsx', size_bytes: 1024, mime_type: 'xlsx' }],
      result_files: [{
        result_id: 1, slot: 'result', file_name: 'Перечень.xlsx',
        size_bytes: 2048, mime_type: 'xlsx', created_at: '2026-08-01T11:00:00Z',
      }],
    },
    completeness_stage: null,
    estimate_stage: null,
    optimization_stage: null,
  }),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

import { CardStageContent } from '../components/kanban/CardStageContent'
import { TaskBrief, WorkflowCard } from '../types/workflow'

function task(taskType: string): TaskBrief {
  return {
    id: `task-${taskType}`,
    task_type: taskType,
    status: 'completed',
    name: null,
    created_at: '2026-08-01T10:00:00Z',
    input_files: [],
    progress_message: null,
  } as TaskBrief
}

function makeCard(): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'АР',
    stage: 'list',
    list_task_id: 't1',
    completeness_task_id: null,
    estimate_task_id: null,
    optimization_task_id: null,
    list_task: task('LIST_FROM_GRAND'),
    completeness_task: null,
    estimate_task: null,
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
  } as WorkflowCard
}

function renderStage() {
  return render(
    <MemoryRouter>
      <CardStageContent card={makeCard()} />
    </MemoryRouter>,
  )
}

describe('«Открыть онлайн» ведёт на страницу документа', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
  })

  it('результат стадии — адрес карточки и типа документа', async () => {
    renderStage()
    const button = await screen.findByTitle('Открыть в онлайн-редакторе')
    fireEvent.click(button)

    expect(mockNavigate).toHaveBeenCalledWith(
      '/projects/proj-1/cards/card-1/document/list?slot=result',
    )
  })

  it('исходный файл заказчика — слот и номер файла в адресе', async () => {
    renderStage()
    const button = await screen.findByTitle('Просмотр (без редактирования)')
    fireEvent.click(button)

    expect(mockNavigate).toHaveBeenCalledWith(
      '/projects/proj-1/cards/card-1/document/list?slot=input&index=0',
    )
  })

  it('окна поверх экрана не появляется', async () => {
    const { container } = renderStage()
    fireEvent.click(await screen.findByTitle('Открыть в онлайн-редакторе'))

    await waitFor(() => expect(mockNavigate).toHaveBeenCalled())
    expect(container.querySelector('.de-overlay')).toBeNull()
    expect(document.querySelector('[aria-modal="true"]')).toBeNull()
  })
})
