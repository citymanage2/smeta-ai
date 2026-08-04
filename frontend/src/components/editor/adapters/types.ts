import { RowFormat } from '../../../api/documents';

/**
 * Строка в том виде, в каком её показывает таблица: плоский объект, где ключ
 * колонки — ключ поля. Оба формата хранения (плоские ячейки перечня и
 * типизированные строки сметы) приводятся к нему адаптером на входе и
 * разворачиваются обратно на выходе — таблица про разницу не знает.
 */
export interface GridRow {
  __key: string;
  [field: string]: unknown;
}

export type RowKind = 'work' | 'material' | 'section' | null;

export interface EditorColumn {
  key: string;
  name: string;
  width: number;
  editable: boolean;
  /** Числовая колонка: вставка нечисла отклоняется, значение выравнивается вправо. */
  numeric: boolean;
  /** Вычисляемая колонка (стоимость) — правится только пересчётом. */
  computed?: boolean;
}

export interface DocumentTotals {
  sumWork: number;
  overhead: number;
  sumMat: number;
  transport: number;
  grand: number;
}

export interface Percentages {
  overhead_pct: number;
  transport_pct: number;
}

/**
 * Настройки документа, которые влияют на показ строк. Пока это только
 * коэффициент к ценам: в таблице цены показываются уже с ним, а в документ
 * уходят исходные (решение пользователя, Фаза 8).
 */
export interface AdapterContext {
  coefficient?: unknown;
}

/**
 * Что отличается между типами документов. Оболочка редактора одна, разный
 * функционал живёт здесь: набор колонок, правила пересчёта, итоги, тип строки.
 */
export interface EditorAdapter {
  rowFormat: RowFormat;
  /** Хранимые строки → строки таблицы. */
  toGrid(rows: unknown[], ctx?: AdapterContext): GridRow[];
  /** Строки таблицы → хранимые строки (в исходном формате). */
  fromGrid(gridRows: GridRow[], ctx?: AdapterContext): unknown[];
  columns(gridRows: GridRow[]): EditorColumn[];
  rowKind(row: GridRow): RowKind;
  /** Текст, по которому работает поиск. */
  searchText(row: GridRow): string;
  /** Пересчёт зависимых полей после правки ячейки (цена × объём → стоимость). */
  recalc(row: GridRow, changedKey: string, columns: EditorColumn[]): GridRow;
  /** Итоги по документу; null — если считать нечего (перечень без цен). */
  totals(rows: GridRow[], pct: Percentages): DocumentTotals | null;
  /** Пустая строка для «Добавить строку». */
  emptyRow(columns: EditorColumn[], keySeed: string): GridRow;
  /**
   * Как показать ячейку: деньги — `1 111 111,11`, объём — с запятой, ноль в
   * денежной колонке — пустой ячейкой. `null` — показывать значение как есть.
   *
   * Формат живёт только здесь: значение строки не меняется, поэтому в выгрузку
   * и в файл уходит число, а не текст с пробелами.
   */
  displayValue?(row: GridRow, key: string): string | null;
  /**
   * Css-классы строки: подсветка вычетов, исключённых позиций, цен из прайса и
   * групп А/В/С. У плоских документов подсвечивать нечего — метод необязателен.
   */
  rowClass?(row: GridRow): string | undefined;
}

// --- Общие помощники форматов ---------------------------------------------

export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const normalized = String(value).trim().replace(/\s/g, '').replace(',', '.');
  if (normalized === '') return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

const CHAR_PX = 8;
const COL_PAD = 24;

export function estimateWidth(
  header: string,
  rows: GridRow[],
  key: string,
  min: number,
  max: number,
): number {
  let longest = header.length;
  for (const row of rows) {
    const value = row[key];
    const length = value === null || value === undefined ? 0 : String(value).length;
    if (length > longest) longest = length;
  }
  return Math.min(max, Math.max(min, longest * CHAR_PX + COL_PAD));
}
