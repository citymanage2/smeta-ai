/**
 * Свёртка одинаковых позиций в редакторе
 * (план `plans/2026-08-13-svertka-odinakovyh-pozicij.md`).
 *
 * Главное правило: свёртка — уровень показа. В сторе всегда лежат настоящие
 * строки документа, поэтому «Применить» записывает их все, а правка свёрнутой
 * строки превращается в правку каждой её позиции по отдельности.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
import { withGridLayout } from './gridLayout';
import { cellIn, getGridRow, numberNextTo, parseScreenNumber } from './screenQueries';

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

// Штукатурка встречается дважды, в разных разделах: 80 + 40,5 = 120,5 м2.
// Наименования отличаются регистром и лишним пробелом — как в чужих сметах.
const ROWS = [
  { id: 'r1', type: 'work', name: 'Штукатурка стен', unit: 'м2', qty: 80,
    price_work: 450, price_material: null, sheet: 'Раздел 1' },
  { id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт', qty: 500,
    price_work: null, price_material: 25, sheet: 'Раздел 1' },
  { id: 'r3', type: 'work', name: 'штукатурка  стен', unit: 'м2', qty: 40.5,
    price_work: 450, price_material: null, sheet: 'Раздел 2' },
  { id: 'r4', type: 'work', name: 'Кладка стен', unit: 'м3', qty: 5,
    price_work: 1000, price_material: null, sheet: 'Раздел 2' },
];

function mockRows(rows: unknown[]) {
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows, draft_rows: null,
  });
}

// В jsdom таблица без подмены размеров не рисует ни одной ячейки.
withGridLayout();

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
  vi.mocked(api.applyDocument).mockResolvedValue({
    version_id: 'v1', rev: 1, rows_count: 4, changes_count: 0,
  });
  mockRows(ROWS);
});

const collapseButton = () => screen.getByRole('button', { name: /Свернуть дубли/i });
const grid = () => screen.getByTestId('document-editor-grid');
const gridText = () => document.querySelector('.de-grid')?.textContent ?? '';
const applyButton = () => screen.getByRole('button', { name: 'Применить' });
/** Поле ввода внутри таблицы — открытый редактор ячейки (поиск в тулбаре не в счёт). */
const cellInput = () => within(screen.getByRole('grid')).queryByRole('textbox');

async function openCollapsed(rows: unknown[] = ROWS, expectedCount = '3') {
  mockRows(rows);
  render(<DocumentEditor cardId="card-1" kind="estimate" />);
  await screen.findByTestId('document-editor-grid');
  fireEvent.click(collapseButton());
  await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', expectedCount));
}

describe('свёрнутый режим', () => {
  it('группа раскрывается и показывает свои позиции', async () => {
    await openCollapsed();

    fireEvent.click(screen.getByTitle('Показать позиции группы'));
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '5'));

    // Позиции внутри группы — настоящие строки со своими объёмами.
    expect(gridText()).toContain('40,5');
  });

  it('вкладки листов отключаются, итог считается по всему документу', async () => {
    await openCollapsed();

    expect(screen.queryByRole('tablist', { name: /Листы документа/i })).toBeNull();
    // Оба раздела: 59 225 работ + 1 776,75 накладных + 12 500 материалов +
    // 375 транспортных. Только «Раздел 1» дал бы 49 955.
    expect(numberNextTo(/^ИТОГО/)).toBe(73876.75);
  });

  it('режим уходит в ссылку и приходит из неё', async () => {
    const onStateChange = vi.fn();
    render(<DocumentEditor cardId="card-1" kind="estimate" onStateChange={onStateChange} />);
    await screen.findByTestId('document-editor-grid');

    fireEvent.click(collapseButton());
    await waitFor(() => expect(onStateChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ collapsed: true }),
    ));
  });

  it('ссылка со свёрткой открывает таблицу уже свёрнутой', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" initialCollapsed />);
    await screen.findByTestId('document-editor-grid');

    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '3'));
  });

  it('без колонки наименования свернуть нечем — кнопка недоступна', async () => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
      kind: 'list', row_format: 'generic', file_slot: 'list',
    }));
    mockRows([
      { row_id: 'g1', cells: { 'Позиция': 'Штукатурка', 'Кол-во': 10 } },
      { row_id: 'g2', cells: { 'Позиция': 'Штукатурка', 'Кол-во': 5 } },
    ]);
    render(<DocumentEditor cardId="card-1" kind="list" />);
    await screen.findByTestId('document-editor-grid');

    expect(collapseButton()).toBeDisabled();
  });
});

