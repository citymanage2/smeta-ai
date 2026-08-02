import { AnalogVariant } from '../../../api/documents';
import { rowCoefficient } from '../../../utils/estimateCalc';
import { billableQty } from '../../../utils/negativeQty';
import { BASE_WORK, BASE_MATERIAL } from '../adapters/estimateAdapter';
import { GridRow, toNumber } from '../adapters/types';

/**
 * Подставить найденный аналог вместо исходной позиции.
 *
 * Правка идёт в строку таблицы, то есть в черновик редактора: она откатывается
 * Ctrl+Z и не попадает в документ, пока человек не нажал «Применить».
 *
 * Цена аналога — из интернета, то есть исходная, без коэффициента. Поэтому она
 * ложится в строку базовой, а показывается умноженной — как все остальные цены
 * (правило Фазы 8).
 */
export function applyAnalogToRow(
  row: GridRow,
  variant: AnalogVariant,
  coefficient: unknown,
): GridRow {
  const factor = rowCoefficient(coefficient, row.__key);
  const isMaterial = String(row.type ?? '') === 'Материал'
    || String(row.type ?? '') === 'material';
  const multiplier = isMaterial ? factor.material : factor.work;
  const shown = Math.round(variant.price * multiplier * 100) / 100;
  const qty = billableQty(toNumber(row.qty));

  const next: GridRow = { ...row };
  next.name = variant.name;
  next.unit = variant.unit || row.unit;

  if (isMaterial) {
    next[BASE_MATERIAL] = variant.price;
    next.price_material = shown;
    next.cost_material = Math.round(qty * shown * 100) / 100;
  } else {
    next[BASE_WORK] = variant.price;
    next.price_work = shown;
    next.cost_work = Math.round(qty * shown * 100) / 100;
  }

  // След в примечании: через месяц должно быть понятно, откуда взялась замена
  // и почему цена отличается от той, что дал расчёт.
  const mark = `Аналог по предложению ИИ${variant.source ? ` (${variant.source})` : ''}`;
  const existing = String(row.notes ?? '').trim();
  next.notes = existing ? `${existing}; ${mark}` : mark;
  next.price_list_name = 'Аналог';

  return next;
}
