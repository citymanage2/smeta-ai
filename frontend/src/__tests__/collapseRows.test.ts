/**
 * Свёртка одинаковых позиций в общий объём
 * (план `plans/2026-08-13-svertka-odinakovyh-pozicij.md`).
 *
 * Главное правило: свёртка — уровень показа. Она не меняет ни одной строки
 * документа, а правка свёрнутой строки превращается в N обычных правок N строк.
 * Числа здесь точные: расхождение общего объёма с суммой позиций — это
 * неправильная сумма контракта на тендере.
 */
import { describe, expect, it } from 'vitest';

import {
  GROUP_PREFIX,
  buildCollapsedRows,
  collapseKey,
  groupInfoOf,
  applySelectionChange,
  isMixedField,
  selectionForGrid,
  spreadEdit,
} from '../components/editor/collapse';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { CollapseFields, GridRow } from '../components/editor/adapters/types';

const FIELDS = estimateAdapter.collapseFields!([]) as CollapseFields;
const kindOf = (row: GridRow) => estimateAdapter.rowKind(row);
const NOTHING = new Set<string>();

function row(over: Partial<GridRow> & { __key: string }): GridRow {
  return {
    type: 'Работа', name: 'Штукатурка стен', unit: 'м2', qty: 0,
    price_work: null, price_material: null, cost_work: 0, cost_material: 0,
    ...over,
  };
}

describe('ключ группы', () => {
  it('не зависит от регистра и лишних пробелов', () => {
    const left = collapseKey(row({ __key: 'a', name: 'Штукатурка стен' }), FIELDS, 'work');
    const right = collapseKey(row({ __key: 'b', name: '  штукатурка   стен ' }), FIELDS, 'work');
    expect(left).toBe(right);
  });

  it('различает работу и материал с одним наименованием', () => {
    const work = collapseKey(row({ __key: 'a' }), FIELDS, 'work');
    const material = collapseKey(row({ __key: 'b' }), FIELDS, 'material');
    expect(work).not.toBe(material);
  });

  it('различает единицы измерения — м2 и м3 не складываются', () => {
    const square = collapseKey(row({ __key: 'a', unit: 'м2' }), FIELDS, 'work');
    const cubic = collapseKey(row({ __key: 'b', unit: 'м3' }), FIELDS, 'work');
    expect(square).not.toBe(cubic);
  });

  it('не берёт разделы и строки без наименования', () => {
    expect(collapseKey(row({ __key: 'a', type: 'Раздел' }), FIELDS, 'section')).toBeNull();
    expect(collapseKey(row({ __key: 'b', name: '   ' }), FIELDS, 'work')).toBeNull();
  });
});

