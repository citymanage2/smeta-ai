/**
 * Пометка «цена из КП» действует, только пока цена строки равна цене, которую
 * поставило КП (`kp_ref.field` / `kp_ref.price`). Правка цены снимает и
 * подсветку, и подсказку, и заливку в файле. Пометка без поля и цены —
 * недействующая. Свёрнутая группа пометку не наследует.
 */
import { describe, expect, it } from 'vitest';

import {
  activeKpRef, estimateAdapter, kpRowHint,
} from '../components/editor/adapters/estimateAdapter';
import { CollapseFields, GridRow } from '../components/editor/adapters/types';
import { buildCollapsedRows } from '../components/editor/collapse';
import { rowsFromEditor } from '../components/editor/exportBuilder';

const REF = {
  request_id: 'r1', offer_id: 'o1', supplier: 'ООО Кабель', offers_count: 2,
  includes_materials: false, field: 'price_work', price: 100,
};
const COLUMNS = [{ key: 'name', label: 'Наименование', numeric: false }];
const COEF = { work: 1.2, material: 1, scope: 'all' };

function stored(over: Record<string, unknown> = {}) {
  return { id: 'x', type: 'work', name: 'Монтаж кабеля', unit: 'м', qty: 10, price_work: 100, kp_ref: REF, ...over };
}

function classes(row: GridRow, coefficient?: unknown): string[] {
  return (estimateAdapter.rowClass?.(row, { coefficient }) ?? '').split(' ');
}

describe('действующая пометка «цена из КП»', () => {
  it('цена равна цене КП — класс и подсказка есть', () => {
    const [grid] = estimateAdapter.toGrid([stored()]);
    expect(classes(grid)).toContain('de-row-kp');
    expect(kpRowHint(grid)).toContain('ООО Кабель');
  });

  it('после правки цены класс de-row-kp и подсказка пропадают', () => {
    const [grid] = estimateAdapter.toGrid([stored()]);
    const edited = estimateAdapter.recalc({ ...grid, price_work: 130 }, 'price_work', []);
    expect(classes(edited)).not.toContain('de-row-kp');
    expect(estimateAdapter.rowHint?.(edited)).toBeNull();
  });

  it('копеечная разница в пределах 0,005 пометку не снимает, 0,01 — снимает', () => {
    expect(activeKpRef({ __key: 'a', price_work: 100.004, kp_ref: REF })).not.toBeNull();
    expect(activeKpRef({ __key: 'a', price_work: 100.01, kp_ref: REF })).toBeNull();
  });

  it('с коэффициентом ×1,2 сравнивается исходная цена, а не показанная', () => {
    const [grid] = estimateAdapter.toGrid([stored()], { coefficient: COEF });
    expect(grid.price_work).toBe(120);
    expect(classes(grid, COEF)).toContain('de-row-kp');
    expect(estimateAdapter.rowHint?.(grid, { coefficient: COEF })).toContain('ООО Кабель');
    // Человек поставил 130 на экране (исходная 108,33) — пометка снята.
    const edited = { ...grid, price_work: 130 };
    expect(classes(edited, COEF)).not.toContain('de-row-kp');
    expect(estimateAdapter.rowHint?.(edited, { coefficient: COEF })).toBeNull();
    // Ввёл ровно 120 = 100 × 1,2 — цена та же, пометка действует.
    expect(activeKpRef({ ...grid, price_work: 120 }, COEF)).not.toBeNull();
  });

  it('правка другой цены пометку не снимает', () => {
    const [grid] = estimateAdapter.toGrid([stored({ price_material: 5 })]);
    expect(activeKpRef({ ...grid, price_material: 7 })).not.toBeNull();
  });

  it('kp_ref без field или price — недействующий', () => {
    const noField = { ...REF, field: undefined };
    const noPrice = { ...REF, price: undefined };
    const badField = { ...REF, field: 'qty' };
    for (const ref of [noField, noPrice, badField]) {
      const [grid] = estimateAdapter.toGrid([stored({ kp_ref: ref })]);
      expect(classes(grid)).not.toContain('de-row-kp');
      expect(kpRowHint(grid)).toBeNull();
    }
  });

  it('выгрузка: недействующая пометка в __kp_ref не уходит', () => {
    const grid = estimateAdapter.toGrid([
      stored({ id: 'a' }),
      stored({ id: 'b', price_work: 150 }),
      stored({ id: 'c', kp_ref: { ...REF, price: undefined } }),
    ]);
    const exported = rowsFromEditor(grid, COLUMNS, () => 'work');
    expect(exported[0].__kp_ref).toEqual(REF);
    expect('__kp_ref' in exported[1]).toBe(false);
    expect('__kp_ref' in exported[2]).toBe(false);
  });

  it('выгрузка с коэффициентом: цена на экране с коэффициентом, пометка действует', () => {
    const grid = estimateAdapter.toGrid([stored()], { coefficient: COEF });
    expect(rowsFromEditor(grid, COLUMNS, () => 'work', undefined, COEF)[0].__kp_ref).toEqual(REF);
    const edited = [{ ...grid[0], price_work: 999 }];
    expect('__kp_ref' in rowsFromEditor(edited, COLUMNS, () => 'work', undefined, COEF)[0]).toBe(false);
  });
});

describe('свёртка и kp_ref', () => {
  it('группа не получает kp_ref первой строки, даже когда пометки разные', () => {
    const fields = estimateAdapter.collapseFields!([]) as CollapseFields;
    const grid = estimateAdapter.toGrid([
      stored({ id: 'a', kp_ref: { ...REF, supplier: 'ООО Первый' } }),
      stored({ id: 'b', kp_ref: { ...REF, supplier: 'ООО Второй' } }),
    ]);
    const collapsed = buildCollapsedRows(grid, fields, (row) => estimateAdapter.rowKind(row), new Set());
    expect(collapsed).toHaveLength(1);
    expect('kp_ref' in collapsed[0]).toBe(false);
    expect(classes(collapsed[0])).not.toContain('de-row-kp');
  });
});
