/**
 * Смета в едином редакторе: действия с ценами.
 *
 * Фаза 5 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * «Исправить пустые цены» и «↺ Цена» жили на странице задачи рядом с её
 * собственной таблицей. Таблица уехала в единый редактор — действия едут за ней.
 * Оба пишут смету на сервере, поэтому запускать их поверх непринятых правок
 * нельзя: сервер поднимет `rev`, и правки человека уйдут в конфликт.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

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
  };
});

vi.mock('../api/tasks', () => ({
  fixEmptyPrices: vi.fn(),
  repriceEstimateItem: vi.fn(),
}));

import * as api from '../api/documents';
import * as tasksApi from '../api/tasks';
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

// Две позиции без цены (работа и материал) и одна с ценой; вычет без цены —
// это норма, а не пустая цена, и в счётчик попадать не должен.
const ESTIMATE_ROWS = [
  { id: 'r1', lineage_id: 'r1', type: 'work', name: 'Кладка стен', unit: 'м3',
    qty: 4, price_work: 1000, price_material: null },
  { id: 'r2', lineage_id: 'r2', type: 'work', name: 'Штукатурка', unit: 'м2',
    qty: 10, price_work: null, price_material: null },
  { id: 'r3', lineage_id: 'r3', type: 'material', name: 'Кирпич', unit: 'шт',
    qty: 400, price_work: null, price_material: null },
  { id: 'r4', lineage_id: 'r4', type: 'work', name: 'Вычет глубины', unit: 'м',
    qty: -0.61, price_work: null, price_material: null },
];

const GENERIC_ROWS = [
  { row_id: 'g1', cells: { 'Наименование': 'Работа A', 'Кол-во': 1 } },
];

function mockEstimate(overrides: Partial<api.DocumentMeta> = {}) {
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta(overrides));
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: ESTIMATE_ROWS, draft_rows: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
});

describe('данные строки не теряются в редакторе', () => {
  it('источник цены, ссылки и примечание переживают правку', async () => {
    // Регрессия: их не было в списке переносимых полей, и первое же сохранение
    // из редактора стирало то, что нашёл ИИ, — вместе с колонками в файле.
    const { estimateAdapter } = await import('../components/editor/adapters/estimateAdapter');
    const stored = [{
      ...ESTIMATE_ROWS[0],
      price_list_name: 'Прайс', sources: 'прайс подрядчика', notes: 'с НДС',
    }];

    const grid = estimateAdapter.toGrid(stored);
    grid[0].price_work = 2000;
    const back = estimateAdapter.fromGrid(grid) as Array<Record<string, unknown>>;

    expect(back[0].price_list_name).toBe('Прайс');
    expect(back[0].sources).toBe('прайс подрядчика');
    expect(back[0].notes).toBe('с НДС');
    expect(back[0].price_work).toBe(2000);
  });
});

describe('панель цен доступна только смете', () => {
  it('в смете кнопки есть', async () => {
    mockEstimate();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByText(/Исправить пустые цены/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Цена/ })).toBeInTheDocument();
  });

  it('в перечне кнопок нет', async () => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
      kind: 'list', row_format: 'generic', task_type: 'LIST_FROM_GRAND', file_slot: 'result',
    }));
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0, rows: GENERIC_ROWS, draft_rows: null,
    });
    render(<DocumentEditor cardId="card-1" kind="list" />);

    await waitFor(() => expect(screen.getByText('Строк: 1')).toBeInTheDocument());
    expect(screen.queryByText(/Исправить пустые цены/)).not.toBeInTheDocument();
  });

  it('в режиме просмотра кнопок нет', async () => {
    mockEstimate({ can_write: false, readonly_reason: 'task_processing' });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByText(/Идёт расчёт/)).toBeInTheDocument());
    expect(screen.queryByText(/Исправить пустые цены/)).not.toBeInTheDocument();
  });
});

describe('исправление пустых цен', () => {
  it('счётчик считает пустые цены и не считает вычет', async () => {
    mockEstimate();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByText('Исправить пустые цены (2)')).toBeInTheDocument());
  });

  it('кнопка запускает расчёт', async () => {
    mockEstimate();
    vi.mocked(tasksApi.fixEmptyPrices).mockResolvedValue({ empty_count: 2, status: 'started' });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByText('Исправить пустые цены (2)')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Исправить пустые цены (2)'));

    await waitFor(() => expect(tasksApi.fixEmptyPrices).toHaveBeenCalledWith('task-1'));
  });

  it('при непринятых правках кнопка заблокирована', async () => {
    mockEstimate();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByText('Исправить пустые цены (2)')).toBeInTheDocument());

    const store = useDocumentEditorStore.getState();
    store.setRows(store.rows.map((r, i) => (i === 0 ? { ...r, price_work: 5 } : r)));

    await waitFor(() => {
      expect(screen.getByText(/Исправить пустые цены/).closest('button')).toBeDisabled();
    });
  });

  it('когда пустых цен нет, кнопки нет', async () => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0, rows: [ESTIMATE_ROWS[0]], draft_rows: null,
    });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByText('Строк: 1')).toBeInTheDocument());
    expect(screen.queryByText(/Исправить пустые цены/)).not.toBeInTheDocument();
  });
});

describe('пересчёт цены строки', () => {
  it('без выбранных строк кнопка заблокирована', async () => {
    mockEstimate();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);

    await waitFor(() => expect(screen.getByRole('button', { name: /Цена/ })).toBeDisabled());
  });

  it('уходит по номеру строки в документе и перечитывает документ', async () => {
    mockEstimate();
    vi.mocked(tasksApi.repriceEstimateItem).mockResolvedValue({
      item_index: 1, work_price: 777, material_price: null, sources: 'сайт', notes: '',
    });
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByText('Строк: 4')).toBeInTheDocument());

    useDocumentEditorStore.getState().setSelected(new Set(['r2']));
    await waitFor(() => expect(screen.getByRole('button', { name: /Цена/ })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /Цена/ }));

    await waitFor(() => expect(tasksApi.repriceEstimateItem).toHaveBeenCalledWith('task-1', 1));
    // Цену записал сервер и поднял rev — состояние берём с сервера, а не угадываем.
    await waitFor(() => expect(api.getDocumentRows).toHaveBeenCalledTimes(2));
  });

  it('вычет пересчитать нельзя — цена ему не нужна', async () => {
    mockEstimate();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByText('Строк: 4')).toBeInTheDocument());

    useDocumentEditorStore.getState().setSelected(new Set(['r4']));

    await waitFor(() => expect(screen.getByRole('button', { name: /Цена/ })).toBeDisabled());
  });
});