describe('свёрнутые строки', () => {
  // Три позиции одной работы в трёх разделах: 80 + 40,5 + 10 = 130,5 м2.
  const ROWS = [
    row({ __key: 'r1', qty: 80, price_work: 450, cost_work: 36000, sheet: 'Раздел 1' }),
    row({ __key: 'r2', name: 'Кладка стен', unit: 'м3', qty: 5, price_work: 1000, cost_work: 5000 }),
    row({ __key: 'r3', qty: 40.5, price_work: 450, cost_work: 18225, sheet: 'Раздел 2' }),
    row({ __key: 'r4', qty: 10, price_work: 450, cost_work: 4500, sheet: 'Раздел 3' }),
  ];

  it('складывает объём и стоимость, оставляя порядок документа', () => {
    const collapsed = buildCollapsedRows(ROWS, FIELDS, kindOf, NOTHING);

    expect(collapsed).toHaveLength(2);
    expect(collapsed[0].__key).toBe(`${GROUP_PREFIX}work|штукатурка стен|м2`);
    expect(collapsed[0].qty).toBe(130.5);
    expect(collapsed[0].cost_work).toBe(58725);
    expect(collapsed[0].price_work).toBe(450);
    // Одиночная позиция группой не становится — правится как обычная строка.
    expect(collapsed[1].__key).toBe('r2');
  });

  it('стоимость складывает по позициям, а не считает по общему объёму', () => {
    // Цены разошлись: 80 × 450 + 40,5 × 500 = 36 000 + 20 250 = 56 250.
    // «Общий объём × цена» дал бы 120,5 × 450 = 54 225 — расхождение с итогом.
    const mixed = [
      row({ __key: 'r1', qty: 80, price_work: 450, cost_work: 36000 }),
      row({ __key: 'r2', qty: 40.5, price_work: 500, cost_work: 20250 }),
    ];
    const [group] = buildCollapsedRows(mixed, FIELDS, kindOf, NOTHING);

    expect(group.cost_work).toBe(56250);
    expect(group.price_work).toBeNull();
    expect(isMixedField(group, 'price_work')).toBe(true);
  });

  it('раскрытая группа показывает свои позиции настоящими строками', () => {
    const expanded = new Set(['work|штукатурка стен|м2']);
    const collapsed = buildCollapsedRows(ROWS, FIELDS, kindOf, expanded);

    expect(collapsed.map((item) => item.__key)).toEqual([
      `${GROUP_PREFIX}work|штукатурка стен|м2`, 'r1', 'r3', 'r4', 'r2',
    ]);
    // Позиция внутри группы — та же строка документа, со своим объёмом.
    expect(collapsed[1].qty).toBe(80);
    expect(collapsed[2].qty).toBe(40.5);
  });

  it('служебные поля позиций свёрнутой строке не наследуются', () => {
    const [group] = buildCollapsedRows(ROWS, FIELDS, kindOf, NOTHING);
    // Лист исходного файла у позиций разный, а свёрнутая строка не строка
    // документа вовсе — сохраняться ей некуда.
    expect(Object.keys(group).filter((key) => key.startsWith('__')))
      .toEqual(['__key', '__group', '__mixed']);
  });

  it('не сворачивает разделы', () => {
    const withSection = [
      row({ __key: 's1', type: 'Раздел', name: 'Раздел 1' }),
      ...ROWS,
      row({ __key: 's2', type: 'Раздел', name: 'Раздел 1' }),
    ];
    const collapsed = buildCollapsedRows(withSection, FIELDS, kindOf, NOTHING);
    expect(collapsed.map((item) => item.__key)).toEqual([
      's1', `${GROUP_PREFIX}work|штукатурка стен|м2`, 'r2', 's2',
    ]);
  });

  it('пустой объём у всех позиций оставляет ячейку пустой, а не нулём', () => {
    const empty = [
      row({ __key: 'r1', qty: null, cost_work: null }),
      row({ __key: 'r2', qty: null, cost_work: null }),
    ];
    const [group] = buildCollapsedRows(empty, FIELDS, kindOf, NOTHING);
    expect(group.qty).toBeNull();
  });
});

describe('правка свёрнутой строки', () => {
  const ROWS = [
    row({ __key: 'r1', qty: 80, price_work: 450, cost_work: 36000 }),
    row({ __key: 'r2', qty: 40.5, price_work: 450, cost_work: 18225 }),
    row({ __key: 'r3', name: 'Кладка стен', qty: 5, price_work: 1000, cost_work: 5000 }),
  ];
  const recalc = (item: GridRow, key: string) => estimateAdapter.recalc(item, key, []);

  it('цена разъезжается по всем позициям, стоимость — по своему объёму', () => {
    const [group] = buildCollapsedRows(ROWS, FIELDS, kindOf, NOTHING);
    const edited = { ...group, price_work: 500 };
    const changes = spreadEdit(edited, 'price_work', ROWS, FIELDS, recalc);

    expect([...changes.keys()]).toEqual(['r1', 'r2']);
    expect(changes.get('r1')!.cost_work).toBe(40000);
    expect(changes.get('r2')!.cost_work).toBe(20250);
    // Чужая позиция не тронута.
    expect(changes.has('r3')).toBe(false);
  });

  it('переименование меняет все позиции — группа не распадается', () => {
    const [group] = buildCollapsedRows(ROWS, FIELDS, kindOf, NOTHING);
    const changes = spreadEdit(
      { ...group, name: 'Штукатурка стен улучшенная' }, 'name', ROWS, FIELDS, recalc,
    );
    expect(changes.get('r1')!.name).toBe('Штукатурка стен улучшенная');
    expect(changes.get('r2')!.name).toBe('Штукатурка стен улучшенная');
  });

  it('объём через свёрнутую строку не правится', () => {
    const [group] = buildCollapsedRows(ROWS, FIELDS, kindOf, NOTHING);
    const changes = spreadEdit({ ...group, qty: 200 }, 'qty', ROWS, FIELDS, recalc);
    expect(changes.size).toBe(0);
  });
});

