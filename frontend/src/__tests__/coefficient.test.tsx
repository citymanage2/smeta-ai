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
import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { withGridLayout } from './gridLayout';
import { cellIn, getGridRow, numberNextTo, parseScreenNumber } from './screenQueries';

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

  it('итоги перечня считаются по типу строки, проценты — из настроек проекта', () => {
    // В перечне колонки называет заказчик: стоимость работ и материалов
    // узнаётся по заголовку, а в итог идёт только по своему типу строки.
    const grid = genericAdapter.toGrid([
      { row_id: 'g1', cells: { 'Тип': 'Работа', 'Наименование': 'Кладка',
        'Стоимость работ': 1000, 'Стоимость материалов': 0 } },
      { row_id: 'g2', cells: { 'Тип': 'Материал', 'Наименование': 'Кирпич',
        'Стоимость работ': 0, 'Стоимость материалов': 2000 } },
      // Стоимость работ у материала в сумму работ не идёт: строка — материал.
      { row_id: 'g3', cells: { 'Тип': 'Материал', 'Наименование': 'Раствор',
        'Стоимость работ': 500, 'Стоимость материалов': 400 } },
      // Строка без типа (заголовок раздела) в итог не идёт вовсе.
      { row_id: 'g4', cells: { 'Тип': '', 'Наименование': 'Раздел 1',
        'Стоимость работ': 9999, 'Стоимость материалов': 9999 } },
    ]);
    const totals = genericAdapter.totals(grid, { overhead_pct: 10, transport_pct: 5 })!;

    expect(totals.sumWork).toBe(1000);
    expect(totals.overhead).toBeCloseTo(100, 6);
    expect(totals.sumMat).toBe(2400);
    expect(totals.transport).toBeCloseTo(120, 6);
    expect(totals.grand).toBeCloseTo(3620, 6);
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

// Ячейки таблицы нужны: цена читается с экрана, правка идёт двойным щелчком.
withGridLayout();

async function waitForRows(count: number) {
  await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
    .toHaveAttribute('data-row-count', String(count)));
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  vi.mocked(api.setDocumentCoefficient).mockResolvedValue({ coefficient: null });
  vi.mocked(api.applyDocument).mockResolvedValue({
    version_id: 'v1', rev: 1, rows_count: 2, changes_count: 1,
  });
});

describe('коэффициент в редакторе', () => {
  it('без коэффициента показывается предложение его задать', async () => {
    mockDocument();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));
    expect(screen.getByRole('button', { name: /Коэффициент/ })).toBeInTheDocument();
  });

  it('с коэффициентом цена в таблице показана уже умноженной', async () => {
    mockDocument({ coefficient: { work: 1.05, material: 1, scope: 'all' } });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitForRows(2);

    // 1000 × 1,05 — человек видит цену с коэффициентом, а не исходную.
    const row = getGridRow('Кладка');
    expect(parseScreenNumber(cellIn(row, 'Цена работ').textContent)).toBe(1050);
    expect(parseScreenNumber(cellIn(row, 'Стоим. работ').textContent)).toBe(4200);
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

    // 4000 работ × 20% = 800; транспортные 0 → ИТОГО 9800 (по ставкам проекта было бы 9270).
    await waitFor(() => expect(numberNextTo('ИТОГО:')).toBe(9800));
    expect(numberNextTo(/^Накладные расходы/)).toBe(800);
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
    await waitForRows(2);

    // В ячейке 2000 (1000 × 2). Человек ставит 3000 — это цена с коэффициентом.
    fireEvent.doubleClick(cellIn(getGridRow('Кладка'), 'Цена работ'));
    const input = await screen.findByDisplayValue('2000');
    fireEvent.change(input, { target: { value: '3000' } });
    // Enter, а не blur: React слушает focusout, и blur из jsdom редактор не увидит.
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.click(screen.getByRole('button', { name: 'Применить' }));

    await waitFor(() => expect(api.applyDocument).toHaveBeenCalled());
    const sent = vi.mocked(api.applyDocument).mock.calls[0][3] as Array<Record<string, unknown>>;
    const byId = new Map(sent.map((row) => [row.id, row]));
    // В документ уходит исходная: 3000 ÷ 2.
    expect(byId.get('r1')!.price_work).toBe(1500);
    // Нетронутая цена материала уходит как была.
    expect(byId.get('r2')!.price_material).toBe(500);
  });
});
