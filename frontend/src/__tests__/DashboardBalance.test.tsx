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
import { numbersIn } from './screenQueries'

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

  it('показывает остаток, на сколько дней и на сколько смет его хватит', async () => {
    fetchApiBalance.mockResolvedValue(balance())
    const { container } = render(<DashboardBalance />)

    await screen.findByText('Остаток на Claude API')
    // Числа, а не формат «$450,00»: остаток 450, хватит на 30 дней и 45 смет.
    expect(numbersIn(container.textContent)).toEqual(expect.arrayContaining([450, 30, 45]))
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

  // Официальной сверки может не быть никогда: на личной организации Anthropic
  // отвечает 403, а остаток при этом полностью рабочий. Поэтому кнопку
  // выключает только отсутствие ключа, а не отсутствие данных сверки.
  it.each([
    { official_enabled: true, enabled: true },
    { official_enabled: false, enabled: false },
  ])('ключ Anthropic задан: $official_enabled — «Сверить траты» активна: $enabled', async ({ official_enabled, enabled }) => {
    fetchApiBalance.mockResolvedValue(
      balance({ official_enabled, official_through: null, synced_at: null })
    )
    render(<DashboardBalance />)

    const button = await screen.findByRole('button', { name: 'Сверить траты' })
    if (enabled) expect(button).toBeEnabled()
    else expect(button).toBeDisabled()
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

  it('удачная сверка убирает ответ прошлой неудачной', async () => {
    // Своей роли у сообщения об ошибке нет — ищем его по ответу Anthropic,
    // который в нём показан: формулировка вокруг может меняться.
    fetchApiBalance.mockResolvedValue(balance({ synced_at: null }))
    syncApiBalance
      .mockResolvedValueOnce(balance({ synced_at: null, sync_error: 'HTTP 401 invalid x-api-key' }))
      .mockResolvedValueOnce(balance({ synced_at: '2026-09-01T10:00:00Z' }))
    render(<DashboardBalance />)

    const button = await screen.findByRole('button', { name: 'Сверить траты' })
    await userEvent.click(button)
    expect(await screen.findByText(/HTTP 401 invalid x-api-key/)).toBeInTheDocument()

    await userEvent.click(button)
    await waitFor(() => expect(syncApiBalance).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByText(/HTTP 401 invalid x-api-key/)).not.toBeInTheDocument())
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
