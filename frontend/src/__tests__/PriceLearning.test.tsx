/**
 * Экран «Выученные цены».
 *
 * Проверяется главное правило функции: пока человек не нажал «Запомнить», в
 * прайс не уходит ничего (правило 9 CLAUDE.md). И то, что человеку показывают
 * последствия: цена станет главнее прайсов подрядчиков, а разошедшиеся цены
 * помечены как повод перепроверить.
 *
 * План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 7.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getPriceSuggestions = vi.fn()
const acceptPriceSuggestion = vi.fn()
const rejectPriceSuggestion = vi.fn()
const undoPriceDecision = vi.fn()

vi.mock('../api/priceSuggestions', () => ({
  getPriceSuggestions: (...a: unknown[]) => getPriceSuggestions(...a),
  acceptPriceSuggestion: (...a: unknown[]) => acceptPriceSuggestion(...a),
  rejectPriceSuggestion: (...a: unknown[]) => rejectPriceSuggestion(...a),
  undoPriceDecision: (...a: unknown[]) => undoPriceDecision(...a),
}))

vi.mock('../components/Layout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

import PriceLearning from '../pages/PriceLearning'
import type { PriceSuggestion } from '../types/priceSuggestions'

function suggestion(overrides: Partial<PriceSuggestion> = {}): PriceSuggestion {
  return {
    name_key: 'кладка стен',
    display_name: 'Кладка стен',
    row_type: 'work',
    unit: 'м3',
    suggested_price: 2500,
    min_price: 2500,
    max_price: 2500,
    system_price: 3000,
    touches: 3,
    tasks: 2,
    sources: ['Прайс подрядчика №2'],
    prices_disagree: false,
    user_name: 'Иванов Иван',
    last_at: '2026-09-09T10:00:00+00:00',
    decision: null,
    ...overrides,
  }
}

describe('PriceLearning', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    acceptPriceSuggestion.mockResolvedValue({ written: true })
    rejectPriceSuggestion.mockResolvedValue({ decision: 'rejected' })
    undoPriceDecision.mockResolvedValue({ restored: true })
  })

  it('показывает расхождение словами и не пишет в прайс сам', async () => {
    getPriceSuggestions.mockResolvedValue([suggestion()])

    render(<PriceLearning />)

    await waitFor(() => {
      expect(screen.getByText('Кладка стен')).toBeInTheDocument()
    })
    expect(screen.getByText(/система посчитала/)).toBeInTheDocument()
    expect(screen.getByText(/3 000,00 ₽/)).toBeInTheDocument()
    // Ключевое: пока не нажали — ничего не записано.
    expect(acceptPriceSuggestion).not.toHaveBeenCalled()
  })

  it('предупреждает, что цена станет главнее прайсов подрядчиков', async () => {
    getPriceSuggestions.mockResolvedValue([suggestion()])

    render(<PriceLearning />)

    await waitFor(() => {
      expect(screen.getByText(/станет главнее/)).toBeInTheDocument()
    })
  })

  it('записывает цену только по нажатию', async () => {
    getPriceSuggestions.mockResolvedValue([suggestion()])
    const user = userEvent.setup()

    render(<PriceLearning />)
    await waitFor(() => screen.getByText('Кладка стен'))

    await user.click(screen.getByRole('button', { name: 'Запомнить' }))

    await waitFor(() => {
      expect(acceptPriceSuggestion).toHaveBeenCalledWith({
        name: 'Кладка стен', row_type: 'work', unit: 'м3', price: 2500,
      })
    })
  })

  it('даёт поправить цену перед подтверждением', async () => {
    getPriceSuggestions.mockResolvedValue([suggestion()])
    const user = userEvent.setup()

    render(<PriceLearning />)
    await waitFor(() => screen.getByText('Кладка стен'))

    const input = screen.getByLabelText(/Цена для «Кладка стен»/)
    await user.clear(input)
    await user.type(input, '2650')
    await user.click(screen.getByRole('button', { name: 'Запомнить' }))

    await waitFor(() => {
      expect(acceptPriceSuggestion).toHaveBeenCalledWith(
        expect.objectContaining({ price: 2650 }),
      )
    })
  })

  it('«Не запоминать» в прайс ничего не пишет', async () => {
    getPriceSuggestions.mockResolvedValue([suggestion()])
    const user = userEvent.setup()

    render(<PriceLearning />)
    await waitFor(() => screen.getByText('Кладка стен'))

    await user.click(screen.getByRole('button', { name: 'Не запоминать' }))

    await waitFor(() => {
      expect(rejectPriceSuggestion).toHaveBeenCalled()
    })
    expect(acceptPriceSuggestion).not.toHaveBeenCalled()
  })

  it('помечает разошедшиеся цены как повод перепроверить', async () => {
    getPriceSuggestions.mockResolvedValue([
      suggestion({ min_price: 2500, max_price: 25000, prices_disagree: true }),
    ])

    render(<PriceLearning />)

    await waitFor(() => {
      expect(screen.getByText(/Цены расходятся больше чем в полтора раза/))
        .toBeInTheDocument()
    })
  })

  it('пустая очередь объясняет, когда появится предложение', async () => {
    getPriceSuggestions.mockResolvedValue([])

    render(<PriceLearning />)

    await waitFor(() => {
      expect(screen.getByText(/поправили по цене хотя бы дважды/)).toBeInTheDocument()
    })
  })

  it('решённое можно вернуть в очередь', async () => {
    getPriceSuggestions.mockResolvedValue([suggestion({ decision: 'rejected' })])
    const user = userEvent.setup()

    render(<PriceLearning />)
    await waitFor(() => screen.getByText('Кладка стен'))

    await user.click(screen.getByRole('button', { name: 'Уже решённые' }))
    await waitFor(() => screen.getByRole('button', { name: 'Вернуть в очередь' }))
    await user.click(screen.getByRole('button', { name: 'Вернуть в очередь' }))

    await waitFor(() => {
      expect(undoPriceDecision).toHaveBeenCalledWith({
        name: 'Кладка стен', row_type: 'work', unit: 'м3',
      })
    })
  })
})
