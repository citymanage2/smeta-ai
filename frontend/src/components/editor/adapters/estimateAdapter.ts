import { billableQty } from '../../../utils/negativeQty';
import {
  DocumentTotals,
  EditorAdapter,
  EditorColumn,
  GridRow,
  Percentages,
  RowKind,
  estimateWidth,
  toNumber,
} from './types';

/**
 * Типизированные документы — смета и версии оптимизации.
 *
 * Здесь строка осмысленная: система знает, что это работа, материал или раздел,
 * и потому умеет то, чего не умеет плоский перечень — считать стоимость,
 * различать вычеты (объём < 0) и связывать материалы с работой.
 *
 * Подключение к интерфейсу — Фазы 5 и 6; здесь адаптер уже полностью рабочий и
 * покрыт тестами, чтобы контракт `EditorAdapter` проверялся двумя реализациями,
 * а не одной.
 */

const COLUMN_DEFS: Array<{
  key: string; name: string; min: number; max: number;
  numeric: boolean; editable: boolean; computed?: boolean;
}> = [
  { key: 'type', name: 'Тип', min: 70, max: 90, numeric: false, editable: true },
  { key: 'name', name: 'Наименование', min: 200, max: 500, numeric: false, editable: true },
  { key: 'unit', name: 'Ед. изм.', min: 70, max: 100, numeric: false, editable: true },
  { key: 'qty', name: 'Кол-во', min: 80, max: 110, numeric: true, editable: true },
  { key: 'price_work', name: 'Цена работ', min: 90, max: 130, numeric: true, editable: true },
  { key: 'cost_work', name: 'Стоим. работ', min: 100, max: 140, numeric: true, editable: false, computed: true },
  { key: 'price_material', name: 'Цена матер.', min: 90, max: 130, numeric: true, editable: true },
  { key: 'cost_material', name: 'Стоим. матер.', min: 100, max: 140, numeric: true, editable: false, computed: true },
];

const STORED_FIELDS = [
  'lineage_id', 'num', 'type', 'name', 'unit', 'qty', 'price_work', 'price_material',
  'cost', 'selected', 'abc_group', 'optimization_note', 'optimization_confidence',
  'is_excluded', 'work_row_id', 'qty_per_work_unit', 'qty_overridden',
  'qty_manual_backup', 'norm_reference',
];

const TYPE_TO_LABEL: Record<string, string> = {
  work: 'Работа', material: 'Материал', section: 'Раздел',
};
const LABEL_TO_TYPE: Record<string, string> = {
  Работа: 'work', Материал: 'material', Раздел: 'section',
};

function costOf(row: GridRow, priceKey: string): number {
  const qty = billableQty(toNumber(row.qty));
  const price = toNumber(row[priceKey]) ?? 0;
  return Math.round(qty * price * 100) / 100;
}

export const estimateAdapter: EditorAdapter = {
  rowFormat: 'estimate',

  toGrid(rows: unknown[]): GridRow[] {
    return rows.map((raw, index) => {
      const row = (raw ?? {}) as Record<string, unknown>;
      const grid: GridRow = { __key: String(row.id ?? `row-${index}`) };
      for (const field of STORED_FIELDS) grid[field] = row[field] ?? null;
      grid.type = TYPE_TO_LABEL[String(row.type ?? '')] ?? row.type ?? '';
      grid.cost_work = costOf(grid, 'price_work');
      grid.cost_material = costOf(grid, 'price_material');
      return grid;
    });
  },

  fromGrid(gridRows: GridRow[]): unknown[] {
    return gridRows.map((grid) => {
      const row: Record<string, unknown> = { id: grid.__key };
      for (const field of STORED_FIELDS) row[field] = grid[field] ?? null;
      row.type = LABEL_TO_TYPE[String(grid.type ?? '')] ?? grid.type ?? 'work';
      row.qty = toNumber(grid.qty);
      row.price_work = toNumber(grid.price_work);
      row.price_material = toNumber(grid.price_material);
      // cost_work / cost_material — вычисляемые, наружу не сохраняются:
      // источник правды по стоимости всегда «объём × цена».
      return row;
    });
  },

  columns(gridRows: GridRow[]): EditorColumn[] {
    return COLUMN_DEFS.map((def) => ({
      key: def.key,
      name: def.name,
      width: estimateWidth(def.name, gridRows, def.key, def.min, def.max),
      editable: def.editable,
      numeric: def.numeric,
      computed: def.computed,
    }));
  },

  rowKind(row: GridRow): RowKind {
    const value = String(row.type ?? '').trim();
    if (value === 'Работа' || value === 'work') return 'work';
    if (value === 'Материал' || value === 'material') return 'material';
    if (value === 'Раздел' || value === 'section') return 'section';
    return null;
  },

  searchText(row: GridRow): string {
    return String(row.name ?? '');
  },

  recalc(row: GridRow, changedKey: string): GridRow {
    if (!['qty', 'price_work', 'price_material'].includes(changedKey)) return row;
    const next: GridRow = { ...row };
    next.cost_work = costOf(next, 'price_work');
    next.cost_material = costOf(next, 'price_material');
    return next;
  },

  totals(rows: GridRow[], pct: Percentages): DocumentTotals | null {
    let sumWork = 0;
    let sumMat = 0;
    for (const row of rows) {
      if (row.is_excluded) continue;
      const kind = estimateAdapter.rowKind(row);
      if (kind === 'section') continue;
      // billableQty внутри costOf: у вычета (объём < 0) стоимости нет.
      sumWork += costOf(row, 'price_work');
      sumMat += costOf(row, 'price_material');
    }
    const overhead = (sumWork * pct.overhead_pct) / 100;
    const transport = (sumMat * pct.transport_pct) / 100;
    return { sumWork, overhead, sumMat, transport, grand: sumWork + overhead + sumMat + transport };
  },

  emptyRow(_columns: EditorColumn[], keySeed: string): GridRow {
    return {
      __key: keySeed,
      lineage_id: keySeed,
      num: null,
      type: 'Работа',
      name: '',
      unit: '',
      qty: null,
      price_work: null,
      price_material: null,
      cost_work: 0,
      cost_material: 0,
      selected: false,
    };
  },
};
