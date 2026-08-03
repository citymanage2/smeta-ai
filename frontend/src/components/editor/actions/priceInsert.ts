import { rowCoefficient } from '../../../utils/estimateCalc';
import { BASE_WORK, BASE_MATERIAL } from '../adapters/estimateAdapter';
import { EditorAdapter, EditorColumn, GridRow } from '../adapters/types';

/**
 * Позиция прайса, готовая к вставке в документ или к отправке в прайс.
 * Один и тот же формат в обе стороны: что взяли из прайса, то в него и вернём.
 */
export interface PricePosition {
  kind: 'work' | 'material';
  name: string;
  unit: string | null;
  price: number | null;
}

/**
 * Позиции прайса → строки документа.
 *
 * Цена работы попадает в цену работ, цена материала — в цену материалов:
 * в смете это разные колонки и разные итоги.
 *
 * Цена из прайса — исходная, без коэффициента. Поэтому она едет в строке как
 * базовая, а в таблице показывается умноженной, как и все остальные цены.
 * Иначе снятие коэффициента изменило бы её, хотя человек её не трогал.
 */
export function buildPriceRows(
  positions: PricePosition[],
  adapter: EditorAdapter,
  columns: EditorColumn[],
  seedPrefix: string,
  coefficient?: unknown,
): GridRow[] {
  return positions.map((position, index) => {
    const seed = `${seedPrefix}-${index}`;
    const row = adapter.emptyRow(columns, seed);
    const factor = rowCoefficient(coefficient, seed);
    const shown = (base: number | null, multiplier: number): number | null => (
      base === null ? null : Math.round(base * multiplier * 100) / 100
    );

    row.name = position.name;
    row.unit = position.unit ?? '';
    if (position.kind === 'work') {
      row.type = 'Работа';
      row[BASE_WORK] = position.price ?? null;
      row.price_work = shown(position.price ?? null, factor.work);
    } else {
      row.type = 'Материал';
      row[BASE_MATERIAL] = position.price ?? null;
      row.price_material = shown(position.price ?? null, factor.material);
    }
    // Откуда взялась цена — видно и в редакторе, и в скачиваемом файле.
    row.price_list_name = 'Прайс';
    return row;
  });
}

/**
 * Вставить строки сразу после текущей (решение пользователя 7.1).
 *
 * Якорь — ключ строки, а не её номер: номер «уезжает» при поиске и смене
 * вкладки, и вставка попала бы не туда. Якоря нет — строки идут в конец.
 */
export function insertRowsAfter(
  rows: GridRow[],
  anchorKey: string | null,
  inserted: GridRow[],
): GridRow[] {
  if (inserted.length === 0) return rows;
  const at = anchorKey ? rows.findIndex((row) => row.__key === anchorKey) : -1;
  if (at < 0) return [...rows, ...inserted];
  return [...rows.slice(0, at + 1), ...inserted, ...rows.slice(at + 1)];
}
