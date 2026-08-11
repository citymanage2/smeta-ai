import { describe, expect, it } from 'vitest';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';

/**
 * Номер позиции исходной сметы виден на стадии сметы — и в версиях
 * оптимизации, и в разделах сводной: у них тот же формат строки.
 * План: plans/2026-08-11-nomer-pozicii-na-vseh-stadiyah.md
 */

const row = (extra: Record<string, unknown> = {}) => ({
  id: 'r1',
  lineage_id: 'r1',
  type: 'work',
  name: 'Пробивка гнезд',
  unit: 'м2',
  qty: 2,
  price_work: 100,
  price_material: null,
  ...extra,
});

describe('смета: номер позиции исходной сметы', () => {
  it('колонка идёт первой, до сквозного номера', () => {
    const grid = estimateAdapter.toGrid([row({ source_no: '1' })]);
    const keys = estimateAdapter.columns(grid).map((c) => c.key);
    expect(keys[0]).toBe('source_no');
    expect(keys[1]).toBe('type');
    expect(estimateAdapter.columns(grid)[0].name).toBe('№ в исходной смете');
  });

  it('без номеров колонки нет — смета выглядит как раньше', () => {
    const grid = estimateAdapter.toGrid([row()]);
    const keys = estimateAdapter.columns(grid).map((c) => c.key);
    expect(keys).not.toContain('source_no');
    expect(keys[0]).toBe('type');
  });

  it('колонка появляется, если номер есть хоть у одной строки', () => {
    const grid = estimateAdapter.toGrid([row(), row({ id: 'r2', source_no: '4' })]);
    expect(estimateAdapter.columns(grid).map((c) => c.key)).toContain('source_no');
  });

  it('колонка не редактируется и не числовая — «1.1» остаётся текстом', () => {
    const grid = estimateAdapter.toGrid([row({ source_no: '1.1' })]);
    const column = estimateAdapter.columns(grid).find((c) => c.key === 'source_no')!;
    expect(column.numeric).toBe(false);
    expect(column.editable).toBe(false);
    expect(grid[0].source_no).toBe('1.1');
    expect(estimateAdapter.displayValue(grid[0], 'source_no')).toBeNull();
  });

  it('правка строки номер не теряет', () => {
    const grid = estimateAdapter.toGrid([row({ source_no: '7' })]);
    const edited = { ...grid[0], qty: 5 };
    const [stored] = estimateAdapter.fromGrid([edited]) as Array<Record<string, unknown>>;
    expect(stored.source_no).toBe('7');
    expect(stored.qty).toBe(5);
    // стоимость по-прежнему считается из объёма и цены
    expect(estimateAdapter.recalc(edited, 'qty').cost_work).toBe(500);
  });

  it('новая строка номера не выдумывает', () => {
    const grid = estimateAdapter.toGrid([row({ source_no: '1' })]);
    const fresh = estimateAdapter.emptyRow(estimateAdapter.columns(grid), 'new-1');
    expect(fresh.source_no ?? null).toBeNull();
  });
});
