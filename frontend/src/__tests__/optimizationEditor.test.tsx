/**
 * Оптимизация в едином редакторе: версии, сравнение, предложения.
 *
 * Фаза 6 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * Главное требование пользователя (решение 11): вкладки версий видны при любом
 * способе открытия. На старой странице они были спрятаны, когда редактор
 * открывали из карточки, — человек не понимал, что версий несколько.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

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
  };
});

vi.mock('../api/estimateVersions', () => ({
  getVersion: vi.fn(),
  getVersions: vi.fn().mockResolvedValue([]),
  rollbackVersion: vi.fn().mockResolvedValue(undefined),
  renameVersion: vi.fn().mockResolvedValue(undefined),
  exportVersion: vi.fn().mockResolvedValue(undefined),
  exportComparison: vi.fn().mockResolvedValue(undefined),
  runOptimization: vi.fn(),
}));

vi.mock('../api/summaryEstimate', () => ({
  setPrimaryVersion: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../api/tasks', () => ({
  fixEmptyPrices: vi.fn(),
  repriceEstimateItem: vi.fn(),
  getTaskStatus: vi.fn().mockResolvedValue({ status: 'completed' }),
}));

import * as api from '../api/documents';
import { useDocumentEditorStore } from '../stores/documentEditor';
import DocumentEditor from '../components/editor/DocumentEditor';

function version(n: number, id: string, name: string): api.VersionBrief {
  return {
    id, version_number: n, version_label: n === 0 ? 'original' : 'custom',
    version_display_name: name, is_rolled_back: false,
    created_at: '2026-08-02T10:00:00+00:00',
    overhead_pct: 3, transport_pct: 3, contingency_pct: 0,
    expenses_overridden: false,
  };
}

const VERSIONS = [
  version(0, 'v0', 'Исходная смета'),
  version(1, 'v1', 'После проверки'),
];

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'optimization', row_format: 'estimate', file_slot: 'result',
    task_id: 'task-1', task_type: 'ESTIMATE_OPTIMIZATION', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v0', versions: VERSIONS, coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3 },
    ...overrides,
  };
}

const ROWS = [
  { id: 'r1', lineage_id: 'r1', type: 'work', name: 'Кладка стен', unit: 'м3',
    qty: 4, price_work: 1000, price_material: null },
];

function mockDoc(overrides: Partial<api.DocumentMeta> = {}, versionId = 'v0') {
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta(overrides));
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: versionId, rev: 0, rows: ROWS, draft_rows: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
});

/** Названия версий встречаются и в тулбаре шагов — ищем строго во вкладках. */
const tabs = () => within(screen.getByTestId('editor-version-tabs'));

describe('вкладки версий видны всегда', () => {
  it('во встроенном виде', async () => {
    mockDoc();
    render(<DocumentEditor cardId="card-1" kind="optimization" />);

    await waitFor(() => expect(screen.getByTestId('editor-version-tabs')).toBeInTheDocument());
    expect(tabs().getByText('Исходная смета')).toBeInTheDocument();
    expect(tabs().getByText('После проверки')).toBeInTheDocument();
  });

  it('в развёрнутом виде', async () => {
    mockDoc();
    render(<DocumentEditor cardId="card-1" kind="optimization" fullHeight />);

    await waitFor(() => expect(screen.getByTestId('editor-version-tabs')).toBeInTheDocument());
    expect(tabs().getByText('Исходная смета')).toBeInTheDocument();
    expect(tabs().getByText('После проверки')).toBeInTheDocument();
  });

  it('у документа с одной версией вкладок нет', async () => {
    mockDoc({ versions: [VERSIONS[0]] });
    render(<DocumentEditor cardId="card-1" kind="optimization" />);

    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '1'));
    expect(screen.queryByTestId('editor-version-tabs')).not.toBeInTheDocument();
  });
});

describe('переключение версии', () => {
  it('грузит строки выбранной версии', async () => {
    mockDoc();
    render(<DocumentEditor cardId="card-1" kind="optimization" />);
    await waitFor(() => expect(screen.getByTestId('editor-version-tabs')).toBeInTheDocument());

    fireEvent.click(tabs().getByText('После проверки'));

    await waitFor(() => {
      expect(vi.mocked(api.getDocumentRows).mock.calls.at(-1)?.[0]).toMatchObject({ versionId: 'v1' });
    });
  });

  it('при непринятых правках спрашивает подтверждение и слушает отказ', async () => {
    mockDoc();
    render(<DocumentEditor cardId="card-1" kind="optimization" />);
    await waitFor(() => expect(screen.getByTestId('editor-version-tabs')).toBeInTheDocument());

    await act(async () => {
      const store = useDocumentEditorStore.getState();
      store.setRows(store.rows.map((r) => ({ ...r, price_work: 5 })));
    });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const callsBefore = vi.mocked(api.getDocumentRows).mock.calls.length;

    fireEvent.click(tabs().getByText('После проверки'));

    expect(confirmSpy).toHaveBeenCalled();
    expect(vi.mocked(api.getDocumentRows).mock.calls.length).toBe(callsBefore);
    confirmSpy.mockRestore();
  });
});

describe('сравнение версий', () => {
  it('открывается из редактора', async () => {
    mockDoc();
    const { getVersion } = await import('../api/estimateVersions');
    vi.mocked(getVersion).mockResolvedValue({
      id: 'v0', task_id: 'task-1', version_number: 0, version_label: 'original',
      version_display_name: 'Исходная смета', overhead_pct: 3, transport_pct: 3,
      contingency_pct: 0, expenses_overridden: false, is_rolled_back: false,
      created_at: '2026-08-02T10:00:00+00:00', rows: [], optimization_proposals: null,
    });
    render(<DocumentEditor cardId="card-1" kind="optimization" />);
    await waitFor(() => expect(screen.getByTestId('editor-version-tabs')).toBeInTheDocument());

    fireEvent.click(tabs().getByRole('button', { name: /Сравнение/ }));

    await waitFor(() => expect(screen.getByText(/Сравнение версий/)).toBeInTheDocument());
  });
});

describe('правки уходят в выбранную версию', () => {
  it('применение шлёт номер выбранной версии, а не активной', async () => {
    mockDoc({}, 'v1');
    vi.mocked(api.applyDocument).mockResolvedValue({
      version_id: 'v1', rev: 1, rows_count: 1, changes_count: 1,
    });
    await useDocumentEditorStore.getState().load({
      cardId: 'card-1', kind: 'optimization', versionId: 'v1',
    });

    const store = useDocumentEditorStore.getState();
    store.setRows(store.rows.map((r) => ({ ...r, price_work: 5 })));
    await useDocumentEditorStore.getState().applyChanges();

    expect(vi.mocked(api.applyDocument).mock.calls[0][1]).toBe('v1');
  });

  it('черновик сохраняется в выбранную версию', async () => {
    vi.useFakeTimers();
    mockDoc({}, 'v1');
    await useDocumentEditorStore.getState().load({
      cardId: 'card-1', kind: 'optimization', versionId: 'v1',
    });

    const store = useDocumentEditorStore.getState();
    store.setRows(store.rows.map((r) => ({ ...r, price_work: 7 })));
    await vi.advanceTimersByTimeAsync(900);

    expect(vi.mocked(api.saveDraft).mock.calls[0][1]).toBe('v1');
    vi.useRealTimers();
  });
});
