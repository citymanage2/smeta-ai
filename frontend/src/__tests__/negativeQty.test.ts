import { describe, it, expect } from 'vitest';
import { billableQty, isNegativeQty } from '../utils/negativeQty';
import { formatQty } from '../utils/formatQty';
import { calcSummary } from '../stores/summaryEditorStore';
import { DEFAULT_OVERRIDES } from '../types/summary';
import { EstimateRow } from '../types';

/**
 * Строка с отрицательным объёмом — вычет, а не работа: стоимости по ней нет.
 * Раньше qty × цена давало отрицательную сумму и занижало итог сметы.
 *
 * План: plans/2026-07-30-otricatelnyy-obyom-bez-rascheta.md
 */

describe('negativeQty', () => {
  it('распознаёт вычет', () => {
    expect(isNegativeQty(-0.61)).toBe(true);
    expect(isNegativeQty(0)).toBe(false);
    expect(isNegativeQty(0.61)).toBe(false);
    expect(isNegativeQty(null)).toBe(false);
    expect(isNegativeQty(undefined)).toBe(false);
  });

  it('обнуляет объём вычета для умножения на цену', () => {
    expect(billableQty(-0.61)).toBe(0);
    expect(billableQty(3)).toBe(3);
    expect(billableQty(null)).toBe(0);
  });
});

describe('formatQty', () => {
  it('показывает дробный объём точно, а не округляет до целого', () => {
    // Раньше Math.round печатал 0,61 как «1» — по такой сетке смету не проверить.
    expect(formatQty(0.61)).toBe('0,61');
    expect(formatQty(-1.1139)).toBe('-1,1139');
    expect(formatQty(137.3)).toBe('137,3');
  });

  it('целые остаются без хвостовых нулей', () => {
    expect(formatQty(50)).toBe('50');
    expect(formatQty(0)).toBe('0');
  });
});

function row(id: string, qty: number | null, priceWork: number | null): EstimateRow {
  return {
    id,
    lineage_id: id,
    num: 1,
    type: 'work',
    name: 'Работа',
    unit: 'м²',
    qty,
    price_work: priceWork,
    price_material: null,
    cost: null,
    selected: false,
  };
}

describe('сводная не считает вычеты', () => {
  const section = (rows: EstimateRow[]) => ({
    card_id: 'c1',
    card_name: 'Раздел',
    tax_pct: 0,
    rows,
  });

  it('вычет не уменьшает сумму раздела', () => {
    const withoutNegative = calcSummary(
      [section([row('w1', 10, 100)])],
      DEFAULT_OVERRIDES,
    );
    const withNegative = calcSummary(
      [section([row('w1', 10, 100), row('w2', -5, 100)])],
      DEFAULT_OVERRIDES,
    );

    expect(withNegative.section_totals[0].works_raw).toBe(
      withoutNegative.section_totals[0].works_raw,
    );
    expect(withNegative.section_totals[0].works_raw).toBe(1000);
  });
});