describe('правка свёрнутой строки', () => {
  /** `shown` — как ячейка выглядит на экране, `stored` — что лежит в строке. */
  async function editCell(shown: string, stored: string, next: string) {
    const cell = [...document.querySelectorAll('.rdg-cell')]
      .find((node) => node.textContent === shown);
    expect(cell, `ячейка «${shown}» не найдена`).toBeTruthy();
    fireEvent.doubleClick(cell!);
    const input = await screen.findByDisplayValue(stored);
    fireEvent.change(input, { target: { value: next } });
    // Enter, а не blur: React слушает focusout, и события blur из jsdom
    // редактор ячейки не увидит.
    fireEvent.keyDown(input, { key: 'Enter' });
  }

  it('меняет цену во всех позициях группы, пересчитывая каждую по её объёму', async () => {
    await openCollapsed();

    // Цена 450,00 в свёрнутом виде одна на всю таблицу — это ячейка группы.
    await editCell('450,00', '450', '500');

    fireEvent.click(await screen.findByRole('button', { name: /применить/i }));
    await waitFor(() => expect(api.applyDocument).toHaveBeenCalled());

    const sent = vi.mocked(api.applyDocument).mock.calls[0][3] as Array<Record<string, unknown>>;
    const byId = new Map(sent.map((row) => [row.id, row]));
    // Обе позиции группы получили новую цену…
    expect(byId.get('r1')!.price_work).toBe(500);
    expect(byId.get('r3')!.price_work).toBe(500);
    // …и сохранили свои объёмы: общий объём в позицию не переезжает.
    expect(byId.get('r1')!.qty).toBe(80);
    expect(byId.get('r3')!.qty).toBe(40.5);
    // Чужая работа не тронута.
    expect(byId.get('r4')!.price_work).toBe(1000);
    // Строк по-прежнему четыре: свёртка документ не склеивает.
    expect(sent).toHaveLength(4);
  });

  it('общий объём не редактируется', async () => {
    await openCollapsed();
    const group = getGridRow('Штукатурка стен');
    expect(parseScreenNumber(cellIn(group, 'Кол-во').textContent)).toBe(120.5);

    // Объём свёрнутой строки — результат сложения: поля ввода не появляется.
    fireEvent.doubleClick(cellIn(group, 'Кол-во'));
    expect(cellInput()).toBeNull();

    // А цена той же строки правится — двойной щелчок в таблице работает.
    fireEvent.doubleClick(cellIn(getGridRow('Штукатурка стен'), 'Цена работ'));
    expect(await screen.findByDisplayValue('450')).toBe(cellInput());
  });
});

describe('операции, опасные в свёрнутом виде', () => {
  it('вставка из буфера отклоняется: строки не меняются, применять нечего', async () => {
    await openCollapsed();

    // Курсор в ячейке объёма — без него вставке некуда целиться.
    fireEvent.click(cellIn(getGridRow('Кирпич'), 'Кол-во'));
    fireEvent.paste(grid(), { clipboardData: { getData: () => '1\t2' } });

    // Объём остался прежним, документ не тронут.
    expect(parseScreenNumber(cellIn(getGridRow('Кирпич'), 'Кол-во').textContent)).toBe(500);
    expect(applyButton()).toBeDisabled();
  });

  it('удаление отмеченной группы уносит обе её позиции', async () => {
    await openCollapsed();

    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    await screen.findByText('Выбрано: 2');
    fireEvent.click(screen.getByRole('button', { name: /удалить выбранные строки/i }));

    fireEvent.click(await screen.findByRole('button', { name: /применить/i }));
    await waitFor(() => expect(api.applyDocument).toHaveBeenCalled());

    const sent = vi.mocked(api.applyDocument).mock.calls[0][3] as Array<Record<string, unknown>>;
    expect(sent.map((row) => row.id)).toEqual(['r2', 'r4']);
  });
});
