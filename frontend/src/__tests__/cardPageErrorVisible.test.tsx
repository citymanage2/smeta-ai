/**
 * Ошибка стадии должна быть читаема там, где на неё смотрят.
 *
 * Два места: список смет проекта (там она видна как «● Ошибка») и страница
 * сметы, куда ведёт стрелка рядом с этим бейджем. Проверяем, что переход
 * действительно открывает страницу (а не белый экран) и что причина ошибки
 * названа словами уже в списке.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ projectId: 'proj-1', cardId: 'card-1' }),
  }
})

vi.mock('../components/Layout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('../api/workflowCards', () => ({
  getWorkflowCards: vi.fn(),
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
  createWorkflowCard: vi.fn(),
  updateWorkflowCard: vi.fn(),
  deleteWorkflowCard: vi.fn(),
  startTask: vi.fn(),
}))

vi.mock('../api/tasks', () => ({
  getTaskStatus: vi.fn(),
  restartTask: vi.fn(),
  resumeTask: vi.fn(),
}))

vi.mock('../api/projects', () => ({
  downloadSlotFile: vi.fn(),
}))

import * as cardsApi from '../api/workflowCards'
import * as tasksApi from '../api/tasks'
import ProjectCardPage from '../pages/ProjectCardPage'
import { CardStagesAccordion } from '../components/kanban/CardStageContent'
import { useKanbanStore } from '../stores/kanban'
import { TaskBrief, TaskStatus, WorkflowCard } from '../types/workflow'

function task(status: TaskStatus, taskType: string, over: Partial<TaskBrief> = {}): TaskBrief {
  return {
    id: `task-${taskType}`,
    task_type: taskType,
    status,
    name: null,
    created_at: '2026-08-01T10:00:00Z',
    input_files: [],
    progress_message: null,
    ...over,
  }
}

/** Перечень и полнота готовы, смета упала. */
function makeCard(over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'АР — корпус 2',
    stage: 'estimate',
    list_task_id: 't1',
    completeness_task_id: 't2',
    estimate_task_id: 't3',
    optimization_task_id: null,
    list_task: task('completed', 'LIST_FROM_GRAND'),
    completeness_task: task('completed', 'CHECK_LIST_COMPLETENESS'),
    estimate_task: task('failed', 'ESTIMATE_FROM_LIST', {
      error_message: 'Не удалось разобрать ответ ИИ по чанку 3',
    }),
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
    ...over,
  } as WorkflowCard
}

beforeEach(() => {
  vi.clearAllMocks()
  useKanbanStore.setState({ cards: [], currentProjectId: null })
  vi.mocked(cardsApi.getCardFilesMeta).mockRejectedValue(new Error('no meta in test'))
  vi.mocked(tasksApi.getTaskStatus).mockResolvedValue({
    id: 'task-ESTIMATE_FROM_LIST',
    status: 'failed',
    task_type: 'ESTIMATE_FROM_LIST',
    estimation_status: 'not_applicable',
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
    progress_log: ['Готовлю чанки', 'Считаю чанк 3'],
    error_message: 'Не удалось разобрать ответ ИИ по чанку 3',
  } as Awaited<ReturnType<typeof tasksApi.getTaskStatus>>)
})

describe('страница сметы открывается по стрелке из списка', () => {
  it('карточка, пришедшая после первой отрисовки, показывает содержимое, а не пустой экран', async () => {
    vi.mocked(cardsApi.getWorkflowCards).mockResolvedValue([makeCard()])

    render(
      <MemoryRouter initialEntries={['/projects/proj-1/cards/card-1?stage=estimate']}>
        <ProjectCardPage />
      </MemoryRouter>,
    )

    // Первый рендер — карточек в сторе ещё нет (переход со страницы другого
    // проекта или обновление вкладки). Как только они пришли, страница обязана
    // отрисоваться целиком.
    await waitFor(() => {
      expect(screen.getByText('АР — корпус 2')).toBeInTheDocument()
    })
    expect(await screen.findByText('Ошибка обработки')).toBeInTheDocument()
    // Причина названа и в блоке стадии, и в ходе обработки — оба места ведут
    // себя одинаково, поэтому вхождений больше одного.
    expect(screen.getAllByText(/чанку 3/).length).toBeGreaterThan(0)
  })
})

describe('причина ошибки видна в списке смет', () => {
  it('рядом с «Ошибка» написано, что именно случилось', async () => {
    render(
      <MemoryRouter>
        <CardStagesAccordion card={makeCard()} />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/чанку 3/)).toBeInTheDocument()
  })
})
