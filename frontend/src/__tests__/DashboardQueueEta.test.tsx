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
import { describeEta } from '../utils/eta'

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

/**
 * Тексты прогноза («старт ≈ через 25 мин», «2-я в очереди») проверяет
 * `eta.test.ts`. Здесь — связка: ячейка очереди показывает прогноз именно этой
 * задачи и с её статусом. Ожидающая задача берётся потому, что у неё видно всё
 * сразу — и место в очереди, и старт, и готовность; у считающейся (`processing`)
 * первых двух нет, и перепутанный статус здесь бы заметился.
 *
 * Место в очереди: план plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 8.
 */
describe('DashboardQueue — готовность', () => {
  it('ожидающая задача показывает место в очереди, старт и готовность', () => {
    const eta = {
      starts_in_s: 1500,
      ready_in_s: 4200,
      ready_at: new Date(Date.now() + 4200_000).toISOString(),
      rough: false,
      finishing: false,
      units: 300,
      unit_kind: 'rows',
      queue_position: 2,
    }
    renderQueue([makeTask({ status: 'pending', eta })])

    const view = describeEta(eta, 'pending')!
    const cell = screen.getByTestId('queue-eta')
    expect(view.position && view.start && view.ready).toBeTruthy()
    expect(screen.getByTestId('queue-position')).toHaveTextContent(view.position)
    expect(cell).toHaveTextContent(view.start)
    expect(cell).toHaveTextContent(view.ready)
  })
})
