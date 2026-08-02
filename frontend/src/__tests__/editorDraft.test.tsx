import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

import * as api from '../api/documents';
import { useDocumentEditorStore } from '../stores/documentEditor';
import DocumentEditor from '../components/editor/DocumentEditor';
import { GridRow } from '../components/editor/adapters/types';

const REF = { cardId: 'card-1', kind: 'list' as const };

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'list', row_format: 'generic', file_slot: 'result',
    task_id: 'task-1', task_type: 'LIST_FROM_GRAND', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1', versions: [], coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3 },
    ...overrides,
  };
}

const STORED = [
  { row_id: 'r1', cells: { 'Наименование': 'Работа A', 'Кол-во': 1 } },
  { row_id: 'r2', cells: { 'Наименование': 'Работа Б', 'Кол-во': 2 } },
];

function mockDocument(metaOverrides: Partial<api.DocumentMeta> = {}, draft: unknown[] | null = null) {
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta(metaOverrides));
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: metaOverrides.rev ?? 0, rows: STORED, draft_rows: draft,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('черновик', () => {
  it('серия правок уходит на сервер одним сохранением, а не на каждую букву', async () => {
    mockDocument();
    await useDocumentEditorStore.getState().load(REF);
    vi.useFakeTimers();

    const store = useDocumentEditorStore.getState();
    const rows = store.rows;
    store.setRows(rows.map((r, i) => (i === 0 ? { ...r, 'Кол-во': 10 } : r)));
    useDocumentEditorStore.getState().setRows(
      useDocumentEditorStore.getState().rows.map((r, i) => (i === 0 ? { ...r, 'Кол-во': 11 } : r)),
    );
    useDocumentEditorStore.getState().setRows(
      useDocumentEditorStore.getState().rows.map((r, i) => (i === 0 ? { ...r, 'Кол-во': 12 } : r)),
    );

    expect(api.saveDraft).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(900);
    expect(api.saveDraft).toHaveBeenCalledTimes(1);

    const [, , sentRows] = vi.mocked(api.saveDraft).mock.calls[0];
    expect((sentRows as Array<{ cells: Record<string, unknown> }>)[0].cells['Кол-во']).toBe(12);
  });

  it('правка помечает документ как непринятый', async () => {
    mockDocument();
    await useDocumentEditorStore.getState().load(REF);
    expect(useDocumentEditorStore.getState().isDirty).toBe(false);

    const rows = useDocumentEditorStore.getState().rows;
    useDocumentEditorStore.getState().setRows([...rows, { __key: 'r3' } as GridRow]);
    expect(useDocumentEditorStore.getState().isDirty).toBe(true);
  });

  it('сохранённый ранее черновик показывается при открытии', async () => {
    mockDocument({}, [{ row_id: 'r1', cells: { 'Наименование': 'Работа A', 'Кол-во': 99 } }]);
    await useDocumentEditorStore.getState().load(REF);

    const state = useDocumentEditorStore.getState();
    expect(state.isDirty).toBe(true);
    expect(state.rows[0]['Кол-во']).toBe(99);
    // «Как было» помним отдельно — иначе отменить правки было бы не к чему.
    expect(state.baseline[0]['Кол-во']).toBe(1);
  });

  it('отмена правок возвращает применённое состояние', async () => {
    mockDocument({}, [{ row_id: 'r1', cells: { 'Наименование': 'Работа A', 'Кол-во': 99 } }]);
    await useDocumentEditorStore.getState().load(REF);
    await useDocumentEditorStore.getState().discardChanges();

    const state = useDocumentEditorStore.getState();
    expect(state.isDirty).toBe(false);
    expect(state.rows[0]['Кол-во']).toBe(1);
    expect(api.discardDraft).toHaveBeenCalled();
  });
});

describe('применение правок', () => {
  it('успешное применение снимает пометку и двигает номер версии', async () => {
    mockDocument();
    vi.mocked(api.applyDocument).mockResolvedValue({
      version_id: 'v1', rev: 1, rows_count: 2, changes_count: 1,
    });
    await useDocumentEditorStore.getState().load(REF);
    useDocumentEditorStore.getState().setRows(
      useDocumentEditorStore.getState().rows.map((r, i) => (i === 0 ? { ...r, 'Кол-во': 5 } : r)),
    );

    const ok = await useDocumentEditorStore.getState().applyChanges();
    expect(ok).toBe(true);
    const state = useDocumentEditorStore.getState();
    expect(state.isDirty).toBe(false);
    expect(state.meta?.rev).toBe(1);
    expect(state.undoStack).toHaveLength(0);
  });

  it('чужое сохранение показывается как конфликт, а правки не теряются', async () => {
    mockDocument();
    vi.mocked(api.applyDocument).mockRejectedValue({
      response: { status: 409, data: { detail: 'Документ изменился. Последним сохранял: Иванов Иван.' } },
    });
    await useDocumentEditorStore.getState().load(REF);
    useDocumentEditorStore.getState().setRows(
      useDocumentEditorStore.getState().rows.map((r, i) => (i === 0 ? { ...r, 'Кол-во': 5 } : r)),
    );

    const ok = await useDocumentEditorStore.getState().applyChanges();
    expect(ok).toBe(false);
    const state = useDocumentEditorStore.getState();
    expect(state.conflict).toContain('Иванов Иван');
    expect(state.isDirty).toBe(true);
    expect(state.rows[0]['Кол-во']).toBe(5);
  });
});

