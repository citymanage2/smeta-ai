/**
 * «Цены из КП»: свежесть данных вокруг кнопки и окна предпросмотра.
 *
 * * число завершённых запросов перечитывается при возврате на вкладку и при
 *   нажатии — ноль, прочитанный при открытии, не блокирует кнопку навсегда;
 * * 409 при загрузке предпросмотра — «Обновить документ»: версии перечитаны,
 *   предпросмотр берёт последнюю версию, окно не закрывается;
 * * после применения карточка обновляет блок запросов КП;
 * * при коэффициенте версии ≠ 1 окно поясняет, что в таблице цены будут с ним.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';
import { useState } from 'react';

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

vi.mock('../api/kpRequests', async () => {
  const actual = await vi.importActual<typeof import('../api/kpRequests')>('../api/kpRequests');
  return {
    ...actual,
    listCardKpRequests: vi.fn(),
    previewKpApply: vi.fn(),
    applyKpPrices: vi.fn(),
    previewKpRequest: vi.fn(),
  };
});

import * as api from '../api/documents';
import * as kpApi from '../api/kpRequests';
import DocumentEditor from '../components/editor/DocumentEditor';
import KpPrices from '../components/editor/actions/KpPrices';
import KpApplyDialog, { coefficientNote } from '../components/kp/KpApplyDialog';
import { useDocumentEditorStore } from '../stores/documentEditor';
import { useAuthStore } from '../stores/auth';
import type { VersionBrief } from '../api/documents';
import type { KpApplyPreview, KpRequestBrief } from '../types/kp';

function version(overrides: Partial<VersionBrief>): VersionBrief {
  return {
    id: 'v0', version_number: 0, version_label: 'original',
    version_display_name: 'V0 — Оригинал', is_rolled_back: false,
    created_at: '2026-09-01T10:00:00Z', overhead_pct: 0, transport_pct: 0,
    contingency_pct: 0, expenses_overridden: false,
    ...overrides,
  };
}

function brief(overrides: Partial<KpRequestBrief> = {}): KpRequestBrief {
  return {
    id: 'q1', project_id: 'p1', project_name: 'ЖК', card_id: 'card-1', card_name: 'Смета',
    source_kind: 'optimization', category: 'material', target_role: 'supply_manager',
    status: 'done', author_id: 1, author_name: 'Анна', author_comment: null,
    taken_by_id: 2, taken_by_name: 'Олег', taken_at: null, completed_by_id: 2,
    completed_by_name: 'Олег', completed_at: '2026-09-15T10:00:00Z', applied_at: null,
    items_count: 2, files_count: 0, confirmed_prices_count: 3, created_at: '2026-09-14T10:00:00Z', updated_at: null,
    ...overrides,
  };
}

function preview(overrides: Partial<KpApplyPreview> = {}): KpApplyPreview {
  return {
    version_id: 'v2', rev: 7, preview_hash: 'hash-1',
    rows: [{
      row_id: 'r1', name: 'Кирпич', unit: 'шт', sheet: null, source_no: '5', type: 'material',
      field: 'price_material', old_price: 25, new_price: 21.5, request_id: 'q1', item_id: 'i1',
      offer_id: 'o1', supplier: 'ООО Кирпич', offer_date: '2026-09-10', offers_count: 3,
      includes_materials: false, match: 'row_id',
    }],
    ambiguous: [], not_found: [], skipped: [], no_price_count: 0, includes_materials_count: 0,
    ...overrides,
  };
}

const CONFLICT = { response: { status: 409, data: { detail: 'Цены из КП применяются к последней версии оптимизации' } } };
const kpButton = () => screen.getByRole('button', { name: /Цены из КП/ });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(kpApi.listCardKpRequests).mockReset();
  vi.mocked(kpApi.previewKpApply).mockReset();
  vi.mocked(kpApi.applyKpPrices).mockReset();
});

describe('кнопка «Цены из КП» перечитывает завершённые запросы', () => {
  it('при открытии запросов не было, вернулись на вкладку — запрос завершён, кнопка активна', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValueOnce([brief({ status: 'in_progress' })]);
    render(
      <KpPrices
        cardId="card-1" versions={[version({})]} rowsCount={3} isDirty={false}
        onApplied={vi.fn()} onNotice={vi.fn()}
      />,
    );
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalledTimes(1));
    expect(kpButton()).toBeDisabled();

    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    act(() => { window.dispatchEvent(new Event('focus')); });
    await waitFor(() => expect(kpButton()).toBeEnabled());
  });

  it('нажатие тоже перечитывает список', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    vi.mocked(kpApi.previewKpApply).mockResolvedValue(preview());
    render(
      <KpPrices
        cardId="card-1" versions={[version({})]} rowsCount={3} isDirty={false}
        onApplied={vi.fn()} onNotice={vi.fn()}
      />,
    );
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalledTimes(2));
  });
});

describe('409 предпросмотра — «Обновить документ»', () => {
  it('версии перечитаны, предпросмотр уходит к новой последней версии, окно открыто', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    vi.mocked(kpApi.previewKpApply).mockImplementation(async (_card, versionId) => {
      if (versionId === 'v1') throw CONFLICT;
      return preview({ version_id: versionId });
    });

    function Harness() {
      const [versions, setVersions] = useState([version({}), version({ id: 'v1', version_number: 1 })]);
      return (
        <KpPrices
          cardId="card-1" versions={versions} rowsCount={3} isDirty={false}
          onApplied={vi.fn()} onNotice={vi.fn()}
          onRefreshDocument={async () => {
            setVersions((prev) => [...prev, version({ id: 'v2', version_number: 2 })]);
          }}
        />
      );
    }
    render(<Harness />);
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    expect(await screen.findByRole('alert')).toHaveTextContent('последней версии');

    fireEvent.click(screen.getByRole('button', { name: 'Обновить документ' }));
    expect(await screen.findByTestId('kp-apply-rows')).toBeInTheDocument();
    expect(kpApi.previewKpApply).toHaveBeenLastCalledWith('card-1', 'v2');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('без 409 кнопки «Обновить документ» нет', async () => {
    vi.mocked(kpApi.previewKpApply).mockRejectedValue({ response: { status: 500 } });
    render(
      <KpApplyDialog
        cardId="card-1" versionId="v2" onClose={vi.fn()} onApplied={vi.fn()}
        onRefreshDocument={vi.fn()}
      />,
    );
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'Обновить документ' })).not.toBeInTheDocument();
  });
});

describe('коэффициент версии в окне', () => {
  it('×1,2 — пояснение видно; ×1 и без коэффициента — нет', async () => {
    vi.mocked(kpApi.previewKpApply).mockResolvedValue(preview());
    const { unmount } = render(
      <KpApplyDialog
        cardId="card-1" versionId="v2" onClose={vi.fn()} onApplied={vi.fn()}
        coefficient={{ work: 1.2, material: 1.2, scope: 'all' }}
      />,
    );
    expect(await screen.findByTestId('kp-apply-coefficient'))
      .toHaveTextContent('В таблице цены покажутся с коэффициентом ×1,2');
    unmount();

    render(
      <KpApplyDialog
        cardId="card-1" versionId="v2" onClose={vi.fn()} onApplied={vi.fn()}
        coefficient={{ work: 1, material: 1 }}
      />,
    );
    await screen.findByTestId('kp-apply-rows');
    expect(screen.queryByTestId('kp-apply-coefficient')).not.toBeInTheDocument();
  });

  it('разные коэффициенты работ и материалов названы оба', () => {
    expect(coefficientNote({ work: 1.1, material: 0.9 })).toContain('работ ×1,1, материалов ×0,9');
    expect(coefficientNote(null)).toBeNull();
  });

  it('KpPrices передаёт коэффициент, только если открыта последняя версия', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    vi.mocked(kpApi.previewKpApply).mockResolvedValue(preview());
    const props = {
      cardId: 'card-1', rowsCount: 3, isDirty: false, onApplied: vi.fn(), onNotice: vi.fn(),
      versions: [version({}), version({ id: 'v2', version_number: 2 })],
      openCoefficient: { work: 1.5, material: 1.5 },
    };
    const { unmount } = render(<KpPrices {...props} openVersionId="v0" />);
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    await screen.findByTestId('kp-apply-rows');
    expect(screen.queryByTestId('kp-apply-coefficient')).not.toBeInTheDocument();
    unmount();

    render(<KpPrices {...props} openVersionId="v2" />);
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    expect(await screen.findByTestId('kp-apply-coefficient')).toHaveTextContent('×1,5');
  });
});

// --- В редакторе оптимизации ------------------------------------------------------

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'optimization', row_format: 'estimate', file_slot: 'optimization',
    task_id: 'task-1', task_type: 'ESTIMATE_OPTIMIZATION', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1',
    versions: [version({}), version({ id: 'v1', version_number: 1, version_label: 'opt' })],
    coefficient: null, has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3, name: 'ЖК Северный' },
    ...overrides,
  };
}

const ROWS = [
  { id: 'r1', type: 'material', name: 'Кирпич', unit: 'шт', qty: 500, price_work: null, price_material: 25 },
];

let restoreWidth: PropertyDescriptor | undefined;
let originalRect: typeof HTMLElement.prototype.getBoundingClientRect;

beforeAll(() => {
  restoreWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 2000 });
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

describe('редактор оптимизации и «Цены из КП»', () => {
  beforeEach(() => {
    useDocumentEditorStore.getState().reset();
    useAuthStore.getState().setAuth('token', 'project_manager', 'Анна');
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
    vi.mocked(api.getDocumentRows).mockResolvedValue({
      version_id: 'v1', rev: 0, rows: ROWS, draft_rows: null,
    });
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
  });

  it('после применения карточка обновляет блок запросов КП (onKpChanged)', async () => {
    vi.mocked(kpApi.previewKpApply).mockResolvedValue(preview({ version_id: 'v1' }));
    vi.mocked(kpApi.applyKpPrices).mockResolvedValue({
      version_id: 'v1', version_number: 1, source_version_id: 'v1', applied_rows: 1,
      changes_count: 1, request_ids: ['q1'],
    });
    const onKpChanged = vi.fn();
    render(<DocumentEditor cardId="card-1" kind="optimization" onKpChanged={onKpChanged} />);
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    await screen.findByTestId('kp-apply-rows');
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^Применить/ }));
    await waitFor(() => expect(onKpChanged).toHaveBeenCalledTimes(1));
  });

  it('409 предпросмотра: «Обновить документ» перечитывает версии, окно берёт последнюю', async () => {
    vi.mocked(kpApi.previewKpApply).mockImplementation(async (_card, versionId) => {
      if (versionId === 'v1') throw CONFLICT;
      return preview({ version_id: versionId });
    });
    render(<DocumentEditor cardId="card-1" kind="optimization" />);
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    await screen.findByRole('button', { name: 'Обновить документ' });

    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
      versions: [...meta().versions, version({ id: 'v2', version_number: 2, version_label: 'kp' })],
    }));
    const rowsCalls = vi.mocked(api.getDocumentRows).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Обновить документ' }));
    expect(await screen.findByTestId('kp-apply-rows')).toBeInTheDocument();
    expect(kpApi.previewKpApply).toHaveBeenLastCalledWith('card-1', 'v2');
    // Строки документа не перезагружались — черновик и открытая версия на месте.
    expect(vi.mocked(api.getDocumentRows).mock.calls.length).toBe(rowsCalls);
    expect(useDocumentEditorStore.getState().versionId).toBe('v1');
  });
});
