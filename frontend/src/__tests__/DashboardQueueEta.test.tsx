/**
 * Колонка «Готовность» в активной очереди.
 *
 * До неё в таблице было видно только «сколько задача уже висит» — по этому
 * числу нельзя решить, ждать или отменять.
 *
 * План: plans/2026-07-30-eta-ocheredi-zadach.md, Фаза 5.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/tasks', () => ({ cancelTask: vi.fn() }))

import DashboardQueue from '../components/dashboard/DashboardQueue'
import { ActiveTask } from '../api/dashboard'

function makeTask(overrides: Partial<ActiveTask> = {}): ActiveTask {
  return {
    id: 'task-1',
    task_type: 'ESTIMATE_FROM_LIST',
    status: 'processing',
    progress_message: 'Прайс: 0 позиций найдено',
    created_at: new Date(Date.now() - 3600_000).toISOString(),
    project_id: null,
    project_name: 'РЖД корректировка',
    eta: {
      starts_in_s: 0,
      ready_in_s: 2400,
      ready_at: new Date(Date.now() + 2400_000).toISOString(),
      rough: false,
      finishing: false,
      units: 1220,
      unit_kind: 'items',
    },
    ...overrides,
  }
}

function renderQueue(tasks: ActiveTask[]) {
  return render(
    <MemoryRouter>
      <DashboardQueue tasks={tasks} onCancel={() => {}} />
    </MemoryRouter>
  )
}

describe('DashboardQueue — готовность', () => {
  it('считающаяся задача показывает время результата', () => {
    renderQueue([makeTask()])
    expect(screen.getByTestId('queue-eta')).toHaveTextContent(/через 40 мин/)
  })

  it('ожидающая задача показывает и время старта', () => {
    renderQueue([
      makeTask({
        status: 'pending',
        eta: {
          starts_in_s: 1500,
          ready_in_s: 4200,
          ready_at: new Date(Date.now() + 4200_000).toISOString(),
          rough: false,
          finishing: false,
          units: 300,
          unit_kind: 'rows',
        },
      }),
    ])
    const cell = screen.getByTestId('queue-eta')
    expect(cell).toHaveTextContent('старт ≈ через 25 мин')
    expect(cell).toHaveTextContent(/через 1 ч 10 мин/)
  })

  it('грубая оценка помечена прямо в таблице', () => {
    renderQueue([makeTask({ eta: { ...makeTask().eta!, rough: true } })])
    expect(screen.getByTestId('queue-eta')).toHaveTextContent('оценка грубая')
  })

  it('без прогноза — прочерк, а не пустая ячейка', () => {
    renderQueue([makeTask({ eta: null })])
    expect(screen.queryByTestId('queue-eta')).not.toBeInTheDocument()
  })
})
