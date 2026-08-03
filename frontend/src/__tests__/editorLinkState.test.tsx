/**
 * Ссылка на состояние документа: этап, версия, вкладка.
 *
 * Фаза 12 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`, сверка с критерием
 * приёмки «ссылка вида документ + версия + вкладка открывает ровно то
 * состояние, из которого её скопировали». Этап в адрес писался с Фазы 3, версия
 * и вкладка — нет: коллега по ссылке попадал в другую версию сметы.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
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

const VERSIONS: api.VersionBrief[] = [
  {
    id: 'v1', version_number: 0, version_label: 'original',
    version_display_name: 'V0 — Оригинал', is_rolled_back: false,
    created_at: '2026-08-01T10:00:00Z', overhead_pct: 3, transport_pct: 3,
    contingency_pct: 0, expenses_overridden: false,
  },
  {
    id: 'v2', version_number: 1, version_label: 'step_1',
    version_display_name: 'V1 — Шаг 1', is_rolled_back: false,
    created_at: '2026-08-02T10:00:00Z', overhead_pct: 3, transport_pct: 3,
    contingency_pct: 0, expenses_overridden: false,
  },
];

function meta(): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
    task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1', versions: VERSIONS, coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3, name: 'ЖК Северный' },
  };
}

const ROWS = [
  { id: 'r1', type: 'work', name: 'Кладка стен', unit: 'м3', qty: 10,
    price_work: 1000, price_material: null },
  { id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт', qty: 500,
    price_work: null, price_material: 25 },
];

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: ROWS, draft_rows: null,
  });
});

describe('состояние документа в ссылке', () => {
  it('сообщает открытую версию и вкладку наружу', async () => {
    const onStateChange = vi.fn();
    render(
      <DocumentEditor cardId="card-1" kind="estimate" onStateChange={onStateChange} />,
    );

    await waitFor(() => expect(onStateChange).toHaveBeenCalled());
    expect(onStateChange).toHaveBeenLastCalledWith({ versionId: 'v1', tab: 'all' });
  });

  it('смена вкладки уходит наружу — ссылка её сохранит', async () => {
    const onStateChange = vi.fn();
    render(
      <DocumentEditor cardId="card-1" kind="estimate" onStateChange={onStateChange} />,
    );
    await screen.findByTestId('document-editor-grid');

    fireEvent.click(screen.getByRole("tab", { name: /работы/i }));

    await waitFor(() =>
      expect(onStateChange).toHaveBeenLastCalledWith({ versionId: 'v1', tab: 'works' }));
  });

  it('ссылка с версией открывает именно её, а не активную', async () => {
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v2', rev: 0, rows: ROWS, draft_rows: null,
    });

    render(
      <DocumentEditor cardId="card-1" kind="estimate" initialVersionId="v2" />,
    );

    await waitFor(() => expect(api.getDocumentRows).toHaveBeenCalled());
    const call = vi.mocked(api.getDocumentRows).mock.calls[0][0];
    expect(call.versionId).toBe('v2');
  });

  it('ссылка с вкладкой открывает её', async () => {
    render(
      <DocumentEditor cardId="card-1" kind="estimate" initialTab="materials" />,
    );

    await screen.findByTestId('document-editor-grid');

    // Вкладка «Материалы» выбрана, и в таблице осталась одна строка из двух.
    expect(screen.getByRole('tab', { name: /материалы/i }))
      .toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/Строк: 1/)).toBeInTheDocument();
  });
});
