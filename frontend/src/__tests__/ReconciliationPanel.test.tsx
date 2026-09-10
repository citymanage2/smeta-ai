/**
 * Панель сверки с расчётом ИИ.
 *
 * Проверяется то, ради чего панель и сделана: видно, кто изменил число — сам
 * сервис (подбор цен, проверка единиц, коэффициент) или человек. И состояние,
 * в котором легко соврать: снимка расчёта нет — сравнивать не с чем, и это надо
 * сказать словами, а не показать пустой список, будто всё совпало.
 *
 * План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 3.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const getDocumentReconciliation = vi.fn()

vi.mock('../api/documents', () => ({
  getDocumentReconciliation: (...a: unknown[]) => getDocumentReconciliation(...a),
}))

import ReconciliationPanel from '../components/editor/ReconciliationPanel'
import type { Reconciliation } from '../api/documents'

const docRef = { cardId: 'c1', kind: 'estimate' as const }

function data(overrides: Partial<Reconciliation> = {}): Reconciliation {
  return {
    has_baseline: true,
    baseline_truncated: false,
    ai_row_count: 2,
    compared_row_count: 2,
    match_mode: 'row_id',
    truncated: false,
    rows: [],
    totals: { ai_total: 14935, current_total: 12875, delta: -2060, delta_pct: -13.79 },
    counts: {
      rows_changed: 1, rows_added: 0, rows_removed: 0,
      cells_by_human: 1, cells_by_service: 0,
    },
    ...overrides,
  }
}

function cell(overrides = {}) {
  return {
    field: 'Цена работ',
    field_key: 'price_work',
    ai_value: '3000',
    service_value: '3000',
    current_value: '2500',
    changed_by: 'human' as const,
    delta: -500,
    delta_pct: -16.67,
    price_source: 'Прайс подрядчика №2',
    user_name: 'Иванов Иван',
    ...overrides,
  }
}

describe('ReconciliationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('говорит словами, когда расчёт ИИ не сохранён', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      has_baseline: false,
      rows: [],
      totals: { ai_total: null, current_total: 12875, delta: null, delta_pct: null },
      counts: {
        rows_changed: 0, rows_added: 0, rows_removed: 0,
        cells_by_human: 0, cells_by_service: 0,
      },
    }))

    render(<ReconciliationPanel documentRef={docRef} onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText(/Расчёт ИИ по этому документу не сохранён/)).toBeInTheDocument()
    })
  })

  it('показывает правку человека с автором и источником цены', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      rows: [{
        row_key: 'e1', row_number: 1, row_name: 'Кладка стен',
        status: 'changed', cells: [cell()],
      }],
    }))

    render(<ReconciliationPanel documentRef={docRef} onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('Кладка стен')).toBeInTheDocument()
    })
    expect(screen.getByText('Иванов Иван')).toBeInTheDocument()
    expect(screen.getByText('3000')).toBeInTheDocument()
    expect(screen.getByText('2500')).toBeInTheDocument()
    expect(screen.getByText(/Прайс подрядчика №2/)).toBeInTheDocument()
  })

  it('не приписывает человеку то, что изменил сам сервис', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      rows: [{
        row_key: 'e1', row_number: 1, row_name: 'Кладка стен', status: 'changed',
        cells: [cell({
          changed_by: 'service', service_value: '2800', current_value: '2800',
          user_name: null, delta: -200, delta_pct: -6.67,
        })],
      }],
      counts: {
        rows_changed: 1, rows_added: 0, rows_removed: 0,
        cells_by_human: 0, cells_by_service: 1,
      },
    }))

    const { container } = render(
      <ReconciliationPanel documentRef={docRef} onClose={() => {}} />,
    )

    // Автор помечен именно «сервисом»: слово «сервис» есть и в подписи шага,
    // поэтому проверяем бейдж автора, а не текст на странице.
    await waitFor(() => {
      expect(container.querySelector('.de-recon-author-service')).not.toBeNull()
    })
    expect(container.querySelector('.de-recon-author-human')).toBeNull()
    expect(screen.queryByText('Иванов Иван')).not.toBeInTheDocument()
  })

  it('показывает промежуточный шаг сервиса, когда он менял цену до человека', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      rows: [{
        row_key: 'e1', row_number: 1, row_name: 'Кладка стен', status: 'changed',
        cells: [cell({ service_value: '2800' })],
      }],
    }))

    render(<ReconciliationPanel documentRef={docRef} onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('2800')).toBeInTheDocument()
    })
    // Все три шага видны: ИИ → сервис → итог.
    expect(screen.getByText('3000')).toBeInTheDocument()
    expect(screen.getByText('2500')).toBeInTheDocument()
  })

  it('пропущенную и лишнюю позицию называет прямо', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      rows: [
        {
          row_key: 'e3', row_number: 3, row_name: 'Штукатурка',
          status: 'added', changed_by: 'human', cells: [],
        },
        {
          row_key: 'e2', row_number: 2, row_name: 'Кирпич',
          status: 'removed', changed_by: 'human', cells: [],
        },
      ],
      counts: {
        rows_changed: 0, rows_added: 1, rows_removed: 1,
        cells_by_human: 0, cells_by_service: 0,
      },
    }))

    render(<ReconciliationPanel documentRef={docRef} onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText(/позиции не было у ИИ/)).toBeInTheDocument()
    })
    expect(screen.getByText(/позиция ИИ убрана/)).toBeInTheDocument()
  })

  it('совпадение с расчётом ИИ не выглядит как поломка', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      rows: [],
      totals: { ai_total: 14935, current_total: 14935, delta: 0, delta_pct: 0 },
      counts: {
        rows_changed: 0, rows_added: 0, rows_removed: 0,
        cells_by_human: 0, cells_by_service: 0,
      },
    }))

    render(<ReconciliationPanel documentRef={docRef} onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText(/Документ совпадает с расчётом ИИ/)).toBeInTheDocument()
    })
  })

  it('предупреждает, что снимок сохранён не целиком', async () => {
    getDocumentReconciliation.mockResolvedValue(data({
      baseline_truncated: true,
      ai_row_count: 2507,
      compared_row_count: 2500,
      rows: [],
    }))

    render(<ReconciliationPanel documentRef={docRef} onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText(/снимок сохранён/)).toBeInTheDocument()
    })
  })
})
