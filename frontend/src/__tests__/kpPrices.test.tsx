/**
 * Цены из КП в оптимизацию: пометка строк, кнопка «Цены из КП» и окно
 * предпросмотра.
 *
 * План: plans/2026-09-14-zapros-kp.md, фаза 8 (критерии 30–37 спецификации).
 *
 * Главное, что здесь закреплено:
 * * строка с `kp_ref` подсвечена «цена из КП», цена «включает материалы» —
 *   отдельно, подсказка называет поставщика, дату и число КП;
 * * кнопка активна только при завершённых запросах и строках оптимизации;
 * * «Применить» уходит с `client_rev` и `preview_hash` предпросмотра, по
 *   «Неоднозначно» — только выбор человека, и ведёт на новую версию;
 * * 409 — понятное сообщение, окно не закрывается и версию не меняет.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';

vi.mock('../api/kpRequests', async () => {
  const actual = await vi.importActual<typeof import('../api/kpRequests')>('../api/kpRequests');
  return {
    ...actual,
    listCardKpRequests: vi.fn(),
    previewKpApply: vi.fn(),
    applyKpPrices: vi.fn(),
  };
});

import * as kpApi from '../api/kpRequests';
import { estimateAdapter, kpRowHint } from '../components/editor/adapters/estimateAdapter';
import KpPrices from '../components/editor/actions/KpPrices';
import KpApplyDialog from '../components/kp/KpApplyDialog';
import type { VersionBrief } from '../api/documents';
import type { KpApplyItem, KpApplyPreview, KpApplyRow, KpRequestBrief } from '../types/kp';

function version(overrides: Partial<VersionBrief>): VersionBrief {
  return {
    id: 'v0', version_number: 0, version_label: 'original',
    version_display_name: 'V0 — Оригинал', is_rolled_back: false,
    created_at: '2026-09-01T10:00:00Z', overhead_pct: 0, transport_pct: 0,
    contingency_pct: 0, expenses_overridden: false,
    ...overrides,
  };
}

function brief(overrides: Partial<KpRequestBrief>): KpRequestBrief {
  return {
    id: 'q1', project_id: 'p1', project_name: 'ЖК', card_id: 'card-1', card_name: 'Смета',
    source_kind: 'optimization', category: 'material', target_role: 'supply_manager',
    status: 'done', author_id: 1, author_name: 'Анна', author_comment: null,
    taken_by_id: 2, taken_by_name: 'Олег', taken_at: null, completed_by_id: 2,
    completed_by_name: 'Олег', completed_at: '2026-09-15T10:00:00Z', applied_at: null,
    items_count: 2, files_count: 0, created_at: '2026-09-14T10:00:00Z', updated_at: null,
    ...overrides,
  };
}

function row(overrides: Partial<KpApplyRow>): KpApplyRow {
  return {
    row_id: 'r1', name: 'Кирпич', unit: 'шт', sheet: null, source_no: '5', type: 'material',
    field: 'price_material', old_price: 25, new_price: 21.5, request_id: 'q1', item_id: 'i1',
    offer_id: 'o1', supplier: 'ООО Кирпич', offer_date: '2026-09-10', offers_count: 3,
    includes_materials: false, match: 'row_id',
    ...overrides,
  };
}

function item(overrides: Partial<KpApplyItem>): KpApplyItem {
  return {
    request_id: 'q2', item_id: 'i9', item_type: 'work', name: 'Монтаж перегородки', unit: 'м2',
    sheet: null, source_no: null, price: 800, supplier: 'СтройМонтаж', offer_date: '2026-09-11',
    offers_count: 2, includes_materials: false, candidates: [],
    ...overrides,
  };
}

function preview(overrides: Partial<KpApplyPreview> = {}): KpApplyPreview {
  return {
    version_id: 'v2', rev: 7, preview_hash: 'hash-1', rows: [], ambiguous: [], not_found: [],
    skipped: [], no_price_count: 0, includes_materials_count: 0,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(kpApi.listCardKpRequests).mockReset();
  vi.mocked(kpApi.previewKpApply).mockReset();
  vi.mocked(kpApi.applyKpPrices).mockReset();
});

// --- Пометка строк -------------------------------------------------------------

describe('строка с ценой из КП', () => {
  it('подсвечена «цена из КП», подсказка — поставщик, дата и число КП', () => {
    const r = {
      __key: 'r1', type: 'Материал', name: 'Кирпич', price_material: 42.5,
      kp_ref: {
        supplier: 'ООО Кирпич', offer_date: '2026-09-10', offers_count: 3, includes_materials: false,
        field: 'price_material', price: 42.5,
      },
    };
    const css = estimateAdapter.rowClass?.(r) ?? '';
    expect(css.split(' ')).toContain('de-row-kp');
    expect(css).not.toContain('de-row-kp-materials');
    const hint = kpRowHint(r) ?? '';
    expect(hint).toContain('ООО Кирпич');
    expect(hint).toContain('10.09.2026');
    expect(hint).toContain('КП: 3');
  });

  it('цена работы «включает материалы» — отдельная подсветка и «проверьте материал позиции»', () => {
    const r = {
      __key: 'r2', type: 'Работа', name: 'Монтаж', price_work: 900,
      kp_ref: {
        supplier: 'СтройМонтаж', offer_date: null, offers_count: 1, includes_materials: true,
        field: 'price_work', price: 900,
      },
    };
    const css = (estimateAdapter.rowClass?.(r) ?? '').split(' ');
    expect(css).toContain('de-row-kp-materials');
    expect(css).not.toContain('de-row-kp');
    expect(kpRowHint(r)).toContain('проверьте материал позиции');
  });

  it('без kp_ref — ни класса, ни подсказки; kp_ref не объект — тоже', () => {
    expect(estimateAdapter.rowClass?.({ __key: 'a', type: 'Работа' }) ?? '').not.toContain('de-row-kp');
    expect(kpRowHint({ __key: 'a' })).toBeNull();
    expect(kpRowHint({ __key: 'b', kp_ref: 'текст' })).toBeNull();
    expect(estimateAdapter.rowClass?.({ __key: 'b', kp_ref: 'текст' }) ?? '').not.toContain('de-row-kp');
  });
});

// --- Кнопка ------------------------------------------------------------------------

function renderButton(props: Partial<React.ComponentProps<typeof KpPrices>> = {}) {
  const onApplied = vi.fn();
  const onNotice = vi.fn();
  render(
    <KpPrices
      cardId="card-1"
      versions={[version({}), version({ id: 'v2', version_number: 2, version_display_name: 'V2' })]}
      rowsCount={10}
      isDirty={false}
      onApplied={onApplied}
      onNotice={onNotice}
      {...props}
    />,
  );
  return { onApplied, onNotice };
}

const kpButton = () => screen.getByRole('button', { name: /Цены из КП/ });

describe('кнопка «Цены из КП»', () => {
  it('неактивна без завершённых запросов', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([
      brief({ status: 'in_progress' }), brief({ id: 'q2', status: 'cancelled' }),
    ]);
    renderButton();
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalledWith('card-1'));
    expect(kpButton()).toBeDisabled();
  });

  it('неактивна без строк оптимизации', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    renderButton({ rowsCount: 0 });
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalled());
    expect(kpButton()).toBeDisabled();
  });

  it('неактивна при непринятых правках', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    renderButton({ isDirty: true });
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalled());
    expect(kpButton()).toBeDisabled();
  });

  it('активна при завершённом запросе и строках; предпросмотр — от последней неоткатанной версии', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({})]);
    vi.mocked(kpApi.previewKpApply).mockResolvedValue(preview({ rows: [row({})] }));
    renderButton({
      versions: [
        version({}),
        version({ id: 'v2', version_number: 2 }),
        version({ id: 'v3', version_number: 3, is_rolled_back: true }),
      ],
    });
    await waitFor(() => expect(kpButton()).toBeEnabled());
    fireEvent.click(kpButton());
    await waitFor(() => expect(kpApi.previewKpApply).toHaveBeenCalledWith('card-1', 'v2'));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});

// --- Окно предпросмотра ---------------------------------------------------------

function renderDialog(data: KpApplyPreview) {
  vi.mocked(kpApi.previewKpApply).mockResolvedValue(data);
  const onApplied = vi.fn();
  const onClose = vi.fn();
  render(<KpApplyDialog cardId="card-1" versionId="v2" onClose={onClose} onApplied={onApplied} />);
  return { onApplied, onClose };
}

const applyButton = () => screen.getByRole('button', { name: /^Применить/ });

describe('окно «Цены из КП»', () => {
  it('показывает было → стало, КП, «Не найдено» и «включают материалы: N»', async () => {
    renderDialog(preview({
      rows: [
        row({}),
        row({
          row_id: 'r2', name: 'Монтаж', type: 'work', field: 'price_work', old_price: null,
          new_price: 1200, supplier: 'СтройМонтаж', includes_materials: true, offers_count: 1,
        }),
      ],
      not_found: [item({ item_id: 'i5', name: 'Гвозди 100 мм' })],
      includes_materials_count: 1,
    }));

    const rows = await screen.findByTestId('kp-apply-rows');
    const first = within(rows).getByTestId('kp-apply-row-r1');
    expect(first).toHaveTextContent('Кирпич');
    expect(first).toHaveTextContent('25');
    expect(first).toHaveTextContent('21,5');
    expect(first).toHaveTextContent('ООО Кирпич');
    expect(first).toHaveTextContent('10.09.2026');
    expect(within(rows).getByTestId('kp-apply-row-r2')).toHaveTextContent('включает материалы');
    expect(screen.getByTestId('kp-apply-not-found')).toHaveTextContent('Гвозди 100 мм');
    expect(screen.getByTestId('kp-apply-includes-materials')).toHaveTextContent('включают материалы: 1');
    expect(applyButton()).toBeEnabled();
  });

  it('«Применить» — с rev и хэшем предпросмотра, выбор по «Неоднозначно», переход на новую версию', async () => {
    vi.mocked(kpApi.applyKpPrices).mockResolvedValue({
      version_id: 'v9', version_number: 3, source_version_id: 'v2', applied_rows: 2,
      changes_count: 2, request_ids: ['q1', 'q2'],
    });
    const { onApplied } = renderDialog(preview({
      rows: [row({})],
      ambiguous: [
        item({
          item_id: 'i9',
          candidates: [
            { row_id: 'r7', name: 'Монтаж перегородки', unit: 'м2', sheet: 'Корпус 1', source_no: null, qty: 10, old_price: 900, new_price: 800 },
            { row_id: 'r8', name: 'Монтаж перегородок', unit: 'м2', sheet: 'Корпус 2', source_no: null, qty: 5, old_price: 950, new_price: 800 },
          ],
        }),
        item({ item_id: 'i10', name: 'Окраска', candidates: [
          { row_id: 'r11', name: 'Окраска', unit: 'м2', sheet: 'А', source_no: null, qty: 1, old_price: 1, new_price: 2 },
        ] }),
      ],
    }));

    const ambiguous = await screen.findByTestId('kp-apply-ambiguous');
    fireEvent.click(within(ambiguous).getByLabelText(/Корпус 2/));
    fireEvent.click(applyButton());

    await waitFor(() => expect(kpApi.applyKpPrices).toHaveBeenCalledWith({
      card_id: 'card-1', version_id: 'v2', client_rev: 7, preview_hash: 'hash-1',
      choices: { i9: 'r8', i10: null },
    }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(
      expect.objectContaining({ version_id: 'v9', applied_rows: 2 }),
    ));
  });

  it('409 — понятное сообщение, окно остаётся, на новую версию не переходим', async () => {
    vi.mocked(kpApi.applyKpPrices).mockRejectedValue({
      response: { status: 409, data: { detail: 'Версию изменили' } },
    });
    const { onApplied, onClose } = renderDialog(preview({ rows: [row({})] }));
    await screen.findByTestId('kp-apply-rows');
    fireEvent.click(applyButton());

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/коллега/i);
    expect(alert).toHaveTextContent(/ничего не записано/i);
    expect(onApplied).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /Обновить предпросмотр/ })).toBeInTheDocument();
  });

  it('применять нечего — «Применить» неактивна с причиной', async () => {
    renderDialog(preview({ not_found: [item({})], no_price_count: 2 }));
    expect(await screen.findByTestId('kp-apply-nothing')).toBeInTheDocument();
    expect(applyButton()).toBeDisabled();
  });
});
