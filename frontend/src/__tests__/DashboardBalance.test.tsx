/**
 * Блок остатка денег на Claude API.
 *
 * Проверяется то, ради чего блок и сделан: человек должен понять не сумму, а
 * когда встанет работа. И два состояния, в которых легко соврать: отметки нет
 * (остаток неизвестен — это не ноль) и потрачено больше отметки (минус
 * показываем, а не прячем: это единственный признак «пополнили и не отметили»).
 *
 * План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 7.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const fetchApiBalance = vi.fn()
const createBalanceMark = vi.fn()
const deleteBalanceMark = vi.fn()
const syncApiBalance = vi.fn()

vi.mock('../api/apiBalance', () => ({
  fetchApiBalance: (...a: unknown[]) => fetchApiBalance(...a),
  createBalanceMark: (...a: unknown[]) => createBalanceMark(...a),
  deleteBalanceMark: (...a: unknown[]) => deleteBalanceMark(...a),
  syncApiBalance: (...a: unknown[]) => syncApiBalance(...a),
}))

import DashboardBalance from '../components/dashboard/DashboardBalance'
import type { ApiBalance } from '../api/apiBalance'

function balance(overrides: Partial<ApiBalance> = {}): ApiBalance {
  return {
    mark_usd: 500,
    mark_on: '2026-08-28',
    official_usd: 40,
    live_usd: 10,
    spent_usd: 50,
    remaining_usd: 450,
    official_through: '2026-08-31',
    synced_at: '2026-09-01T09:00:00Z',
    official_enabled: true,
    avg_daily_usd: 15,
    days_left: 30,
    avg_estimate_usd: 10,
    estimates_left: 45,
    level: 'ok',
    marks: [],
    ...overrides,
  }
}

describe('DashboardBalance', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('показывает остаток и на сколько дней его хватит', async () => {
    fetchApiBalance.mockResolvedValue(balance())
    render(<DashboardBalance />)

    expect(await screen.findByText(/\$450,00/)).toBeInTheDocument()
    expect(screen.getByText(/хватит примерно на 30 дней/)).toBeInTheDocument()
    expect(screen.getByText(/примерно 45 смет/)).toBeInTheDocument()
  })

  it('без отметки говорит «неизвестно», а не показывает ноль', async () => {
    fetchApiBalance.mockResolvedValue(
      balance({ remaining_usd: null, mark_usd: null, mark_on: null, level: 'unknown' })
    )
    render(<DashboardBalance />)

    expect(await screen.findByText('Остаток неизвестен')).toBeInTheDocument()
    expect(screen.queryByText(/\$0,00/)).not.toBeInTheDocument()
  })

  it('перерасход показывает как есть — это признак незаписанного пополнения', async () => {
    fetchApiBalance.mockResolvedValue(
      balance({ remaining_usd: -25, level: 'alarm', days_left: -1.6 })
    )
    render(<DashboardBalance />)

    expect(await screen.findByText(/-\$?25,00|−25,00|\$-25,00/)).toBeInTheDocument()
    expect(screen.getByText(/пополнили и не отметили/)).toBeInTheDocument()
  })

  it('меньше суток запаса — предупреждает словами, а не долями дня', async () => {
    fetchApiBalance.mockResolvedValue(
      balance({ remaining_usd: 8, level: 'alarm', days_left: 0.5 })
    )
    render(<DashboardBalance />)

    expect(await screen.findByText(/хватит меньше чем на сутки/)).toBeInTheDocument()
  })

  it('без ключа Anthropic сверять нечем — кнопка выключена', async () => {
    fetchApiBalance.mockResolvedValue(
      balance({ official_enabled: false, official_through: null, synced_at: null })
    )
    render(<DashboardBalance />)

    const button = await screen.findByRole('button', { name: 'Сверить траты' })
    expect(button).toBeDisabled()
    expect(screen.getByText(/Ключ Anthropic не задан/)).toBeInTheDocument()
  })

  it('без официальных данных подпись нейтральна — блок не выглядит сломанным', async () => {
    // Официальной сверки может не быть никогда: на личной организации Anthropic
    // отвечает 403. Остаток при этом полностью рабочий.
    fetchApiBalance.mockResolvedValue(
      balance({ official_enabled: true, official_through: null, synced_at: null })
    )
    render(<DashboardBalance />)

    expect(await screen.findByText(/Официальная сверка с Anthropic: данных нет/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сверить траты' })).toBeEnabled()
  })

  it('неудачная сверка показывает ответ Anthropic целиком', async () => {
    // Без текста ответа «не сработало» одинаково выглядит при неподходящем
    // ключе, закрытом на прокси пути и личной организации.
    fetchApiBalance.mockResolvedValue(balance({ synced_at: null }))
    syncApiBalance.mockResolvedValue(
      balance({ synced_at: null, sync_error: 'Отчёт о тратах: HTTP 401 invalid x-api-key' })
    )
    render(<DashboardBalance />)

    await userEvent.click(await screen.findByRole('button', { name: 'Сверить траты' }))

    expect(await screen.findByText(/HTTP 401 invalid x-api-key/)).toBeInTheDocument()
  })

  it('удачная сверка не оставляет сообщения об ошибке', async () => {
    fetchApiBalance.mockResolvedValue(balance({ synced_at: null }))
    syncApiBalance.mockResolvedValue(balance({ synced_at: '2026-09-01T10:00:00Z' }))
    render(<DashboardBalance />)

    await userEvent.click(await screen.findByRole('button', { name: 'Сверить траты' }))

    await waitFor(() => expect(syncApiBalance).toHaveBeenCalled())
    expect(screen.queryByText(/Сверка не прошла/)).not.toBeInTheDocument()
  })

  it('внесённая отметка сразу пересчитывает остаток', async () => {
    fetchApiBalance.mockResolvedValue(
      balance({ remaining_usd: null, mark_usd: null, level: 'unknown' })
    )
    createBalanceMark.mockResolvedValue(balance({ remaining_usd: 990, mark_usd: 1000 }))
    render(<DashboardBalance />)

    await userEvent.click(await screen.findByRole('button', { name: 'Внести баланс' }))
    await userEvent.type(screen.getByPlaceholderText('500'), '1000')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(createBalanceMark).toHaveBeenCalled())
    expect(createBalanceMark.mock.calls[0][0]).toBe(1000)
    expect(await screen.findByText(/\$990,00/)).toBeInTheDocument()
  })
})
