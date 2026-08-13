/**
 * Предупреждение «ИИ не вернул позиции» не должно прятаться в свёрнутой панели.
 *
 * Задача завершилась успешно, файл получен — панель «Ход обработки» свёрнута, и
 * строка о потерянных позициях исходной сметы видна только тому, кто догадался
 * её раскрыть. А неполный перечень — это деньги на тендере.
 *
 * План: `plans/2026-08-14-propusk-pozicij-iz-grand-smety.md`, Фаза 3.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const getTaskStatus = vi.fn()

vi.mock('../api/tasks', () => ({
  getTaskStatus: (...args: unknown[]) => getTaskStatus(...args),
  restartTask: vi.fn(),
  resumeTask: vi.fn(),
}))

import StageProcessingPanel from '../components/card/StageProcessingPanel'

const WARNING = '⚠ ИИ не вернул 2 позиции исходной сметы: №3, №5. Проверьте их вручную — в перечне этих позиций нет.'

function task(log: string[]) {
  return {
    task_id: 't1',
    status: 'completed',
    progress_message: 'Готово',
    progress_log: log,
    started_at: null,
    cost: 0,
  }
}

describe('предупреждение о потерянных позициях', () => {
  it('видно сразу, без раскрытия панели', async () => {
    getTaskStatus.mockResolvedValue(task(['Файл разбит на 1 часть...', WARNING]))

    render(<StageProcessingPanel taskId="t1" />)

    await waitFor(() => expect(screen.getByText(WARNING)).toBeInTheDocument())
  })

  it('без предупреждения панель остаётся свёрнутой', async () => {
    getTaskStatus.mockResolvedValue(task(['Файл разбит на 1 часть...', 'Найдено 12 позиций']))

    render(<StageProcessingPanel taskId="t1" />)

    await waitFor(() => expect(screen.getByText('Ход обработки')).toBeInTheDocument())
    expect(screen.queryByText('Найдено 12 позиций')).not.toBeInTheDocument()
  })
})
