import { GridRow, Percentages, toNumber } from '../components/editor/adapters/types';
import { billableQty } from './negativeQty';

/**
 * Единый расчёт итогов сметы и правила коэффициента.
 *
 * Раньше одно и то же считалось в трёх местах по трём разным формулам, и число
 * на экране не совпадало с числом в скачанном файле. Здесь — одна формула,
 * ровно та же, что у генератора xlsx на сервере:
 *
 *   накладные   = сумма по работам × %накладных
 *   транспортные = сумма по материалам × %транспортных
 *   ИТОГО       = работы + накладные + материалы + транспортные
 *
 * Коэффициент — обратимая настройка документа: он множит цены, но исходные
 * цены строк не меняет никогда, поэтому его можно снять и получить прежние
 * числа.
 */

export interface Coefficient {
  work: number;
  material: number;
  /** 'all' — весь документ; список — только эти строки. */
  scope: 'all' | string[];
}

export interface RowCoefficient {
  work: number;
  material: number;
}

const NEUTRAL: RowCoefficient = { work: 1, material: 1 };

/** Коэффициент, действующий на конкретную строку. */
export function rowCoefficient(
  coefficient: unknown,
  rowKey: string | null | undefined,
): RowCoefficient {
  if (!coefficient || typeof coefficient !== 'object') return NEUTRAL;
  const value = coefficient as Record<string, unknown>;

  const scope = value.scope ?? 'all';
  if (Array.isArray(scope)) {
    if (!rowKey || !scope.map(String).includes(String(rowKey))) return NEUTRAL;
  }

  const factor = (raw: unknown): number => {
    const parsed = toNumber(raw);
    // Ноль и минус коэффициентом не бывают: они обнулили бы смету молча.
    return parsed !== null && parsed > 0 ? parsed : 1;
  };

  return { work: factor(value.work), material: factor(value.material) };
}

/** Есть ли что применять: единичный коэффициент — это отсутствие коэффициента. */
export function isActiveCoefficient(coefficient: unknown): boolean {
  if (!coefficient || typeof coefficient !== 'object') return false;
  const value = coefficient as Record<string, unknown>;
  const work = toNumber(value.work) ?? 1;
  const material = toNumber(value.material) ?? 1;
  return work !== 1 || material !== 1;
}

export function formatFactor(value: number): string {
  return String(value).replace('.', ',');
}

export interface EstimateTotals {
  sumWork: number;
  overhead: number;
  sumMat: number;
  transport: number;
  grand: number;
}

/** Стоимость строки по колонке цены. Вычет (объём < 0) стоимости не имеет. */
export function rowCost(row: GridRow, priceKey: string): number {
  const qty = billableQty(toNumber(row.qty));
  const price = toNumber(row[priceKey]) ?? 0;
  return Math.round(qty * price * 100) / 100;
}

/**
 * Итоги по строкам таблицы. Строки уже содержат цены с коэффициентом (его
 * применяет адаптер при показе), поэтому отдельного умножения здесь нет.
 */
export function calcEstimateTotals(rows: GridRow[], pct: Percentages): EstimateTotals {
  let sumWork = 0;
  let sumMat = 0;
  for (const row of rows) {
    if (row.is_excluded) continue;
    const type = String(row.type ?? '').trim();
    if (type === 'Раздел' || type === 'section') continue;
    sumWork += rowCost(row, 'price_work');
    sumMat += rowCost(row, 'price_material');
  }
  const overhead = (sumWork * pct.overhead_pct) / 100;
  const transport = (sumMat * pct.transport_pct) / 100;
  return { sumWork, overhead, sumMat, transport, grand: sumWork + overhead + sumMat + transport };
}
