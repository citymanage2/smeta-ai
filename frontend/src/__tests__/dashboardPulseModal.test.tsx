/**
 * Карточки «Пульса сегодня» кликабельны, под каждой — таблица задач.
 *
 * План: `plans/2026-08-31-klikabelnye-kartochki-pulsa.md`, Фаза 2.
 *
 * До этого карточки были четырьмя мёртвыми цифрами: «4 с ошибкой» — а какие
 * задачи и во что они обошлись, приходилось искать глазами в других блоках.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

const getPulseBucket = vi.fn()
const navigate = vi.fn()

vi.mock('../api/dashboard', () => ({
  getPulseBucket: (...args: unknown[]) => getPulseBucket(...args),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

import DashboardPulse from '../components/dashboard/DashboardPulse'
import type { PulseStats } from '../api/dashboard'

const PULSE: PulseStats = {
  created_today: 4,
  processing_now: 1,
  pending_now: 2,
  completed_today: 3,
  failed_today: 4,
}

function row(over: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    task_type: 'ESTIMATE_FROM_LIST',
    status: 'failed',
    name: null,
    project_id: 'p1',
    project_name: 'ЖК Северный',
    created_at: '2026-08-31T09:00:00Z',
    work_seconds: 840,
    work_running: false,
    tokens: 1500,
    cost_usd: 1.75,
    ...over,
  }
}

function detail(over: Record<string, unknown> = {}) {
  return {
    bucket: 'failed',
    count: 1,
    total_tokens: 1500,
    total_cost_usd: 1.75,
    total_work_seconds: 840,
    tasks: [row()],
    ...over,
  }
}

function renderPulse() {
  return render(
    <MemoryRouter>
      <DashboardPulse pulse={PULSE} />
    </MemoryRouter>
  )
}

beforeEach(() => {
  getPulseBucket.mockReset()
  navigate.mockReset()
  getPulseBucket.mockResolvedValue(detail())
})

describe('Пульс сегодня', () => {
  it('показывает пять карточек, включая отдельную «В ожидании»', () => {
    renderPulse()
    for (const label of [
      'Создано сегодня',
      'В обработке',
      'В ожидании',
      'Завершено сегодня',
      'С ошибкой сегодня',
    ]) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeTruthy()
    }
  })

  it('по клику грузит задачи именно этой карточки', async () => {
    renderPulse()
    await userEvent.click(screen.getByRole('button', { name: /С ошибкой сегодня/ }))
    await waitFor(() => expect(getPulseBucket).toHaveBeenCalledWith('failed'))

    await userEvent.click(screen.getByLabelText('Закрыть'))
    await userEvent.click(screen.getByRole('button', { name: /В ожидании/ }))
    await waitFor(() => expect(getPulseBucket).toHaveBeenLastCalledWith('pending'))
  })

  it('строка показывает проект, задачу, время, токены и стоимость', async () => {
    renderPulse()
    await userEvent.click(screen.getByRole('button', { name: /С ошибкой сегодня/ }))

    const cells = await screen.findByText('ЖК Северный')
    const tr = cells.closest('tr') as HTMLElement
    expect(within(tr).getByText('Смета из перечня')).toBeTruthy()
    expect(within(tr).getByText('14 мин')).toBeTruthy()
    expect(within(tr).getByText('1.5K')).toBeTruthy()
    expect(within(tr).getByText('$1.75')).toBeTruthy()
  })

  it('над таблицей — суммарные итоги', async () => {
    getPulseBucket.mockResolvedValue(
      detail({
        count: 2,
        total_tokens: 2500,
        total_cost_usd: 3.25,
        total_work_seconds: 1800,
        tasks: [row(), row({ id: 'task-2', tokens: 1000, cost_usd: 1.5, work_seconds: 960 })],
      })
    )
    renderPulse()
    await userEvent.click(screen.getByRole('button', { name: /С ошибкой сегодня/ }))

    expect(await screen.findByText('30 мин')).toBeTruthy()
    expect(screen.getByText('2.5K')).toBeTruthy()
    expect(screen.getByText('$3.25')).toBeTruthy()
  })

  it('клик по строке ведёт к задаче', async () => {
    renderPulse()
    await userEvent.click(screen.getByRole('button', { name: /С ошибкой сегодня/ }))
    await userEvent.click(await screen.findByText('ЖК Северный'))
    expect(navigate).toHaveBeenCalledWith('/tasks/task-1/status')
  })

  it('время не выдумывается: не стартовавшая задача показывает прочерк', async () => {
    getPulseBucket.mockResolvedValue(
      detail({ tasks: [row({ work_seconds: null, tokens: 0, cost_usd: 0 })] })
    )
    renderPulse()
    await userEvent.click(screen.getByRole('button', { name: /В ожидании/ }))

    const tr = (await screen.findByText('ЖК Северный')).closest('tr') as HTMLElement
    expect(within(tr).getAllByText('—').length).toBe(3)
  })

  it('пустая карточка не выглядит поломкой', async () => {
    getPulseBucket.mockResolvedValue(
      detail({ count: 0, total_tokens: 0, total_cost_usd: 0, total_work_seconds: 0, tasks: [] })
    )
    renderPulse()
    await userEvent.click(screen.getByRole('button', { name: /Создано сегодня/ }))
    expect(await screen.findByText('Задач нет')).toBeTruthy()
  })
})
