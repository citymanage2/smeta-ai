import { formatDecimal, formatMoney } from '../../../utils/formatNumber';
import {
  CollapseFields,
  DocumentTotals,
  EditorAdapter,
  EditorColumn,
  GridRow,
  KIT_ADDED_PREFIX,
  KIT_MISMATCH_PREFIX,
  Percentages,
  RowKind,
  SHEET_KEY,
  estimateWidth,
  isServiceKey,
  sheetName,
  toNumber,
} from './types';

/**
 * Плоские документы — перечень и результат проверки полноты.
 *
 * Данные хранятся «как в файле»: `{row_id, cells: {Колонка: значение}}`, без
 * привязки к схеме сметы. Колонки берутся из самих данных, поэтому один и тот
 * же адаптер работает с любым набором столбцов, который пришёл из xlsx.
 */

interface GenericStoredRow {
  row_id: string;
  /** Лист исходного файла — вкладка редактора. Нет поля = документ без вкладок. */
  sheet?: string | null;
  cells: Record<string, unknown>;
}

const EXCLUDED_COLUMNS = new Set(['№', '#']);
const TYPE_COL = 'Тип';
const NAME_COL = 'Наименование';
const NOTES_COL = 'примечание';
/** Номер позиции исходной сметы — им сверяют перечень со сметой заказчика. */
const SOURCE_NO_COL = '№ в исходной смете';

/** Примечание строки. Колонка приходит из файла, поэтому ищем по началу имени. */
function noteOf(row: GridRow): string {
  for (const [key, value] of Object.entries(row)) {
    if (isServiceKey(key)) continue;
    if (key.trim().toLowerCase().startsWith(NOTES_COL)) return String(value ?? '');
  }
  return '';
}

const COL_MIN = 60;
const COL_MAX = 280;
const COL_MAX_NAME = 500;
const COL_MAX_PRICE = 110;

const QTY_KEYWORDS = ['кол-во', 'количество', 'кол.', 'объем', 'объём', 'кол'];
/** Единица измерения — вторая половина ключа при свёртке одинаковых позиций. */
const UNIT_KEYWORDS = ['ед. изм', 'ед.изм', 'ед изм', 'единица'];
const PRICE_WORK_KEYWORDS = ['цена работ', 'цена работы'];
const PRICE_MAT_KEYWORDS = ['цена материал'];
const COST_WORK_KEYWORDS = ['стоимость работ'];
const COST_MAT_KEYWORDS = ['стоимость материал'];

const NUMERIC_KEYWORDS = [
  ...QTY_KEYWORDS, ...PRICE_WORK_KEYWORDS, ...PRICE_MAT_KEYWORDS,
  ...COST_WORK_KEYWORDS, ...COST_MAT_KEYWORDS,
];

// Деньги показываем как `1 111 111,11`, ноль — пустой ячейкой.
const MONEY_KEYWORDS = [
  ...PRICE_WORK_KEYWORDS, ...PRICE_MAT_KEYWORDS,
  ...COST_WORK_KEYWORDS, ...COST_MAT_KEYWORDS,
];

function matches(column: string, keywords: string[]): boolean {
  const lower = column.trim().toLowerCase();
  return keywords.some((kw) => lower.startsWith(kw));
}

interface RecalcPair { priceCol: string; costCol: string }

interface RecalcConfig { qtyCol: string | null; pairs: RecalcPair[] }

/** Пары «цена → стоимость»: правка цены или объёма пересчитывает стоимость. */
export function findRecalcConfig(columns: string[]): RecalcConfig {
  let qtyCol: string | null = null;
  let priceWork: string | null = null;
  let priceMat: string | null = null;
  let costWork: string | null = null;
  let costMat: string | null = null;

  for (const col of columns) {
    if (!qtyCol && matches(col, QTY_KEYWORDS)) { qtyCol = col; continue; }
    if (!priceWork && matches(col, PRICE_WORK_KEYWORDS)) { priceWork = col; continue; }
    if (!priceMat && matches(col, PRICE_MAT_KEYWORDS)) { priceMat = col; continue; }
    if (!costWork && matches(col, COST_WORK_KEYWORDS)) { costWork = col; continue; }
    if (!costMat && matches(col, COST_MAT_KEYWORDS)) { costMat = col; continue; }
  }

  const pairs: RecalcPair[] = [];
  if (priceWork && costWork) pairs.push({ priceCol: priceWork, costCol: costWork });
  if (priceMat && costMat) pairs.push({ priceCol: priceMat, costCol: costMat });
  return { qtyCol, pairs };
}

