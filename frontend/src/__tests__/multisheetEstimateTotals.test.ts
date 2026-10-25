/**
 * Итоги сметы из нескольких листов на экране — те же числа, что в файле.
 *
 * Правило проекта «экран и скачиваемый файл считают по одной формуле» при
 * разбивке на листы даёт не одну сумму, а N+1: итог каждой вкладки и итог
 * документа. Позиции и числа — те же, что в бэкенд-тесте файла
 * (`backend/tests/test_multisheet_estimate.py`): там их считает генератор xlsx,
 * здесь — `calcEstimateTotals`, по которому редактор показывает итог вкладки
 * (`rowsOfSheet`) и всего документа.
 */
import { describe, expect, it } from 'vitest';

import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { rowsOfSheet } from '../stores/documentEditor';
import { calcEstimateTotals } from '../utils/estimateCalc';

// Раздел 1: работа 12 × 1000 = 12 000; материал 5 × 200 = 1 000
// Раздел 2: работа 3 × 5000 = 15 000; материал 10 × 350 = 3 500
const STORED = [
  { id: 'r1', type: 'work', name: 'Демонтаж стен', unit: 'м2', qty: 12,
    price_work: 1000, price_material: null, sheet: 'Раздел 1' },
  { id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт', qty: 5,
    price_work: null, price_material: 200, sheet: 'Раздел 1' },
  { id: 'r3', type: 'work', name: 'Кладка', unit: 'м3', qty: 3,
    price_work: 5000, price_material: null, sheet: 'Раздел 2' },
  { id: 'r4', type: 'material', name: 'Раствор', unit: 'кг', qty: 10,
    price_work: null, price_material: 350, sheet: 'Раздел 2' },
];

const RATES = { overhead_pct: 3, transport_pct: 3 };

describe('итоги многолистовой сметы', () => {
  const rows = estimateAdapter.toGrid(STORED);

  it('у каждой вкладки свой итог', () => {
    // 12 000 + 360 + 1 000 + 30
    expect(calcEstimateTotals(rowsOfSheet(estimateAdapter, rows, 'Раздел 1'), RATES).grand)
      .toBeCloseTo(13390, 2);
    // 15 000 + 450 + 3 500 + 105
    expect(calcEstimateTotals(rowsOfSheet(estimateAdapter, rows, 'Раздел 2'), RATES).grand)
      .toBeCloseTo(19055, 2);
  });

  it('итог документа — сумма вкладок, то же «ВСЕГО», что в файле', () => {
    expect(calcEstimateTotals(rows, RATES).grand).toBeCloseTo(32445, 2);
  });
});
