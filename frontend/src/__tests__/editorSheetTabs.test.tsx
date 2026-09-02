/**
 * Вкладки листов исходного файла (план `plans/2026-08-04-multisheet-excel.md`).
 *
 * Главное правило: вкладка — только фильтр показа. В сторе всегда лежат строки
 * всех вкладок, поэтому «Применить» записывает документ целиком, а не тот
 * раздел, который был открыт в момент нажатия. Иначе одно нажатие стирало бы
 * остальные разделы сметы.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
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

// Раздел 1: 10 × 1000 = 10 000 работ. Раздел 2: 4 × 500 = 2 000 работ.
const ROWS = [
  { id: 'r1', type: 'work', name: 'Кладка стен', unit: 'м3', qty: 10,
    price_work: 1000, price_material: null, sheet: 'Раздел 1' },
  { id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт', qty: 500,
    price_work: null, price_material: 25, sheet: 'Раздел 1' },
  { id: 'r3', type: 'work', name: 'Штукатурка', unit: 'м2', qty: 4,
    price_work: 500, price_material: null, sheet: 'Раздел 2' },
];

const FLAT_ROWS = [
  { id: 'r1', type: 'work', name: 'Кладка стен', unit: 'м3', qty: 10,
    price_work: 1000, price_material: null },
];

function mockRows(rows: unknown[]) {
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows, draft_rows: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
  vi.mocked(api.applyDocument).mockResolvedValue({
    version_id: 'v1', rev: 1, rows_count: 3, changes_count: 0,
  });
  mockRows(ROWS);
});

function sheetTab(name: string | RegExp) {
  return screen.getByRole('tab', { name });
}

describe('вкладки листов', () => {
  it('документ с несколькими листами показывает вкладку на лист', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    expect(sheetTab(/Раздел 1/)).toBeInTheDocument();
    expect(sheetTab(/Раздел 2/)).toBeInTheDocument();
  });

  it('документ из одного листа вкладок листов не показывает', async () => {
    mockRows(FLAT_ROWS);
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    expect(screen.queryByRole('tablist', { name: /Листы документа/i })).toBeNull();
  });

  it('в таблице видны строки только открытой вкладки', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    const grid = await screen.findByTestId('document-editor-grid');

    // Первая вкладка открыта сразу: две строки Раздела 1.
    expect(grid).toHaveAttribute('data-row-count', '2');

    fireEvent.click(sheetTab(/Раздел 2/));
    await waitFor(() => expect(
      screen.getByTestId('document-editor-grid'),
    ).toHaveAttribute('data-row-count', '1'));
  });

  it('фильтр «Работы» действует внутри открытой вкладки', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    fireEvent.click(screen.getByRole('tab', { name: /работы/i }));

    // В Разделе 1 одна работа из двух строк, работа Раздела 2 не подмешалась.
    await waitFor(() => expect(
      screen.getByTestId('document-editor-grid'),
    ).toHaveAttribute('data-row-count', '1'));
  });

  it('итог показывает и лист, и весь документ', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    // Раздел 1: 10 000 работ + 300 накладных + 12 500 материалов + 375 транспортных
    expect(screen.getByText('ИТОГО по листу «Раздел 1»:')).toBeInTheDocument();
    expect(screen.getByText('23 175,00 ₽')).toBeInTheDocument();

    // Весь документ: плюс Раздел 2 — 2 000 работ + 60 накладных
    expect(screen.getByText('ВСЕГО по документу:')).toBeInTheDocument();
    expect(screen.getByText('25 235,00 ₽')).toBeInTheDocument();
  });

  it('документ из одного листа показывает прежний единственный итог', async () => {
    mockRows(FLAT_ROWS);
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    expect(screen.getByText('ИТОГО:')).toBeInTheDocument();
    expect(screen.queryByText('ВСЕГО по документу:')).toBeNull();
  });

  it('«Применить» записывает все вкладки, а не только открытую', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    // Правка в первой вкладке, чтобы «Применить» стало доступно.
    fireEvent.click(screen.getByRole('button', { name: /добавить строку/i }));
    fireEvent.click(await screen.findByRole('button', { name: /применить/i }));

    await waitFor(() => expect(api.applyDocument).toHaveBeenCalled());
    const sent = vi.mocked(api.applyDocument).mock.calls[0][3] as Array<Record<string, unknown>>;

    // Три исходные строки на месте, включая ту, что лежит на закрытой вкладке.
    expect(sent.map((row) => row.id)).toEqual(
      expect.arrayContaining(['r1', 'r2', 'r3']),
    );
    expect(sent.filter((row) => row.sheet === 'Раздел 2')).toHaveLength(1);
  });

  it('новая строка попадает на открытую вкладку', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    fireEvent.click(sheetTab(/Раздел 2/));
    fireEvent.click(screen.getByRole('button', { name: /добавить строку/i }));

    // Строка видна сразу: попади она на другую вкладку, счётчик остался бы 1.
    await waitFor(() => expect(
      screen.getByTestId('document-editor-grid'),
    ).toHaveAttribute('data-row-count', '2'));
  });

  it('ссылка с листом открывает именно его', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" initialSheet="Раздел 2" />);
    await screen.findByTestId('document-editor-grid');

    await waitFor(() => expect(sheetTab(/Раздел 2/)).toHaveAttribute('aria-selected', 'true'));
  });

  it('открытый лист уходит наружу — ссылка его сохранит', async () => {
    const onStateChange = vi.fn();
    render(
      <DocumentEditor cardId="card-1" kind="estimate" onStateChange={onStateChange} />,
    );
    await screen.findByTestId('document-editor-grid');

    fireEvent.click(sheetTab(/Раздел 2/));

    await waitFor(() => expect(onStateChange).toHaveBeenLastCalledWith(
      { versionId: 'v1', tab: 'all', sheet: 'Раздел 2', collapsed: false, hideMinus: false },
    ));
  });
});

describe('вкладки листов в плоском документе', () => {
  const GENERIC = [
    { row_id: 'g1', sheet: 'Смета КР', cells: { 'Наименование': 'Балка', 'Масса, т': 1.5 } },
    { row_id: 'g2', sheet: 'Смета ОВ', cells: { 'Позиция': 'Радиатор', 'Цена': 4200 } },
  ];

  beforeEach(() => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
      kind: 'list', row_format: 'generic', file_slot: 'result',
      task_type: 'LIST_FROM_GRAND',
    }));
    mockRows(GENERIC);
  });

  it('колонки берутся у открытой вкладки, а не у всего документа', async () => {
    render(<DocumentEditor cardId="card-1" kind="list" />);
    await screen.findByTestId('document-editor-grid');

    // У листов исходного файла шапки разные — общий набор дал бы каждой
    // вкладке пустые колонки соседа.
    expect(screen.getByRole('columnheader', { name: 'Наименование' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Позиция' })).toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: /Смета ОВ/ }));

    await waitFor(() =>
      expect(screen.getByRole('columnheader', { name: 'Позиция' })).toBeInTheDocument());
    expect(screen.queryByRole('columnheader', { name: 'Наименование' })).toBeNull();
  });

  it('лист не показывается колонкой таблицы', async () => {
    render(<DocumentEditor cardId="card-1" kind="list" />);
    await screen.findByTestId('document-editor-grid');

    expect(screen.queryByRole('columnheader', { name: /^__sheet$/ })).toBeNull();
    expect(screen.queryByRole('columnheader', { name: /^sheet$/i })).toBeNull();
  });

  it('лист уходит в документ полем строки, а не ячейкой', async () => {
    render(<DocumentEditor cardId="card-1" kind="list" />);
    await screen.findByTestId('document-editor-grid');

    fireEvent.click(screen.getByRole('button', { name: /добавить строку/i }));
    fireEvent.click(await screen.findByRole('button', { name: /применить/i }));

    await waitFor(() => expect(api.applyDocument).toHaveBeenCalled());
    const sent = vi.mocked(api.applyDocument).mock.calls[0][3] as Array<{
      sheet?: string; cells: Record<string, unknown>;
    }>;

    expect(sent[0].sheet).toBe('Смета КР');
    expect(Object.keys(sent[0].cells)).not.toContain('__sheet');
  });

  it('смена вкладки снимает отметки со строк прежней', async () => {
    render(<DocumentEditor cardId="card-1" kind="list" />);
    await screen.findByTestId('document-editor-grid');

    // Отмечаем строку открытой вкладки — так же, как это делает таблица.
    act(() => useDocumentEditorStore.getState().setSelected(new Set(['g1'])));
    expect(useDocumentEditorStore.getState().selectedKeys.size).toBe(1);

    fireEvent.click(screen.getByRole('tab', { name: /Смета ОВ/ }));

    // Отметка со строки другой вкладки не должна пережить переключение:
    // «удалить отмеченные» унесло бы строку, которой человек уже не видит.
    await waitFor(() =>
      expect(useDocumentEditorStore.getState().selectedKeys.size).toBe(0));
  });
});
