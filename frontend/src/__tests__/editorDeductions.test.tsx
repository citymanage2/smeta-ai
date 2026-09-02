/**
 * Скрытие строк с отрицательным объёмом
 * (план `plans/2026-09-02-skrytie-strok-s-minusom.md`).
 *
 * Главное правило то же, что у свёртки: это уровень показа. В сторе всегда
 * лежат настоящие строки документа, поэтому «Применить» записывает их все —
 * включая спрятанные.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';

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
    getDocumentHistory: vi.fn().mockResolvedValue([]),
    getAnalogsState: vi.fn().mockResolvedValue({
      run_id: null, status: null, processed: 0, total: 0,
      results: [], error: null, created_at: null,
    }),
  };
});

import * as api from '../api/documents';
import DocumentEditor from '../components/editor/DocumentEditor';
import { useDocumentEditorStore } from '../stores/documentEditor';
import {
  countDeductions, hideDeductionRows, isDeductionRow,
} from '../components/editor/deductions';
import { dropDeductionExportRows } from '../components/editor/exportBuilder';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
    task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1',
    versions: [{
      id: 'v1', version_number: 0, version_label: 'original',
      version_display_name: 'V0 — Оригинал', is_rolled_back: false,
      created_at: '2026-08-01T10:00:00Z', overhead_pct: 3, transport_pct: 3,
      contingency_pct: 0, expenses_overridden: false,
    }],
    coefficient: null, has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3, name: 'ЖК Северный' },
    ...overrides,
  };
}

// Два вычета: материал и работа. Оба уточняют объём соседней позиции, поэтому
// прячутся оба — правило одно на любой тип строки (решение пользователя
// 02.09.2026).
const ROWS = [
  { id: 'r1', type: 'work', name: 'Штукатурка стен', unit: 'м2', qty: 80,
    price_work: 450, price_material: null },
  { id: 'r2', type: 'material', name: 'Гипсокартон заказчика', unit: 'м2', qty: -12.5,
    price_work: null, price_material: 320 },
  { id: 'r3', type: 'material', name: 'Кирпич', unit: 'шт', qty: 500,
    price_work: null, price_material: 25 },
  { id: 'r4', type: 'work', name: 'Сверление на 10 мм глубже', unit: 'шт', qty: -0.61,
    price_work: 100, price_material: null },
];

function mockRows(rows: unknown[]) {
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows, draft_rows: null,
  });
}

// В jsdom нет ни ResizeObserver, ни размеров: react-data-grid считает таблицу
// нулевой и не рисует ячеек вовсе. Тот же приём, что в `editorCollapse`.
let restoreWidth: PropertyDescriptor | undefined;
let originalRect: typeof HTMLElement.prototype.getBoundingClientRect;

beforeAll(() => {
  restoreWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true, value: 2000,
  });
  originalRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function fake() {
    return { width: 2000, height: 600, top: 0, left: 0, right: 2000,
      bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  };
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Element.prototype.scrollIntoView = () => {};
});

afterAll(() => {
  if (restoreWidth) Object.defineProperty(HTMLElement.prototype, 'clientWidth', restoreWidth);
  HTMLElement.prototype.getBoundingClientRect = originalRect;
});

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
  vi.mocked(api.applyDocument).mockResolvedValue({
    version_id: 'v1', rev: 1, rows_count: 4, changes_count: 0,
  });
  mockRows(ROWS);
});

const minusButton = () => screen.getByRole('button', { name: /Убрать минусы/i });
const collapseButton = () => screen.getByRole('button', { name: /Свернуть дубли/i });
const grid = () => screen.getByTestId('document-editor-grid');
const gridText = () => document.querySelector('.de-grid')?.textContent ?? '';

async function openEditor(rows: unknown[] = ROWS) {
  mockRows(rows);
  render(<DocumentEditor cardId="card-1" kind="estimate" />);
  await screen.findByTestId('document-editor-grid');
}

describe('кнопка «Убрать минусы»', () => {
  it('прячет строки с отрицательным объёмом — и материал, и работу', async () => {
    await openEditor();
    expect(gridText()).toContain('Гипсокартон заказчика');

    fireEvent.click(minusButton());
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '2'));

    const text = gridText();
    expect(text).not.toContain('Гипсокартон заказчика');
    expect(text).not.toContain('Сверление на 10 мм глубже');
    // Обычные позиции остались на месте.
    expect(text).toContain('Штукатурка стен');
    expect(text).toContain('Кирпич');
  });

  it('показывает, сколько строк спрячет', async () => {
    await openEditor();
    expect(minusButton().textContent).toContain('2');
  });

  it('возвращает строки при повторном нажатии', async () => {
    await openEditor();
    fireEvent.click(minusButton());
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '2'));

    fireEvent.click(minusButton());
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '4'));
    expect(gridText()).toContain('Гипсокартон заказчика');
  });

  it('недоступна, когда прятать нечего', async () => {
    await openEditor([ROWS[0], ROWS[2]]);
    expect(minusButton()).toBeDisabled();
  });

  it('документ не меняется: «Применить» отправляет и спрятанные строки', async () => {
    await openEditor();
    fireEvent.click(minusButton());
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '2'));

    // Любая правка, чтобы «Применить» стало доступно.
    fireEvent.click(screen.getByRole('button', { name: /добавить строку/i }));
    fireEvent.click(await screen.findByRole('button', { name: /применить/i }));
    await waitFor(() => expect(api.applyDocument).toHaveBeenCalled());

    const sent = vi.mocked(api.applyDocument).mock.calls[0][3] as Array<Record<string, unknown>>;
    // Четыре исходные строки на месте — обе спрятанные тоже, — плюс новая.
    expect(sent).toHaveLength(5);
    expect(sent.map((row) => row.id)).toEqual(
      expect.arrayContaining(['r1', 'r2', 'r3', 'r4']),
    );
  });

  it('вычет не попадает в общий объём свёрнутой группы', async () => {
    // Две одинаковые позиции по 10 и вычет −4 к той же работе: свёрнутый объём
    // без вычетов — 20, а не 16.
    await openEditor([
      { id: 'a1', type: 'work', name: 'Кладка стен', unit: 'м3', qty: 10,
        price_work: 1000, price_material: null },
      { id: 'a2', type: 'work', name: 'Кладка стен', unit: 'м3', qty: 10,
        price_work: 1000, price_material: null },
      { id: 'a3', type: 'work', name: 'Кладка стен', unit: 'м3', qty: -4,
        price_work: 1000, price_material: null },
    ]);

    fireEvent.click(minusButton());
    fireEvent.click(collapseButton());
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '1'));
    expect(gridText()).toContain('20');
    expect(gridText()).not.toContain('16');
  });

  it('снимает выделение: спрятанную строку нельзя удалить вслепую', async () => {
    await openEditor();
    useDocumentEditorStore.getState().setSelected(new Set(['r2']));
    await waitFor(() => expect(useDocumentEditorStore.getState().selectedKeys.size).toBe(1));

    fireEvent.click(minusButton());
    await waitFor(() => expect(useDocumentEditorStore.getState().selectedKeys.size).toBe(0));
  });
});

describe('правило вычета', () => {
  it('считает вычетом только отрицательный объём', () => {
    expect(isDeductionRow({ __key: 'x', qty: -0.61 }, 'qty')).toBe(true);
    expect(isDeductionRow({ __key: 'x', qty: 0 }, 'qty')).toBe(false);
    expect(isDeductionRow({ __key: 'x', qty: 12 }, 'qty')).toBe(false);
    // Пустая ячейка и текст («по проекту») вычетом не являются.
    expect(isDeductionRow({ __key: 'x', qty: null }, 'qty')).toBe(false);
    expect(isDeductionRow({ __key: 'x', qty: 'по проекту' }, 'qty')).toBe(false);
    // Число приходит из файла строкой с запятой — так его пишет заказчик.
    expect(isDeductionRow({ __key: 'x', qty: '-0,61' }, 'qty')).toBe(true);
  });

  it('фильтр сохраняет порядок остальных строк', () => {
    const rows = [
      { __key: 'a', qty: 1 }, { __key: 'b', qty: -1 }, { __key: 'c', qty: 2 },
    ];
    expect(hideDeductionRows(rows, 'qty').map((row) => row.__key)).toEqual(['a', 'c']);
    expect(countDeductions(rows, 'qty')).toBe(1);
  });

  it('колонку объёма называет адаптер', () => {
    expect(estimateAdapter.qtyKey?.([])).toBe('qty');
    // В плоских документах колонка называется так, как её назвал заказчик, —
    // ищется теми же словами, что и пересчёт «цена × объём».
    const columns = genericAdapter.columns([
      { __key: 'r1', 'Наименование': 'Кладка', 'Кол-во': 5 },
    ]);
    expect(genericAdapter.qtyKey?.(columns)).toBe('Кол-во');
    // Колонки объёма нет — прятать не по чему.
    const noQty = genericAdapter.columns([{ __key: 'r1', 'Наименование': 'Кладка' }]);
    expect(genericAdapter.qtyKey?.(noQty)).toBeNull();
  });

  it('в выгрузке убираются те же строки и тем же правилом', () => {
    const rows = [
      { _id: 'a', qty: 3 }, { _id: 'b', qty: -2 }, { _id: 'c', qty: 0 },
    ];
    expect(dropDeductionExportRows(rows, 'qty').map((row) => row._id)).toEqual(['a', 'c']);
  });
});
