/**
 * Как редактор показывает числа и типы строк.
 *
 * План `plans/2026-08-04-chitaemye-chisla-v-redaktore.md`.
 *
 * Главное правило файла: формат живёт только на показе. Значение строки
 * остаётся числом — иначе «196 171,20» уехало бы в выгрузку и в xlsx, и ячейка
 * Excel стала бы текстовой, а колонку в скачанном файле не просуммировать.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { formatDecimal, formatMoney } from '../utils/formatNumber';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { GridRow } from '../components/editor/adapters/types';

// В русской локали разряды отбиваются неразрывным пробелом — на экране это
// пробел, но сравнивать надо с тем символом, который реально печатается.
const NBSP = ' ';

const STORED = [
  { id: 'r1', lineage_id: 'r1', type: 'work', name: 'Устройство потолков', unit: 'м2',
    qty: 382.4, price_work: 513, price_material: null },
  { id: 'r2', lineage_id: 'r2', type: 'material', name: 'Листы ГКЛ', unit: 'м2',
    qty: 424.46, price_work: null, price_material: 195 },
];

// --- Формат ----------------------------------------------------------------

describe('формат чисел', () => {
  it('деньги — разряды пробелом, две цифры после запятой', () => {
    expect(formatMoney(1111111.11)).toBe(`1${NBSP}111${NBSP}111,11`);
    expect(formatMoney(196171.2)).toBe(`196${NBSP}171,20`);
    expect(formatMoney(513)).toBe('513,00');
  });

  it('объём — запятая, без хвостовых нулей', () => {
    expect(formatDecimal(382.4)).toBe('382,4');
    expect(formatDecimal(0.61)).toBe('0,61');
    expect(formatDecimal(1338.4)).toBe(`1${NBSP}338,4`);
    expect(formatDecimal(50)).toBe('50');
  });
});

// --- Смета -----------------------------------------------------------------

describe('смета: что показывается в ячейке', () => {
  const grid = estimateAdapter.toGrid(STORED);

  it('цена и стоимость — денежным форматом', () => {
    expect(estimateAdapter.displayValue!(grid[0], 'price_work')).toBe('513,00');
    expect(estimateAdapter.displayValue!(grid[0], 'cost_work'))
      .toBe(`196${NBSP}171,20`);
  });

  it('у работы стоимость материалов пустая, у материала — стоимость работ', () => {
    // Ноль читается как посчитанный результат, хотя считать там нечего.
    expect(grid[0].cost_material).toBe(0);
    expect(estimateAdapter.displayValue!(grid[0], 'cost_material')).toBe('');
    expect(estimateAdapter.displayValue!(grid[0], 'price_material')).toBe('');
    expect(estimateAdapter.displayValue!(grid[1], 'cost_work')).toBe('');
    expect(estimateAdapter.displayValue!(grid[1], 'price_work')).toBe('');
  });

  it('объём показывается с запятой', () => {
    expect(estimateAdapter.displayValue!(grid[0], 'qty')).toBe('382,4');
  });

  it('нечисловые колонки показываются как есть', () => {
    expect(estimateAdapter.displayValue!(grid[0], 'name')).toBeNull();
    expect(estimateAdapter.displayValue!(grid[0], 'unit')).toBeNull();
  });

  it('формат не трогает значение строки — в документ уходит число', () => {
    const back = estimateAdapter.fromGrid(grid) as Array<Record<string, unknown>>;
    expect(back[0].price_work).toBe(513);
    expect(back[0].qty).toBe(382.4);
    expect(typeof back[0].price_work).toBe('number');
  });
});

// --- Перечень и полнота ----------------------------------------------------

describe('перечень: что показывается в ячейке', () => {
  const rows = genericAdapter.toGrid([
    { row_id: 'g1', cells: {
      'Тип': 'Работа', 'Наименование': 'Прокладка труб', 'Кол-во': 20,
      'Цена работ': 1234.5, 'Стоимость работ': 24690, 'Примечание': '',
    } },
    { row_id: 'g2', cells: {
      'Тип': 'Материал', 'Наименование': 'Трубы', 'Кол-во': 'по проекту',
      'Цена работ': 0, 'Стоимость работ': 0, 'Примечание': '',
    } },
  ]);

  it('деньги и объём форматируются по названию колонки', () => {
    expect(genericAdapter.displayValue!(rows[0], 'Цена работ'))
      .toBe(`1${NBSP}234,50`);
    expect(genericAdapter.displayValue!(rows[0], 'Стоимость работ'))
      .toBe(`24${NBSP}690,00`);
    expect(genericAdapter.displayValue!(rows[0], 'Кол-во')).toBe('20');
  });

  it('ноль в денежной колонке — пустая ячейка', () => {
    expect(genericAdapter.displayValue!(rows[1], 'Стоимость работ')).toBe('');
  });

  it('текст в числовой колонке сохраняется', () => {
    // В перечне заказчика в колонке количества попадается «по проекту» —
    // потерять это значит потерять смысл строки.
    expect(genericAdapter.displayValue!(rows[1], 'Кол-во')).toBeNull();
  });

  it('прочие колонки не форматируются', () => {
    expect(genericAdapter.displayValue!(rows[0], 'Наименование')).toBeNull();
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

function mockDocument() {
  vi.mocked(api.getDocumentMeta).mockResolvedValue({
    card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
    task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1', versions: [], coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 0, transport_pct: 0 },
  } as api.DocumentMeta);
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: STORED, draft_rows: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
});

describe('таблица редактора', () => {
  it('в ячейку попадает отформатированное число, а не сырое', async () => {
    // В jsdom нет ResizeObserver, поэтому react-data-grid считает ширину
    // нулевой и рисует только первые колонки — денежных ячеек в DOM просто нет.
    // Подставляем наблюдателя и ширину, иначе проверять нечего.
    const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true, value: 2000,
    });
    const rect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function fake() {
      return { width: 2000, height: 600, top: 0, left: 0, right: 2000,
        bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    };
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    try {
      mockDocument();
      const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);

      await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
        .toHaveAttribute('data-row-count', '2'));
      const text = container.querySelector('.de-grid')?.textContent ?? '';

      expect(text).toContain(`196${NBSP}171,20`);
      expect(text).toContain('382,4');
      expect(text).not.toContain('196171.2');
    } finally {
      if (width) Object.defineProperty(HTMLElement.prototype, 'clientWidth', width);
      HTMLElement.prototype.getBoundingClientRect = rect;
      delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    }
  });

  it('работа и материал различаются классом строки', async () => {
    mockDocument();
    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));
    expect(container.querySelectorAll('.de-row-work')).toHaveLength(1);
    expect(container.querySelectorAll('.de-row-material')).toHaveLength(1);
  });

  it('итог показан с копейками — как и колонки стоимостей', async () => {
    mockDocument();
    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));
    // 382,4 × 513 + 424,46 × 195 = 196 171,20 + 82 769,70
    expect(container.querySelector('.de-totals')?.textContent)
      .toContain(`Сумма по работам:196${NBSP}171,20 ₽`);
    expect(container.querySelector('.de-totals-grand b')?.textContent)
      .toBe(`278${NBSP}940,90 ₽`);
  });

  it('подсветка состояния строки не пропадает из-за цвета типа', async () => {
    // Вычет (объём < 0) важнее цвета «работа/материал»: стоимость по такой
    // строке не считается, и это должно быть видно.
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0, draft_rows: null,
      rows: [{ ...STORED[0], qty: -5 }],
    });
    vi.mocked(api.getDocumentMeta).mockResolvedValue({
      card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
      task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
      can_write: true, readonly_reason: null, rev: 0,
      active_version_id: 'v1', versions: [], coefficient: null,
      has_draft: false, draft_updated_at: null, lock: null,
      project: { overhead_pct: 0, transport_pct: 0 },
    } as api.DocumentMeta);

    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '1'));
    const row = container.querySelector('.de-row-work') as HTMLElement;
    expect(row).toHaveClass('de-row-deduction');
  });
});

// --- Выгрузка --------------------------------------------------------------

describe('выгрузка получает числа, а не текст', () => {
  it('в строках выгрузки остаются числа', async () => {
    const { rowsFromEditor, columnsFromEditor } = await import(
      '../components/editor/exportBuilder'
    );
    const grid: GridRow[] = estimateAdapter.toGrid(STORED);
    const columns = columnsFromEditor(estimateAdapter.columns(grid));
    const exported = rowsFromEditor(grid, columns, estimateAdapter.rowKind);

    expect(exported[0].cost_work).toBe(196171.2);
    expect(typeof exported[0].cost_work).toBe('number');
  });
});
