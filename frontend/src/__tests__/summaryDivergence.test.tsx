/**
 * Раздел сводной разошёлся со сметой.
 *
 * План: `plans/2026-08-04-pravki-svodnoy-uhodyat-v-smetu.md`, фаза 3.
 *
 * До этой работы раздел был отдельной копией сметы и мог годами жить со своими
 * числами. Такой раздел нельзя ни молча привести к смете, ни молча записать в
 * смету: в первом случае пропадает работа человека, во втором — результат
 * расчёта. Поэтому расхождение показано словами, а сторону выбирает человек.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

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
    resolveSectionDivergence: vi.fn().mockResolvedValue({ prefer: 'section', rows_count: 2 }),
  };
});

import * as api from '../api/documents';
import { useDocumentEditorStore } from '../stores/documentEditor';
import DocumentEditor from '../components/editor/DocumentEditor';

const REF = { cardId: 'card-1', kind: 'summary-section' as const };

const DIVERGENCE = {
  section_rows: 60, estimate_rows: 58,
  section_total: 1800000, estimate_total: 1755000,
};

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'summary-section', row_format: 'estimate',
    file_slot: 'summary', task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST',
    task_status: 'completed', can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1', versions: [], coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3 },
    divergence: DIVERGENCE,
    ...overrides,
  };
}

const ROWS = [
  { id: 'r1', lineage_id: 'r1', num: 1, type: 'work', name: 'Кладка стен',
    unit: 'м3', qty: 4, price_work: 1000, price_material: null, cost: 4000 },
];

function mockDocument(metaOverrides: Partial<api.DocumentMeta> = {}) {
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta(metaOverrides));
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: ROWS, draft_rows: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
});

afterEach(() => {
  useDocumentEditorStore.getState().reset();
});

describe('раздел сводной разошёлся со сметой', () => {
  it('расхождение объяснено словами, с обеими сторонами', async () => {
    mockDocument();
    render(<DocumentEditor cardId={REF.cardId} kind="summary-section" />);

    const banner = await screen.findByTestId('summary-divergence');
    expect(banner).toHaveTextContent(/60/);
    expect(banner).toHaveTextContent(/58/);
    expect(banner).toHaveTextContent(/1 800 000/);
    expect(banner).toHaveTextContent(/1 755 000/);
  });

  it('человек выбирает сторону, и выбор уходит на сервер', async () => {
    mockDocument();
    render(<DocumentEditor cardId={REF.cardId} kind="summary-section" />);

    const banner = await screen.findByTestId('summary-divergence');
    fireEvent.click(within(banner).getByRole('button', { name: /правки раздела/i }));

    await waitFor(() => {
      expect(api.resolveSectionDivergence).toHaveBeenCalledWith('card-1', 'section');
    });
  });

  it('можно взять сторону сметы', async () => {
    mockDocument();
    render(<DocumentEditor cardId={REF.cardId} kind="summary-section" />);

    const banner = await screen.findByTestId('summary-divergence');
    fireEvent.click(within(banner).getByRole('button', { name: /строки сметы/i }));

    await waitFor(() => {
      expect(api.resolveSectionDivergence).toHaveBeenCalledWith('card-1', 'estimate');
    });
  });

  it('когда стороны сходятся, плашки нет', async () => {
    mockDocument({ divergence: null });
    render(<DocumentEditor cardId={REF.cardId} kind="summary-section" />);

    // Документ загрузился — панель редактора на месте, а плашки нет.
    await screen.findByRole('button', { name: /применить/i });
    expect(screen.queryByTestId('summary-divergence')).not.toBeInTheDocument();
  });
});
