import { billableQty, isNegativeQty } from '../../../utils/negativeQty';
import { calcEstimateTotals, rowCoefficient } from '../../../utils/estimateCalc';
import { formatDecimal, formatMoney } from '../../../utils/formatNumber';
import {
  AdapterContext,
  CollapseFields,
  DocumentTotals,
  EditorAdapter,
  EditorColumn,
  GridRow,
  KIT_ADDED_PREFIX,
  KIT_MISMATCH_PREFIX,
  PRICE_UNIT_MISMATCH_PREFIX,
  Percentages,
  RowKind,
  SHEET_KEY,
  estimateWidth,
  sheetName,
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

interface ColumnDef {
  key: string; name: string; min: number; max: number;
  numeric: boolean; editable: boolean; computed?: boolean;
}

// Номер позиции в смете заказчика. Колонка необязательная и только для чтения:
// он приезжает с перечня, а выдумывать его в смете нечем — там уже нет
// исходного файла, по которому его можно проверить.
const SOURCE_NO_DEF: ColumnDef = {
  key: 'source_no', name: '№ в исходной смете', min: 90, max: 120,
  numeric: false, editable: false,
};

const COLUMN_DEFS: ColumnDef[] = [
  { key: 'type', name: 'Тип', min: 70, max: 90, numeric: false, editable: true },
  { key: 'name', name: 'Наименование', min: 200, max: 500, numeric: false, editable: true },
  { key: 'unit', name: 'Ед. изм.', min: 70, max: 100, numeric: false, editable: true },
  { key: 'qty', name: 'Кол-во', min: 80, max: 110, numeric: true, editable: true },
  { key: 'price_work', name: 'Цена работ', min: 90, max: 130, numeric: true, editable: true },
  { key: 'cost_work', name: 'Стоим. работ', min: 100, max: 140, numeric: true, editable: false, computed: true },
  { key: 'price_material', name: 'Цена матер.', min: 90, max: 130, numeric: true, editable: true },
  { key: 'cost_material', name: 'Стоим. матер.', min: 100, max: 140, numeric: true, editable: false, computed: true },
];

// Поля, которые проходят через редактор насквозь. Часть из них колонками не
// показывается (источник цены, найденные ссылки, примечание), но пропасть при
// сохранении не должна: их нашёл ИИ, и они попадают в скачиваемый файл.
const STORED_FIELDS = [
  'lineage_id', 'num', 'type', 'name', 'unit', 'qty', 'price_work', 'price_material',
  'cost', 'selected', 'abc_group', 'optimization_note', 'optimization_confidence',
  'is_excluded', 'work_row_id', 'qty_per_work_unit', 'qty_overridden',
  'qty_manual_backup', 'norm_reference',
  'price_list_name', 'sources', 'notes', 'source_no',
];

const TYPE_TO_LABEL: Record<string, string> = {
  work: 'Работа', material: 'Материал', section: 'Раздел',
};
const LABEL_TO_TYPE: Record<string, string> = {
  Работа: 'work', Материал: 'material', Раздел: 'section',
};

// Исходные цены (без коэффициента) едут рядом со строкой таблицы. Без них
// нельзя отличить «человек правил цену» от «цену показали умноженной», и
// каждое сохранение множило бы её заново.
export const BASE_WORK = '__base_price_work';
export const BASE_MATERIAL = '__base_price_material';

// Денежные колонки: показываются как `1 111 111,11`, ноль — пустой ячейкой.
// У работы стоимость материалов равна нулю и наоборот — считать там нечего, и
// ноль в такой ячейке читается как посчитанный результат.
const MONEY_COLUMNS = new Set(['price_work', 'cost_work', 'price_material', 'cost_material']);

function costOf(row: GridRow, priceKey: string): number {
  const qty = billableQty(toNumber(row.qty));
  const price = toNumber(row[priceKey]) ?? 0;
  return Math.round(qty * price * 100) / 100;
}

function scale(price: number | null, factor: number): number | null {
  if (price === null) return null;
  if (factor === 1) return price;
  return Math.round(price * factor * 100) / 100;
}

/**
 * Показанная цена → исходная.
 *
 * Если ячейку не трогали, возвращаем ровно ту исходную цену, что была: иначе
 * деление вносило бы копеечный сдвиг при каждом сохранении. Если правили —
 * введённое считается ценой с коэффициентом, поэтому делим.
 */
function unscale(
  shown: number | null, base: number | null, factor: number,
): number | null {
  if (shown === null) return null;
  if (factor === 1) return shown;
  if (base !== null && scale(base, factor) === shown) return base;
  return Math.round((shown / factor) * 100) / 100;
}

export const estimateAdapter: EditorAdapter = {
  rowFormat: 'estimate',

  toGrid(rows: unknown[], ctx?: AdapterContext): GridRow[] {
    return rows.map((raw, index) => {
      const row = (raw ?? {}) as Record<string, unknown>;
      const key = String(row.id ?? `row-${index}`);
      const grid: GridRow = { __key: key };
      for (const field of STORED_FIELDS) grid[field] = row[field] ?? null;
      grid[SHEET_KEY] = sheetName(row.sheet);
      grid.type = TYPE_TO_LABEL[String(row.type ?? '')] ?? row.type ?? '';

      // Цены показываются уже с коэффициентом (решение пользователя, Фаза 8).
      // Исходные держим рядом: по ним видно, правил ли человек ячейку, и
      // благодаря им повторное сохранение не множит цену второй раз.
      const factor = rowCoefficient(ctx?.coefficient, key);
      grid[BASE_WORK] = toNumber(grid.price_work);
      grid[BASE_MATERIAL] = toNumber(grid.price_material);
      grid.price_work = scale(grid[BASE_WORK] as number | null, factor.work);
      grid.price_material = scale(grid[BASE_MATERIAL] as number | null, factor.material);

      grid.cost_work = costOf(grid, 'price_work');
      grid.cost_material = costOf(grid, 'price_material');
      return grid;
    });
  },

  fromGrid(gridRows: GridRow[], ctx?: AdapterContext): unknown[] {
    return gridRows.map((grid) => {
      const row: Record<string, unknown> = { id: grid.__key };
      for (const field of STORED_FIELDS) row[field] = grid[field] ?? null;
      // Лист хранится служебным ключом, чтобы не стать колонкой таблицы;
      // в документ он уходит обычным полем строки.
      row.sheet = sheetName(grid[SHEET_KEY]);
      row.type = LABEL_TO_TYPE[String(grid.type ?? '')] ?? grid.type ?? 'work';
      row.qty = toNumber(grid.qty);

      const factor = rowCoefficient(ctx?.coefficient, grid.__key);
      row.price_work = unscale(
        toNumber(grid.price_work), toNumber(grid[BASE_WORK]), factor.work,
      );
      row.price_material = unscale(
        toNumber(grid.price_material), toNumber(grid[BASE_MATERIAL]), factor.material,
      );
      // cost_work / cost_material — вычисляемые, наружу не сохраняются:
      // источник правды по стоимости всегда «объём × цена».
      return row;
    });
  },

  columns(gridRows: GridRow[]): EditorColumn[] {
    // Колонка номера показывается, только если он известен хоть одной строке:
    // у сметы по файлу без нумерации пустой столбец лишний. Правило то же, по
    // которому колонку добавляет генератор файла.
    const hasSourceNo = gridRows.some(
      (row) => String(row.source_no ?? '').trim() !== '',
    );
    const defs = hasSourceNo ? [SOURCE_NO_DEF, ...COLUMN_DEFS] : COLUMN_DEFS;

    return defs.map((def) => ({
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
    // Формула одна на весь проект — та же, по которой сервер собирает файл
    // сметы и считает итог задачи.
    return calcEstimateTotals(rows, pct);
  },

  rowClass(row: GridRow): string | undefined {
    const classes: string[] = [];

    // Вычет: объём меньше нуля корректирует соседнюю позицию, стоимость по нему
    // не считается — это должно быть видно, а не выясняться из итога.
    if (isNegativeQty(toNumber(row.qty))) classes.push('de-row-deduction');
    if (row.is_excluded) classes.push('de-row-excluded');
    if (row.price_list_name) classes.push('de-row-from-price');

    // Комплект материалов, дописанный по нормам расхода на шаге «Полнота»,
    // доезжает до сметы вместе с примечанием. В файле заказчика этих позиций не
    // было, и в смете это должно быть видно так же, как в перечне.
    const note = String(row.notes ?? '').trimStart();
    if (note.startsWith(KIT_ADDED_PREFIX)) classes.push('de-row-kit-added');
    if (note.startsWith(KIT_MISMATCH_PREFIX)) classes.push('de-row-kit-mismatch');

    // Единица цены разошлась с единицей позиции: цена либо не подобрана, либо
    // подозрительна. Ищем вхождением — пометка могла дописаться к прежней.
    if (note.includes(PRICE_UNIT_MISMATCH_PREFIX)) classes.push('de-row-price-unit-mismatch');

    const abc = String(row.abc_group ?? '').trim().toUpperCase();
    if (abc === 'A' || abc === 'А') classes.push('de-row-abc-a');
    if (abc === 'B' || abc === 'В') classes.push('de-row-abc-b');
    if (abc === 'C' || abc === 'С') classes.push('de-row-abc-c');

    return classes.length > 0 ? classes.join(' ') : undefined;
  },

  displayValue(row: GridRow, key: string): string | null {
    if (MONEY_COLUMNS.has(key)) {
      const value = toNumber(row[key]);
      // Ноль гасим по значению, а не по типу строки: итог складывает обе цены у
      // каждой строки, и гашение по типу спрятало бы деньги, которые в ИТОГО
      // всё равно попадают.
      return value === null || value === 0 ? '' : formatMoney(value);
    }
    if (key === 'qty') {
      const value = toNumber(row[key]);
      return value === null ? '' : formatDecimal(value);
    }
    return null;
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

  sheetOf(row: GridRow): string | null {
    return sheetName(row[SHEET_KEY]);
  },

  withSheet(row: GridRow, sheet: string | null): GridRow {
    return { ...row, [SHEET_KEY]: sheet };
  },

  // Свёртка одинаковых позиций. Стоимости складываются по позициям, а не
  // считаются как «общий объём × цена»: цены внутри группы могут отличаться.
  collapseFields(): CollapseFields {
    return {
      nameKey: 'name',
      unitKey: 'unit',
      sharedKeys: ['name', 'unit', 'price_work', 'price_material'],
      sumKeys: ['qty', 'cost_work', 'cost_material'],
    };
  },
};
