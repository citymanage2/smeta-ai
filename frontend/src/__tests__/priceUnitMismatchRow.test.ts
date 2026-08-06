import { describe, expect, it } from 'vitest';

import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import {
  KIT_ADDED_PREFIX,
  PRICE_UNIT_MISMATCH_PREFIX,
} from '../components/editor/adapters/types';

/**
 * Единица цены разошлась с единицей позиции.
 *
 * Цена за тонну в строке с килограммами выглядит обычным числом и завышает
 * стоимость в тысячу раз. Такая строка должна быть видна сразу — как видны
 * вычеты и расхождения с нормой расхода.
 *
 * Спека: specs/2026-08-06-edinica-izmereniya-v-podbore-ceny.md
 */

describe('строка с расхождением по единице измерения', () => {
  it('подсвечивается', () => {
    const css = estimateAdapter.rowClass?.({
      __key: 'u1', type: 'Материал', name: 'Смеси сухие', unit: 'кг', qty: 30,
      notes: `${PRICE_UNIT_MISMATCH_PREFIX} — прайс: «т», позиция: «кг».`,
    });

    expect(css).toContain('de-row-price-unit-mismatch');
  });

  it('не мешает подсветке комплекта материалов', () => {
    // Пометка дописывается к прежней — первой остаётся пометка комплекта,
    // по началу строки подсвечивается именно она.
    const css = estimateAdapter.rowClass?.({
      __key: 'u2', type: 'Материал', name: 'Профиль', unit: 'м', qty: 10,
      notes: `${KIT_ADDED_PREFIX}: 10 × 1,05 = 10,5 м. ГЭСН.; `
        + `${PRICE_UNIT_MISMATCH_PREFIX} — прайс: «т», позиция: «м».`,
    });

    expect(css).toContain('de-row-kit-added');
    expect(css).toContain('de-row-price-unit-mismatch');
  });

  it('обычную строку не трогает', () => {
    const css = estimateAdapter.rowClass?.({
      __key: 'u3', type: 'Работа', name: 'Окраска', unit: 'м2', qty: 100,
      price_work: 180, notes: '',
    });

    expect(css ?? '').not.toContain('de-row-price-unit-mismatch');
  });
});