describe('выделение', () => {
  const ROWS = [
    row({ __key: 'r1', qty: 80 }),
    row({ __key: 'r2', qty: 40.5 }),
    row({ __key: 'r3', name: 'Кладка стен', qty: 5 }),
  ];
  const displayed = buildCollapsedRows(ROWS, FIELDS, kindOf, NOTHING);
  const groupKey = `${GROUP_PREFIX}work|штукатурка стен|м2`;

  it('отметка группы отмечает все её позиции', () => {
    expect(applySelectionChange(new Set(), new Set(), new Set([groupKey]), displayed))
      .toEqual(new Set(['r1', 'r2']));
  });

  it('снятая отметка группы гасит её позиции, не трогая чужие', () => {
    const current = new Set(['r1', 'r2', 'r3']);
    expect(applySelectionChange(current, new Set([groupKey, 'r3']), new Set(['r3']), displayed))
      .toEqual(new Set(['r3']));
  });

  it('обычный ключ проходит как есть', () => {
    expect(applySelectionChange(new Set(), new Set(), new Set(['r3']), displayed))
      .toEqual(new Set(['r3']));
  });

  it('галочка группы горит, когда отмечены все её позиции', () => {
    expect(selectionForGrid(new Set(['r1', 'r2']), displayed).has(groupKey)).toBe(true);
    expect(selectionForGrid(new Set(['r1']), displayed).has(groupKey)).toBe(false);
  });
});

describe('плоские документы — перечень и полнота', () => {
  const COLUMNS = [
    { key: 'Тип', name: 'Тип', width: 80, editable: true, numeric: false },
    { key: 'Наименование', name: 'Наименование', width: 200, editable: true, numeric: false },
    { key: 'Ед. изм.', name: 'Ед. изм.', width: 80, editable: true, numeric: false },
    { key: 'Кол-во', name: 'Кол-во', width: 80, editable: true, numeric: true },
    { key: 'Цена работ', name: 'Цена работ', width: 90, editable: true, numeric: true },
    { key: 'Стоимость работ', name: 'Стоимость работ', width: 100, editable: false, numeric: true },
  ];

  it('колонки для свёртки берутся из шапки файла заказчика', () => {
    const fields = genericAdapter.collapseFields!(COLUMNS);
    expect(fields).toEqual({
      nameKey: 'Наименование',
      unitKey: 'Ед. изм.',
      sharedKeys: ['Наименование', 'Ед. изм.', 'Цена работ'],
      sumKeys: ['Кол-во', 'Стоимость работ'],
    });
  });

  it('без колонки наименования свернуть нечем', () => {
    const nameless = COLUMNS.filter((column) => column.key !== 'Наименование');
    expect(genericAdapter.collapseFields!(nameless)).toBeNull();
  });

  it('складывает объёмы строк перечня', () => {
    const fields = genericAdapter.collapseFields!(COLUMNS)!;
    const rows: GridRow[] = [
      { __key: 'g1', 'Тип': 'Работа', 'Наименование': 'Штукатурка стен', 'Ед. изм.': 'м2', 'Кол-во': 80 },
      { __key: 'g2', 'Тип': 'Работа', 'Наименование': 'штукатурка стен', 'Ед. изм.': 'м2', 'Кол-во': 40.5 },
    ];
    const [group] = buildCollapsedRows(rows, fields, (item) => genericAdapter.rowKind(item), NOTHING);
    expect(group['Кол-во']).toBe(120.5);
  });
});