function isStoredRow(row: unknown): row is GenericStoredRow {
  return typeof row === 'object' && row !== null && 'cells' in (row as object);
}

export const genericAdapter: EditorAdapter = {
  rowFormat: 'generic',

  toGrid(rows: unknown[]): GridRow[] {
    return rows.map((row, index) => {
      if (!isStoredRow(row)) return { __key: `row-${index}` };
      const cells = row.cells ?? {};
      const grid: GridRow = { __key: String(row.row_id ?? `row-${index}`) };
      grid[SHEET_KEY] = sheetName(row.sheet);
      for (const [key, value] of Object.entries(cells)) {
        if (EXCLUDED_COLUMNS.has(key)) continue;
        grid[key] = value;
      }
      return grid;
    });
  },

  fromGrid(gridRows: GridRow[]): unknown[] {
    return gridRows.map((grid) => {
      const cells: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(grid)) {
        // Служебные ключи — не данные файла: попав в ячейки, лист стал бы
        // колонкой таблицы и уехал бы в скачиваемый файл.
        if (isServiceKey(key)) continue;
        cells[key] = value;
      }
      const sheet = sheetName(grid[SHEET_KEY]);
      // Документ без вкладок поля не получает — строки остаются такими же, как
      // до появления многолистовых файлов.
      return sheet === null
        ? { row_id: grid.__key, cells }
        : { row_id: grid.__key, sheet, cells };
    });
  },

  columns(gridRows: GridRow[]): EditorColumn[] {
    if (gridRows.length === 0) return [];
    // Порядок колонок берём из первой строки — он совпадает с порядком в файле.
    const keys = Object.keys(gridRows[0]).filter((k) => !isServiceKey(k));
    // Номер позиции исходной сметы идёт первым — с него начинается сверка
    // перечня со сметой заказчика, ради неё колонка и появилась.
    const pinned = [SOURCE_NO_COL, TYPE_COL, NAME_COL].filter((k) => keys.includes(k));
    const ordered = [...pinned, ...keys.filter((k) => !pinned.includes(k))];
    const { pairs } = findRecalcConfig(ordered);
    const computed = new Set(pairs.map((p) => p.costCol));

    return ordered.map((key) => {
      const numeric = matches(key, NUMERIC_KEYWORDS);
      const max = key === NAME_COL ? COL_MAX_NAME : numeric ? COL_MAX_PRICE : COL_MAX;
      return {
        key,
        name: key,
        width: estimateWidth(key, gridRows, key, COL_MIN, max),
        editable: !computed.has(key),
        numeric,
        computed: computed.has(key),
      };
    });
  },

  rowKind(row: GridRow): RowKind {
    const value = String(row[TYPE_COL] ?? '').trim();
    if (value === 'Работа') return 'work';
    if (value === 'Материал') return 'material';
    return null;
  },

  rowClass(row: GridRow): string | undefined {
    // Признак берём из примечания, а не из служебного поля: строки документа
    // собираются из xlsx, и ключ вне ячеек не пережил бы ни файл, ни сохранение.
    const note = noteOf(row).trimStart();
    if (note.startsWith(KIT_ADDED_PREFIX)) return 'de-row-kit-added';
    if (note.startsWith(KIT_MISMATCH_PREFIX)) return 'de-row-kit-mismatch';
    return undefined;
  },

  searchText(row: GridRow): string {
    if (NAME_COL in row) return String(row[NAME_COL] ?? '');
    // В файле может не быть колонки «Наименование» — тогда ищем по всей строке.
    return Object.entries(row)
      .filter(([key]) => !isServiceKey(key))
      .map(([, value]) => String(value ?? ''))
      .join(' ');
  },

  recalc(row: GridRow, changedKey: string, columns: EditorColumn[]): GridRow {
    const config = findRecalcConfig(columns.map((c) => c.key));
    if (!config.qtyCol || config.pairs.length === 0) return row;

    const priceCols = new Set(config.pairs.map((p) => p.priceCol));
    const isTrigger = changedKey === config.qtyCol || priceCols.has(changedKey);
    if (!isTrigger) return row;

    const qty = toNumber(row[config.qtyCol]) ?? 0;
    const next: GridRow = { ...row };
    for (const { priceCol, costCol } of config.pairs) {
      const price = toNumber(row[priceCol]) ?? 0;
      next[costCol] = Math.round(qty * price);
    }
    return next;
  },

  totals(rows: GridRow[], pct: Percentages): DocumentTotals | null {
    if (rows.length === 0) return null;
    const keys = Object.keys(rows[0]).filter((k) => !isServiceKey(k));
    const costWork = keys.find((k) => matches(k, COST_WORK_KEYWORDS)) ?? null;
    const costMat = keys.find((k) => matches(k, COST_MAT_KEYWORDS)) ?? null;
    if (!costWork && !costMat) return null;

    let sumWork = 0;
    let sumMat = 0;
    for (const row of rows) {
      const kind = genericAdapter.rowKind(row);
      if (costWork && kind === 'work') sumWork += toNumber(row[costWork]) ?? 0;
      if (costMat && kind === 'material') sumMat += toNumber(row[costMat]) ?? 0;
    }
    const overhead = (sumWork * pct.overhead_pct) / 100;
    const transport = (sumMat * pct.transport_pct) / 100;
    return { sumWork, overhead, sumMat, transport, grand: sumWork + overhead + sumMat + transport };
  },

  displayValue(row: GridRow, key: string): string | null {
    // Колонки приходят из файла заказчика, поэтому опознаём их по названию — тем
    // же ключевым словам, по которым работает пересчёт «цена × объём».
    const money = matches(key, MONEY_KEYWORDS);
    if (!money && !matches(key, QTY_KEYWORDS)) return null;

    const value = toNumber(row[key]);
    // Не число — оставляем как есть: в перечне заказчика в колонке количества
    // попадается текст вроде «по проекту», терять его нельзя.
    if (value === null) return String(row[key] ?? '') === '' ? '' : null;
    if (money) return value === 0 ? '' : formatMoney(value);
    return formatDecimal(value);
  },

  emptyRow(columns: EditorColumn[], keySeed: string): GridRow {
    const row: GridRow = { __key: keySeed };
    for (const column of columns) row[column.key] = '';
    return row;
  },

  sheetOf(row: GridRow): string | null {
    return sheetName(row[SHEET_KEY]);
  },

  withSheet(row: GridRow, sheet: string | null): GridRow {
    return { ...row, [SHEET_KEY]: sheet };
  },

  /**
   * Свёртка одинаковых позиций. Колонки опознаются по названиям из файла
   * заказчика — теми же ключевыми словами, по которым уже работает пересчёт
   * «цена × объём».
   *
   * Нет колонки наименования — сворачивать не по чему: собрать строки в группы
   * по номеру или по цене значило бы склеить разные позиции.
   */
  collapseFields(columns: EditorColumn[]): CollapseFields | null {
    const keys = columns.map((column) => column.key);
    if (!keys.includes(NAME_COL)) return null;

    const unitKey = keys.find((key) => matches(key, UNIT_KEYWORDS)) ?? null;
    const { qtyCol, pairs } = findRecalcConfig(keys);

    return {
      nameKey: NAME_COL,
      unitKey,
      sharedKeys: [
        NAME_COL,
        ...(unitKey ? [unitKey] : []),
        ...pairs.map((pair) => pair.priceCol),
      ],
      sumKeys: [
        ...(qtyCol ? [qtyCol] : []),
        ...pairs.map((pair) => pair.costCol),
      ],
    };
  },
};
