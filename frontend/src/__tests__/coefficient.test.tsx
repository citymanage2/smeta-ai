/**
 * Коэффициент к ценам и проценты доп. расходов проекта.
 *
 * Фаза 8 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * Решение пользователя: цены в таблице показываются **уже с коэффициентом**.
 * Отсюда главное правило этого файла: правка такой ячейки — это цена с
 * коэффициентом, поэтому в документ уходит исходная (введённое ÷ коэффициент).
 * Иначе снятие коэффициента давало бы не то, что было до него.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { calcEstimateTotals, rowCoefficient } from '../utils/estimateCalc';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { GridRow } from '../components/editor/adapters/types';

const STORED = [
  { id: 'r1', lineage_id: 'r1', type: 'work', name: 'Кладка', unit: 'м2',
    qty: 4, price_work: 1000, price_material: null },
  { id: 'r2', lineage_id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт',
    qty: 10, price_work: null, price_material: 500 },
];

const COEFF = { work: 1.05, material: 1, scope: 'all' };

// --- Расчёт ----------------------------------------------------------------

describe('единый расчёт итогов', () => {
  it('накладные считаются от работ, транспортные — от материалов', () => {
    const totals = calcEstimateTotals(
      estimateAdapter.toGrid(STORED),
      { overhead_pct: 3, transport_pct: 3 },
    );
    expect(totals.sumWork).toBeCloseTo(4000, 6);
    expect(totals.sumMat).toBeCloseTo(5000, 6);
    expect(totals.overhead).toBeCloseTo(120, 6);
    expect(totals.transport).toBeCloseTo(150, 6);
    // То же число, что кладёт в файл и в task.cost бэкенд.
    expect(totals.grand).toBeCloseTo(9270, 6);
  });

  it('ставки проекта участвуют в итоге', () => {
    const totals = calcEstimateTotals(
      estimateAdapter.toGrid(STORED),
      { overhead_pct: 10, transport_pct: 0 },
    );
    expect(totals.grand).toBeCloseTo(9400, 6);
  });

  it('коэффициент действует только на строки из области применения', () => {
    expect(rowCoefficient({ work: 2, material: 3, scope: 'all' }, 'r1'))
      .toEqual({ work: 2, material: 3 });
    expect(rowCoefficient({ work: 2, material: 3, scope: ['r2'] }, 'r1'))
      .toEqual({ work: 1, material: 1 });
    expect(rowCoefficient(null, 'r1')).toEqual({ work: 1, material: 1 });
  });
});

// --- Обратимость -----------------------------------------------------------

describe('коэффициент обратим', () => {
  it('в таблице цена показывается с коэффициентом', () => {
    const grid = estimateAdapter.toGrid(STORED, { coefficient: COEFF });
    expect(grid[0].price_work).toBeCloseTo(1050, 6);
    expect(grid[0].cost_work).toBeCloseTo(4200, 6);
    expect(grid[1].price_material).toBeCloseTo(500, 6);
  });

  it('без правок в документ уходит исходная цена, а не умноженная', () => {
    // Иначе каждое открытие документа множило бы цены заново.
    const grid = estimateAdapter.toGrid(STORED, { coefficient: COEFF });
    const back = estimateAdapter.fromGrid(grid, { coefficient: COEFF }) as Array<Record<string, unknown>>;
    expect(back[0].price_work).toBe(1000);
    expect(back[1].price_material).toBe(500);
  });

  it('введённое в ячейку число — это цена с коэффициентом', () => {
    const grid = estimateAdapter.toGrid(STORED, { coefficient: COEFF });
    grid[0].price_work = 2100;
    const back = estimateAdapter.fromGrid(grid, { coefficient: COEFF }) as Array<Record<string, unknown>>;
    expect(back[0].price_work).toBeCloseTo(2000, 2);
  });

  it('снятие коэффициента возвращает прежние числа', () => {
    const grid = estimateAdapter.toGrid(STORED, { coefficient: COEFF });
    const stored = estimateAdapter.fromGrid(grid, { coefficient: COEFF });
    const plain = estimateAdapter.toGrid(stored);
    expect(plain[0].price_work).toBe(1000);
    expect(plain[0].cost_work).toBeCloseTo(4000, 6);
  });
});

// --- Редактор --------------------------------------------------------------

vi.mock('../api/documents', async () => {
  const actual = await vi.importActual<typeof import('../api/documents')>('../api/documents');
  return {
    ...actual,
    getDocumentMeta: vi.fn(),
    getDocumentRows: vi.fn(),
    saveDraft: vi.fn().mockResolvedValue(undefined),
    discardDraft: vi.fn().mockResolvedValue(undefined),
    applyDocument: vi.fn(),
    sendHeartbeat: vi.fn().mockResolvedValue(null),
    // Поиск аналогов опрашивает сервер при открытии редактора: без мока тест
    // ждал бы реального отказа сети и падал под нагрузкой.
    getAnalogsState: vi.fn().mockResolvedValue({
      run_id: null, status: null, processed: 0, total: 0,
      results: [], error: null, created_at: null,
    }),
    getDocumentHistory: vi.fn().mockResolvedValue([]),
    setDocumentCoefficient: vi.fn().mockResolvedValue({ coefficient: null }),
  };
});

vi.mock('../api/tasks', () => ({
  fixEmptyPrices: vi.fn(),
  repriceEstimateItem: vi.fn(),
}));

import * as api from '../api/documents';
import { useDocumentEditorStore } from '../stores/documentEditor';
import DocumentEditor from '../components/editor/DocumentEditor';

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
    task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1', versions: [], coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3 },
    ...overrides,
  };
}

function mockDocument(metaOverrides: Partial<api.DocumentMeta> = {}) {
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta(metaOverrides));
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: STORED, draft_rows: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  vi.mocked(api.setDocumentCoefficient).mockResolvedValue({ coefficient: null });
});

describe('коэффициент в редакторе', () => {
  it('без коэффициента показывается предложение его задать', async () => {
    mockDocument();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));
    expect(screen.getByRole('button', { name: /Коэффициент/ })).toBeInTheDocument();
  });

  it('с коэффициентом видно, какой он и на что действует', async () => {
    mockDocument({ coefficient: { work: 1.05, material: 1, scope: 'all' } });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByText(/работы ×1,05/)).toBeInTheDocument());
    // Цена в таблице — уже с коэффициентом.
    expect(useDocumentEditorStore.getState().rows[0].price_work).toBeCloseTo(1050, 6);
  });

  it('коэффициент к отмеченным строкам уходит списком строк', async () => {
    mockDocument();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    useDocumentEditorStore.getState().setSelected(new Set(['r2']));
    await waitFor(() => expect(screen.getByText(/Выбрано: 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Коэффициент/ }));

    const workInput = await screen.findByLabelText('Коэффициент на работы');
    fireEvent.change(workInput, { target: { value: '1,2' } });
    // Строки отмечены — область применения по умолчанию «только отмеченные».
    expect(screen.getByLabelText(/Только отмеченные строки/)).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Применить коэффициент' }));

    await waitFor(() => expect(api.setDocumentCoefficient).toHaveBeenCalled());
    const [, payload] = vi.mocked(api.setDocumentCoefficient).mock.calls[0];
    expect(payload).toMatchObject({ work: 1.2, scope: ['r2'] });
  });

  it('коэффициент можно снять', async () => {
    mockDocument({ coefficient: { work: 1.05, material: 1, scope: 'all' } });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByText(/работы ×1,05/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Снять коэффициент' }));

    await waitFor(() => expect(api.setDocumentCoefficient).toHaveBeenCalledWith(
      expect.anything(), null,
    ));
  });

  it('итоги считаются по ставкам версии, если у неё свои', async () => {
    // Порядок тот же, что на сервере: проект даёт значение по умолчанию, версия
    // может его переопределить. Иначе на экране одна сумма, а в файле другая.
    mockDocument({
      versions: [{
        id: 'v1', version_number: 0, version_label: 'original',
        version_display_name: 'Смета', is_rolled_back: false,
        created_at: '2026-08-02T10:00:00Z',
        overhead_pct: 20, transport_pct: 0, contingency_pct: 0,
        expenses_overridden: true,
      }],
    });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByText('Накладные расходы 20%:')).toBeInTheDocument());
    // 4000 работ × 20% = 800; транспортные 0 → ИТОГО 9800.
    // Итог с копейками — как и колонки стоимостей.
    expect(screen.getByText('9 800,00 ₽')).toBeInTheDocument();
  });

  it('в перечне коэффициента нет — там нет цен', async () => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
      kind: 'list', row_format: 'generic', task_type: 'LIST_FROM_GRAND', file_slot: 'result',
    }));
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0,
      rows: [{ row_id: 'g1', cells: { 'Наименование': 'Работа A' } }],
      draft_rows: null,
    });
    render(<DocumentEditor cardId="card-1" kind="list" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '1'));
    expect(screen.queryByRole('button', { name: /Коэффициент/ })).not.toBeInTheDocument();
  });

  it('правка ячейки при коэффициенте сохраняет исходную цену', async () => {
    mockDocument({ coefficient: { work: 2, material: 1, scope: 'all' } });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    const store = useDocumentEditorStore.getState();
    store.setRows(store.rows.map((row: GridRow, index: number) => (
      index === 0 ? { ...row, price_work: 3000 } : row
    )));

    const sent = useDocumentEditorStore.getState().adapter.fromGrid(
      useDocumentEditorStore.getState().rows,
      { coefficient: { work: 2, material: 1, scope: 'all' } },
    ) as Array<Record<string, unknown>>;
    expect(sent[0].price_work).toBeCloseTo(1500, 2);
  });
});
