/**
 * Правила для ИИ: новое правило не действует, пока его не включили.
 *
 * План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getPromptRules = vi.fn()
const createPromptRule = vi.fn()
const setPromptRuleEnabled = vi.fn()
const deletePromptRule = vi.fn()

vi.mock('../api/promptRules', () => ({
  getPromptRules: (...a: unknown[]) => getPromptRules(...a),
  createPromptRule: (...a: unknown[]) => createPromptRule(...a),
  setPromptRuleEnabled: (...a: unknown[]) => setPromptRuleEnabled(...a),
  deletePromptRule: (...a: unknown[]) => deletePromptRule(...a),
}))

import PromptRulesCard from '../components/corrections/PromptRulesCard'

const rule = (over = {}) => ({
  id: 1, text: 'Демонтаж кабеля — в метрах', scope: 'ALL', enabled: false,
  created_by: 'Руководитель', enabled_by: null, enabled_at: null,
  created_at: '2026-09-14T10:00:00+00:00', ...over,
})

describe('PromptRulesCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    createPromptRule.mockResolvedValue(rule())
    setPromptRuleEnabled.mockResolvedValue(rule({ enabled: true }))
  })

  it('создаёт правило и не включает его само', async () => {
    getPromptRules.mockResolvedValue([])
    const user = userEvent.setup()
    render(<PromptRulesCard />)

    await user.type(screen.getByLabelText('Текст правила'), 'Новое правило')
    await user.click(screen.getByRole('button', { name: 'Добавить правило' }))

    await waitFor(() => expect(createPromptRule).toHaveBeenCalledWith('Новое правило', 'ALL'))
    expect(setPromptRuleEnabled).not.toHaveBeenCalled()
  })

  it('включает правило только по нажатию', async () => {
    getPromptRules.mockResolvedValue([rule()])
    const user = userEvent.setup()
    render(<PromptRulesCard />)

    await waitFor(() => screen.getByText('Демонтаж кабеля — в метрах'))
    expect(screen.getByText(/выключено/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Включить' }))
    await waitFor(() => expect(setPromptRuleEnabled).toHaveBeenCalledWith(1, true))
  })
})
