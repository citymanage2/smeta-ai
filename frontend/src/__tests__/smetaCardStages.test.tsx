/**
 * Аккордеон стадий в карточке сметы (план 2026-08-06-kartochki-smet-v-proekte).
 *
 * Дорожки-таймлайна больше нет: состояние стадии видно в заголовке её секции —
 * кружком слева и подписью рядом. Раскрыта одна стадия, активная.
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
  getWorkflowCards: vi.fn().mockResolvedValue([]),
  // Мета файлов не нужна: секции переживают её отсутствие (упрощённый вид).
  getCardFilesMeta: vi.fn().mockRejectedValue(new Error('no meta in test')),
  downloadInputFileById: vi.fn(),
  downloadSlotFileById: vi.fn(),
}))

import { CardStagesAccordion } from '../components/kanban/CardStageContent'
import { TaskBrief, TaskStatus, WorkflowCard } from '../types/workflow'

function task(status: TaskStatus, taskType: string): TaskBrief {
  return {
    id: `task-${taskType}`,
    task_type: taskType,
    status,
    name: null,
    created_at: '2026-08-01T10:00:00Z',
    input_files: [],
    progress_message: null,
  }
}

/** Перечень и полнота готовы, смета не запускалась — активная стадия «Смета». */
function makeCard(over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'card-1',
    project_id: 'proj-1',
    name: 'АР',
    stage: 'estimate',
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
  } as WorkflowCard
}

function renderAccordion(card: WorkflowCard = makeCard()) {
  return render(
    <MemoryRouter>
      <CardStagesAccordion card={card} />
    </MemoryRouter>,
  )
}

describe('CardStagesAccordion — стадии секциями', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
  })

  it('AC-4: показывает все четыре стадии, независимо от текущей', () => {
    renderAccordion()
    expect(screen.getByText('Перечень из Гранд-сметы')).toBeInTheDocument()
    expect(screen.getByText('Полнота')).toBeInTheDocument()
    expect(screen.getByText('Смета')).toBeInTheDocument()
    expect(screen.getByText('Оптимизация')).toBeInTheDocument()
  })

  it('AC-5: у завершённой стадии в заголовке — кружок с галочкой', () => {
    renderAccordion()
    const header = screen.getByTitle('Полнота: Готово')
    expect(header.querySelector('svg.lucide-check')).toBeTruthy()
  })

  it('AC-5: незапущенная стадия показана номером, а не галочкой', () => {
    renderAccordion()
    const header = screen.getByTitle('Оптимизация: Ожидает')
    expect(header.querySelector('svg.lucide-check')).toBeNull()
    expect(header.textContent).toContain('4')
  })

  it('AC-6: состояние стадии подписано в её заголовке', () => {
    renderAccordion()
    expect(screen.getAllByText('Готово').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('Ожидает').length).toBeGreaterThanOrEqual(2)
  })

  it('AC-7: раскрыта только активная стадия', () => {
    renderAccordion()
    // Активная — «Смета»: её форма запуска видна.
    expect(screen.getByText('Создать смету')).toBeInTheDocument()
    // Оптимизация свёрнута: её формы запуска нет.
    expect(screen.queryByText('Использовать смету')).toBeNull()
  })

  it('AC-7: клик по заголовку раскрывает стадию, не уводя со страницы', () => {
    renderAccordion()
    fireEvent.click(screen.getByTitle('Оптимизация: Ожидает'))
    expect(screen.getByText('Использовать смету')).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('AC-8: заблокированная стадия не раскрывается, причина — в подсказке', () => {
    renderAccordion(makeCard({
      list_task: null,
      list_task_id: null,
      completeness_task: null,
      completeness_task_id: null,
      stage: 'list',
    }))
    const header = screen.getByTitle('Полнота: Сначала создайте Перечень')
    fireEvent.click(header)
    expect(screen.queryByText('Запустить проверку полноты')).toBeNull()
  })
})
