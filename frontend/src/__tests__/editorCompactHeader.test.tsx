/**
 * Шапка редактора: компактная и объясняющая себя.
 *
 * План `plans/2026-09-01-kompaktnaya-shapka-redaktora.md`.
 *
 * Два правила, которые легко потерять при следующей правке разметки:
 *
 * 1. Действия над ценами стоят одной полосой (`.de-actions-bar`), а не тремя
 *    строками. Иначе шапка снова займёт полэкрана и таблица уедет под сгиб.
 * 2. У каждой кнопки шапки есть описание при наведении. Проверяется не «есть
 *    хоть какая-то подсказка», а именно её наличие у **каждой** кнопки: одна
 *    забытая кнопка — и человек снова гадает, что она делает и почему серая.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const STORED = [
  { id: 'r1', lineage_id: 'r1', type: 'work', name: 'Кладка', unit: 'м2',
    qty: 4, price_work: 1000, price_material: null },
  { id: 'r2', lineage_id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт',
    qty: 10, price_work: null, price_material: 500 },
];

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

function mockDocument(metaOverrides: Partial<api.DocumentMeta> = {}) {
  vi.mocked(api.getDocumentMeta).mockResolvedValue({
    card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
    task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1', versions: [], coefficient: null,
    has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3 },
    ...metaOverrides,
  } as api.DocumentMeta);
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: STORED, draft_rows: null,
  });
}

/** Описание при наведении: своя подсказка либо системный `title`. */
function hoverText(button: HTMLElement): string {
  const hint = button.closest('.de-hint')?.getAttribute('data-hint') ?? '';
  return hint || button.getAttribute('title') || '';
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
});

describe('компактная шапка редактора', () => {
  it('коэффициент, цены и прайс стоят одной полосой', async () => {
    mockDocument();
    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    const bars = container.querySelectorAll('.de-actions-bar');
    expect(bars).toHaveLength(1);
    // Все три группы — внутри одной полосы, а не своими строками.
    expect(bars[0].querySelector('.de-coefficient')).not.toBeNull();
    expect(bars[0].querySelectorAll('.de-price-actions')).toHaveLength(2);
  });

  it('вкладки «Все / Работы / Материалы» стоят в строке поиска', async () => {
    mockDocument();
    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    const row = container.querySelector('.de-toolbar-row');
    expect(row?.querySelector('.de-tabs')).not.toBeNull();
    expect(row?.querySelector('.de-search')).not.toBeNull();
  });

  it('итог листа и итог документа — в одной строке со слагаемыми', async () => {
    mockDocument();
    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    const totals = container.querySelector('.de-totals');
    expect(totals?.querySelector('.de-totals-grid')).not.toBeNull();
    // Числа при этом остаются прежними: сжимали разметку, а не расчёт.
    expect(totals?.textContent).toContain('Сумма по работам:');
    expect(totals?.textContent).toContain('ИТОГО:');
  });

  it('на странице документа редактор не рисует вторую шапку с названием', async () => {
    mockDocument();
    const { container } = render(
      <DocumentEditor cardId="card-1" kind="estimate" title="Смета — файл.xlsx" showHead={false} />,
    );
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    expect(container.querySelector('.de-head')).toBeNull();
    // Без явного запрета шапка на месте: во вкладках сводной она нужна.
    const { container: withHead } = render(
      <DocumentEditor cardId="card-2" kind="estimate" title="Смета — файл.xlsx" />,
    );
    await waitFor(() => expect(withHead.querySelector('.de-head')).not.toBeNull());
  });

  it('у каждой кнопки шапки есть описание при наведении', async () => {
    mockDocument();
    const { container } = render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    const buttons = [
      ...container.querySelectorAll<HTMLElement>('.de-toolbar button'),
      ...container.querySelectorAll<HTMLElement>('.de-actions-bar button'),
    ];
    expect(buttons.length).toBeGreaterThan(8);

    const silent = buttons.filter((b) => hoverText(b).length < 10);
    expect(silent.map((b) => b.textContent)).toEqual([]);
  });

  it('выключенная кнопка объясняет, почему она недоступна', async () => {
    mockDocument();
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    // Ни одна строка не отмечена галочкой — «В прайс» и «Найти аналоги» серые.
    // Системный `title` на выключенной кнопке браузер не показывает, поэтому
    // подсказка висит на обёртке и объясняет, что нужно сделать.
    const toPrice = screen.getByRole('button', { name: /В прайс/ });
    expect(toPrice).toBeDisabled();
    expect(hoverText(toPrice)).toContain('отметьте');

    const apply = screen.getByRole('button', { name: /Применить/ });
    expect(apply).toBeDisabled();
    expect(hoverText(apply)).toContain('Нет непринятых правок');
  });
});
