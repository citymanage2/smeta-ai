/**
 * Работа с прайсом из редактора: «В прайс» и «Из прайса».
 *
 * Фаза 10 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * Прайс общий на всех и участвует в расчёте будущих смет, поэтому здесь важно
 * не только «кнопка нажимается», но и что именно уходит на сервер: тип позиции,
 * её цена и единица измерения. Вставка из прайса встаёт после текущей строки —
 * решение пользователя 7.1.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/documents', async () => {
  const actual = await vi.importActual<typeof import('../api/documents')>('../api/documents');
  return { ...actual, addToPriceList: vi.fn() };
});

vi.mock('../api/catalog', () => ({
  matchPreview: vi.fn(),
  getCatalog: vi.fn(),
}));

import * as documentsApi from '../api/documents';
import * as catalogApi from '../api/catalog';
import AddToPriceList from '../components/editor/actions/AddToPriceList';
import AddFromPriceList from '../components/editor/actions/AddFromPriceList';
import { buildPriceRows, insertRowsAfter } from '../components/editor/actions/priceInsert';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { GridRow } from '../components/editor/adapters/types';

const REF = { cardId: 'card-1', kind: 'estimate' as const };

const ROWS: GridRow[] = [
  { __key: 'r1', type: 'Работа', name: 'Кладка стен', unit: 'м3', qty: 4,
    price_work: 1000, price_material: null },
  { __key: 'r2', type: 'Материал', name: 'Кирпич', unit: 'шт', qty: 400,
    price_work: null, price_material: 25 },
  { __key: 'r3', type: 'Раздел', name: 'Отделка', unit: null, qty: null,
    price_work: null, price_material: null },
];

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Вставка позиций прайса в документ
// ---------------------------------------------------------------------------

describe('вставка позиций из прайса', () => {
  it('встаёт сразу после текущей строки', () => {
    const inserted = buildPriceRows(
      [{ kind: 'work', name: 'Штукатурка', unit: 'м2', price: 500 }],
      estimateAdapter, [], 'seed',
    );

    const result = insertRowsAfter(ROWS, 'r1', inserted);

    expect(result.map((r) => r.name)).toEqual([
      'Кладка стен', 'Штукатурка', 'Кирпич', 'Отделка',
    ]);
  });

  it('несколько позиций встают в выбранном порядке', () => {
    const inserted = buildPriceRows([
      { kind: 'work', name: 'Первая', unit: 'м2', price: 100 },
      { kind: 'material', name: 'Вторая', unit: 'шт', price: 200 },
    ], estimateAdapter, [], 'seed');

    const result = insertRowsAfter(ROWS, 'r1', inserted);

    expect(result.map((r) => r.name)).toEqual([
      'Кладка стен', 'Первая', 'Вторая', 'Кирпич', 'Отделка',
    ]);
  });

  it('без текущей строки встаёт в конец', () => {
    const inserted = buildPriceRows(
      [{ kind: 'work', name: 'Штукатурка', unit: 'м2', price: 500 }],
      estimateAdapter, [], 'seed',
    );

    const result = insertRowsAfter(ROWS, null, inserted);

    expect(result[result.length - 1].name).toBe('Штукатурка');
  });

  it('цена работы попадает в цену работ, цена материала — в цену материалов', () => {
    const rows = buildPriceRows([
      { kind: 'work', name: 'Штукатурка', unit: 'м2', price: 500 },
      { kind: 'material', name: 'Смесь', unit: 'кг', price: 30 },
    ], estimateAdapter, [], 'seed');

    expect(rows[0]).toMatchObject({
      type: 'Работа', name: 'Штукатурка', unit: 'м2', price_work: 500,
    });
    expect(rows[0].price_material).toBeFalsy();
    expect(rows[1]).toMatchObject({
      type: 'Материал', name: 'Смесь', unit: 'кг', price_material: 30,
    });
    expect(rows[1].price_work).toBeFalsy();
  });

  it('при действующем коэффициенте цена прайса едет базовой, а показывается умноженной', () => {
    const rows = buildPriceRows(
      [{ kind: 'work', name: 'Штукатурка', unit: 'м2', price: 1000 }],
      estimateAdapter, [], 'seed',
      { work: 1.05, material: 1, scope: 'all' },
    );

    // Иначе снятие коэффициента изменило бы цену, которую человек не трогал.
    expect(rows[0].__base_price_work).toBe(1000);
    expect(rows[0].price_work).toBe(1050);
  });

  it('у вставленных строк разные ключи', () => {
    const rows = buildPriceRows([
      { kind: 'work', name: 'A', unit: 'м2', price: 1 },
      { kind: 'work', name: 'Б', unit: 'м2', price: 2 },
    ], estimateAdapter, [], 'seed');

    expect(rows[0].__key).not.toBe(rows[1].__key);
  });
});

// ---------------------------------------------------------------------------
// «В прайс»
// ---------------------------------------------------------------------------

function renderAddTo(selected: string[], onNotice = vi.fn()) {
  render(
    <AddToPriceList
      documentRef={REF}
      rows={ROWS}
      selectedKeys={new Set(selected)}
      rowKind={estimateAdapter.rowKind}
      onNotice={onNotice}
    />,
  );
  return onNotice;
}

describe('«В прайс»', () => {
  it('без выделения кнопка недоступна', () => {
    renderAddTo([]);

    expect(screen.getByRole('button', { name: /в прайс/i })).toBeDisabled();
  });

  it('отправляет выделенные позиции одним пакетом', async () => {
    vi.mocked(documentsApi.addToPriceList).mockResolvedValue({
      added: 2, updated: 0, skipped: 0, skipped_reasons: {},
    });
    renderAddTo(['r1', 'r2']);

    fireEvent.click(screen.getByRole('button', { name: /в прайс/i }));

    await waitFor(() => expect(documentsApi.addToPriceList).toHaveBeenCalledTimes(1));
    expect(documentsApi.addToPriceList).toHaveBeenCalledWith(REF, [
      { kind: 'work', name: 'Кладка стен', unit: 'м3', price: 1000 },
      { kind: 'material', name: 'Кирпич', unit: 'шт', price: 25 },
    ]);
  });

  it('разделы в прайс не отправляются', async () => {
    vi.mocked(documentsApi.addToPriceList).mockResolvedValue({
      added: 1, updated: 0, skipped: 0, skipped_reasons: {},
    });
    renderAddTo(['r1', 'r3']);

    fireEvent.click(screen.getByRole('button', { name: /в прайс/i }));

    await waitFor(() => expect(documentsApi.addToPriceList).toHaveBeenCalled());
    const sent = vi.mocked(documentsApi.addToPriceList).mock.calls[0][1];
    expect(sent).toHaveLength(1);
    expect(sent[0].name).toBe('Кладка стен');
  });

  it('показывает сводку «добавлено / обновлено / пропущено»', async () => {
    vi.mocked(documentsApi.addToPriceList).mockResolvedValue({
      added: 1, updated: 2, skipped: 3, skipped_reasons: { 'без цены': 3 },
    });
    const onNotice = renderAddTo(['r1', 'r2']);

    fireEvent.click(screen.getByRole('button', { name: /в прайс/i }));

    await waitFor(() => expect(onNotice).toHaveBeenCalled());
    const message = onNotice.mock.calls[0][0] as string;
    expect(message).toContain('1');
    expect(message).toContain('2');
    expect(message).toContain('3');
  });

  it('ошибка сервера объясняется человеку', async () => {
    vi.mocked(documentsApi.addToPriceList).mockRejectedValue(new Error('нет сети'));
    const onNotice = renderAddTo(['r1']);

    fireEvent.click(screen.getByRole('button', { name: /в прайс/i }));

    await waitFor(() => expect(onNotice).toHaveBeenCalled());
    expect(onNotice.mock.calls[0][0]).toMatch(/не удалось/i);
  });
});

// ---------------------------------------------------------------------------
// «Из прайса»
// ---------------------------------------------------------------------------

function renderAddFrom(onInsert = vi.fn(), currentName = 'Кладка стен') {
  render(
    <AddFromPriceList
      currentRowName={currentName}
      onInsert={onInsert}
    />,
  );
  return onInsert;
}

const WORK_MATCH = {
  threshold: 0.7, catalog_size: 100, vectors_ready: true, matched: true,
  candidates: [
    { name: 'Кладка стен из кирпича', score: 0.91, unit: 'м3', price: 1200, would_match: true },
    { name: 'Кладка перегородок', score: 0.72, unit: 'м2', price: 800, would_match: true },
  ],
  hint: '',
};

const EMPTY_MATCH = {
  threshold: 0.7, catalog_size: 100, vectors_ready: true, matched: false,
  candidates: [], hint: '',
};

describe('«Из прайса»', () => {
  it('ищет по названию текущей строки и показывает найденное', async () => {
    vi.mocked(catalogApi.matchPreview).mockResolvedValue(WORK_MATCH);
    renderAddFrom();

    fireEvent.click(screen.getByRole('button', { name: /из прайса/i }));

    expect(await screen.findByText('Кладка стен из кирпича')).toBeInTheDocument();
    expect(catalogApi.matchPreview).toHaveBeenCalledWith('Кладка стен', 'work');
  });

  it('вставляет выбранные позиции в выбранном порядке', async () => {
    vi.mocked(catalogApi.matchPreview).mockResolvedValue(WORK_MATCH);
    const onInsert = renderAddFrom();

    fireEvent.click(screen.getByRole('button', { name: /из прайса/i }));
    fireEvent.click(await screen.findByLabelText('Кладка стен из кирпича'));
    fireEvent.click(screen.getByLabelText('Кладка перегородок'));
    fireEvent.click(screen.getByRole('button', { name: /вставить/i }));

    await waitFor(() => expect(onInsert).toHaveBeenCalledTimes(1));
    expect(onInsert.mock.calls[0][0]).toEqual([
      { kind: 'work', name: 'Кладка стен из кирпича', unit: 'м3', price: 1200 },
      { kind: 'work', name: 'Кладка перегородок', unit: 'м2', price: 800 },
    ]);
  });

  it('когда умный поиск ничего не нашёл, ищет по названию в каталоге', async () => {
    vi.mocked(catalogApi.matchPreview).mockResolvedValue(EMPTY_MATCH);
    vi.mocked(catalogApi.getCatalog).mockResolvedValue({
      items: [{
        id: 5, kind: 'work', name: 'Кладка блоков', unit: 'м3', price: 950,
        prices: null, updated_at: '2026-08-01T10:00:00Z',
      }],
      total: 1,
    });
    renderAddFrom();

    fireEvent.click(screen.getByRole('button', { name: /из прайса/i }));

    expect(await screen.findByText('Кладка блоков')).toBeInTheDocument();
  });

  it('переключение на материалы ищет среди материалов', async () => {
    vi.mocked(catalogApi.matchPreview).mockResolvedValue(EMPTY_MATCH);
    vi.mocked(catalogApi.getCatalog).mockResolvedValue({ items: [], total: 0 });
    renderAddFrom();

    fireEvent.click(screen.getByRole('button', { name: /из прайса/i }));
    await screen.findByRole('button', { name: /^материалы$/i });
    fireEvent.click(screen.getByRole('button', { name: /^материалы$/i }));

    await waitFor(() =>
      expect(catalogApi.matchPreview).toHaveBeenLastCalledWith('Кладка стен', 'material'));
  });

  it('ничего не выбрано — вставлять нечего', async () => {
    vi.mocked(catalogApi.matchPreview).mockResolvedValue(WORK_MATCH);
    renderAddFrom();

    fireEvent.click(screen.getByRole('button', { name: /из прайса/i }));
    await screen.findByText('Кладка стен из кирпича');

    expect(screen.getByRole('button', { name: /вставить/i })).toBeDisabled();
  });
});
