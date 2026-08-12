/**
 * Свёртка одинаковых позиций в редакторе
 * (план `plans/2026-08-13-svertka-odinakovyh-pozicij.md`).
 *
 * Главное правило: свёртка — уровень показа. В сторе всегда лежат настоящие
 * строки документа, поэтому «Применить» записывает их все, а правка свёрнутой
 * строки превращается в правку каждой её позиции по отдельности.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
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

// В русской локали разряды отбиваются неразрывным пробелом: на экране это
// пробел, но сравнивать надо с тем символом, который реально печатается.
const NBSP = String.fromCharCode(160);

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

// В jsdom нет ни ResizeObserver, ни размеров: react-data-grid считает таблицу
// нулевой и не рисует ячеек вовсе. Тот же приём, что в `editorNumberFormat`.
let restoreWidth: PropertyDescriptor | undefined;
let originalRect: typeof HTMLElement.prototype.getBoundingClientRect;

beforeAll(() => {
  restoreWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true, value: 2000,
  });
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

async function openCollapsed(rows: unknown[] = ROWS, expectedCount = '3') {
  mockRows(rows);
  render(<DocumentEditor cardId="card-1" kind="estimate" />);
  await screen.findByTestId('document-editor-grid');
  fireEvent.click(collapseButton());
  await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', expectedCount));
}

describe('свёрнутый режим', () => {
  it('собирает одинаковые позиции в одну строку с общим объёмом', async () => {
    await openCollapsed();

    // Четыре строки документа стали тремя: две штукатурки — одна строка.
    const text = gridText();
    expect(text).toContain('120,5');
    // Стоимость складывается по позициям: 36 000 + 18 225.
    expect(text).toContain(`54${NBSP}225,00`);
    // Позиции по отдельности с экрана ушли.
    expect(text).not.toContain('40,5');
  });

  it('группа раскрывается и показывает свои позиции', async () => {
    await openCollapsed();

    fireEvent.click(screen.getByTitle('Показать позиции группы'));
    await waitFor(() => expect(grid()).toHaveAttribute('data-row-count', '5'));

    // Позиции внутри группы — настоящие строки со своими объёмами.
    expect(gridText()).toContain('40,5');
  });

  it('одиночная позиция группой не становится', async () => {
    await openCollapsed();
    // «Кладка стен» и «Кирпич» — по одной на документ, сворачивать их нечего.
    expect(document.querySelectorAll('.de-group-toggle')).toHaveLength(1);
  });

  it('число свёрнутых групп видно на кнопке', async () => {
    await openCollapsed();
    expect(collapseButton().textContent).toContain('1');
  });

  it('расхождение цен внутри группы показывается словом, а не числом', async () => {
    await openCollapsed([ROWS[0], { ...ROWS[2], price_work: 500 }], '1');

    const text = gridText();
    expect(text).toContain('разные');
    // Стоимость всё равно честная: 80 × 450 + 40,5 × 500 = 56 250.
    expect(text).toContain(`56${NBSP}250,00`);
    // Ни одна из двух цен не выдана за цену всей группы.
    expect(text).not.toContain('450,00');
    expect(text).not.toContain('500,00');
  });

  it('вкладки листов отключаются, итог считается по всему документу', async () => {
    await openCollapsed();

    expect(screen.queryByRole('tablist', { name: /Листы документа/i })).toBeNull();
    // 59 225 работ + 1 776,75 накладных + 12 500 материалов + 375 транспортных.
    const totals = document.querySelector('.de-totals')?.textContent ?? '';
    expect(totals).toContain('ИТОГО:');
    expect(totals).toContain(`73${NBSP}876,75 ₽`);
    // Отдельного «ВСЕГО по документу» нет: итог и так по всему документу.
    expect(totals).not.toContain('ВСЕГО по документу');
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

    const cell = [...document.querySelectorAll('.rdg-cell')]
      .find((node) => node.textContent === '120,5');
    fireEvent.doubleClick(cell!);

    // Ячейка объёма у свёрнутой строки только для чтения: ввода не появляется.
    expect(document.querySelector('.de-cell-input')).toBeNull();
  });
});

describe('операции, опасные в свёрнутом виде', () => {
  it('отметка свёрнутой строки отмечает обе её позиции', async () => {
    await openCollapsed();

    // Первый чекбокс — «отметить всё» в шапке, второй — строка группы.
    fireEvent.click(screen.getAllByRole('checkbox')[1]);

    await screen.findByText('Выбрано: 2');
  });

  it('снятая отметка группы гасит и её позиции', async () => {
    await openCollapsed();

    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    await screen.findByText('Выбрано: 2');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);

    await waitFor(() => expect(screen.queryByText(/Выбрано:/)).toBeNull());
  });

  it('вставка из буфера отклоняется с подсказкой, а не молча', async () => {
    await openCollapsed();

    // Курсор в ячейке — без него вставке некуда целиться.
    const cell = [...document.querySelectorAll('.rdg-cell')]
      .find((node) => node.textContent === '120,5');
    fireEvent.click(cell!);
    fireEvent.paste(document.querySelector('.de-grid-wrap')!, {
      clipboardData: { getData: () => '1\t2' },
    });

    expect(await screen.findByText(/Вставка недоступна в свёрнутом режиме/)).toBeInTheDocument();
    // Документ не тронут.
    expect(useDocumentEditorStore.getState().isDirty).toBe(false);
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