describe('отмена и повтор', () => {
  it('возвращают предыдущее состояние и снова применяют его', async () => {
    mockDocument();
    await useDocumentEditorStore.getState().load(REF);

    useDocumentEditorStore.getState().setRows(
      useDocumentEditorStore.getState().rows.map((r, i) => (i === 0 ? { ...r, 'Кол-во': 42 } : r)),
    );
    expect(useDocumentEditorStore.getState().rows[0]['Кол-во']).toBe(42);

    useDocumentEditorStore.getState().undo();
    expect(useDocumentEditorStore.getState().rows[0]['Кол-во']).toBe(1);

    useDocumentEditorStore.getState().redo();
    expect(useDocumentEditorStore.getState().rows[0]['Кол-во']).toBe(42);
  });
});

describe('вставка из буфера', () => {
  const TYPED = [
    { row_id: 'r1', cells: { 'Тип': 'Работа', 'Наименование': 'Работа A', 'Кол-во': 1 } },
    { row_id: 'r2', cells: { 'Тип': 'Материал', 'Наименование': 'Материал Б', 'Кол-во': 2 } },
  ];

  function mockTyped() {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0, rows: TYPED, draft_rows: null,
    });
  }

  it('после смены вкладки вставка не уходит в чужую строку', async () => {
    // Регрессия: якорь хранился номером строки в отфильтрованном списке, и
    // «Материалы» после «Все» сдвигали его — правка попадала не туда.
    mockTyped();
    render(<DocumentEditor cardId="card-1" kind="list" />);
    await waitFor(() => expect(screen.getByText('Строк: 2')).toBeInTheDocument());

    const store = useDocumentEditorStore.getState();
    const before = store.rows.map((r) => r['Кол-во']);

    fireEvent.click(screen.getByRole('tab', { name: /Материалы/ }));
    await waitFor(() => expect(screen.getByText('Строк: 1')).toBeInTheDocument());

    fireEvent.paste(screen.getByTestId('document-editor-grid'), {
      clipboardData: { getData: () => '777' },
    });

    // Без выбранной ячейки вставке некуда идти — строки обязаны остаться прежними.
    expect(useDocumentEditorStore.getState().rows.map((r) => r['Кол-во'])).toEqual(before);
  });

  it('вставка в документ только для чтения игнорируется', async () => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(
      meta({ can_write: false, readonly_reason: 'input_readonly' }));
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0, rows: TYPED, draft_rows: null,
    });
    render(<DocumentEditor cardId="card-1" kind="list" fileSlot="input" />);
    await waitFor(() => expect(screen.getByText('Строк: 2')).toBeInTheDocument());

    fireEvent.paste(screen.getByTestId('document-editor-grid'), {
      clipboardData: { getData: () => '777' },
    });

    expect(useDocumentEditorStore.getState().isDirty).toBe(false);
    expect(api.saveDraft).not.toHaveBeenCalled();
  });
});

describe('режим просмотра', () => {
  it('причину «только чтение» показывает сервер, а не клиент', async () => {
    mockDocument({ can_write: false, readonly_reason: 'task_processing' });
    render(<DocumentEditor cardId="card-1" kind="list" />);

    await waitFor(() => {
      expect(screen.getByText(/Идёт расчёт/)).toBeInTheDocument();
    });
    expect(screen.queryByText('Применить')).not.toBeInTheDocument();
  });

  it('исходный файл заказчика открывается только на просмотр', async () => {
    mockDocument({ can_write: false, readonly_reason: 'input_readonly', file_slot: 'input' });
    render(<DocumentEditor cardId="card-1" kind="list" fileSlot="input" />);

    await waitFor(() => {
      expect(screen.getByText(/никогда не перезаписывается/)).toBeInTheDocument();
    });
  });

  it('предупреждение о чужом редактировании показывается с именем', async () => {
    mockDocument({
      lock: { user_id: 7, user_name: 'Пётр Петров', heartbeat_at: new Date().toISOString() },
    });
    render(<DocumentEditor cardId="card-1" kind="list" />);

    await waitFor(() => {
      expect(screen.getByText('Пётр Петров')).toBeInTheDocument();
    });
  });
});
