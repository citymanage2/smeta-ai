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

/**
 * Лист исходного файла, которому принадлежит строка, — вкладка редактора.
 *
 * Ключ служебный (`__`), потому что у плоских документов ключи полей приходят
 * из шапки файла заказчика, и колонка, честно названная «sheet», иначе стала
 * бы вкладкой. По той же причине служебные ключи не попадают ни в колонки, ни
 * в поиск, ни в сохраняемые ячейки.
 */
export const SHEET_KEY = '__sheet';

/**
 * Начало примечания у строк, дописанных комплектом материалов по нормам расхода
 * (`backend/app/services/material_kits.py`). Признак живёт в тексте примечания,
 * а не в отдельном поле: строки перечня собираются из xlsx, и служебный ключ не
 * пережил бы ни файл, ни сохранение. Меняете формулировку на бэкенде — меняйте
 * здесь: по ней подсвечиваются строки и в перечне, и в смете.
 */
export const KIT_ADDED_PREFIX = 'Добавлено по норме';
export const KIT_MISMATCH_PREFIX = 'Расхождение с нормой';

/**
 * Единица цены разошлась с единицей позиции (`backend/app/utils/unit_compat.py`).
 * Цена за тонну в строке с килограммами выглядит обычным числом и завышает
 * стоимость в тысячу раз — такую строку человек должен видеть сразу.
 *
 * Ищется вхождением, а не началом строки: пометка дописывается к тем, что уже
 * были у позиции, и первой остаётся прежняя.
 */
export const PRICE_UNIT_MISMATCH_PREFIX = 'Цена не подобрана: ед. изм. не совпадает';

/** Служебное поле строки таблицы — в документ такие ключи не сохраняются. */
export function isServiceKey(key: string): boolean {
  return key.startsWith('__');
}

export function sheetName(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text === '' ? null : text;
}

export type RowKind = 'work' | 'material' | 'section' | null;

/**
 * Какие колонки участвуют в свёртке одинаковых позиций.
 *
 * Свёртка — уровень показа: одинаковые работы и материалы собираются в одну
 * строку с общим объёмом, чтобы объём можно было проверить одним взглядом, а
 * цену поправить один раз на все позиции. Строки документа при этом не
 * меняются, поэтому разделы, листы и «№ в исходной смете» остаются на месте.
 *
 * Набор колонок у типов документов разный (у сметы свои поля, у перечня —
 * колонки из файла заказчика), поэтому его сообщает адаптер, а сама свёртка о
 * форматах не знает.
 */
export interface CollapseFields {
  /** Наименование — половина ключа группы. Без него сворачивать нечего. */
  nameKey: string;
  /** Единица измерения — вторая половина ключа. `null` — колонки нет. */
  unitKey: string | null;
  /**
   * Поля, которые правятся сразу во всех позициях группы: цены, наименование,
   * единица. Объёма здесь нет намеренно — общий объём это результат сложения,
   * а не ввод (решение пользователя 13.08.2026).
   */
  sharedKeys: string[];
  /** Поля, которые в свёрнутой строке складываются: объём и стоимости. */
  sumKeys: string[];
}

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
   * Лист, которому принадлежит строка. `null` — документ из одного листа, и
   * вкладок в редакторе нет.
   */
  sheetOf(row: GridRow): string | null;
  /** Поставить строке лист: новая строка попадает на открытую вкладку. */
  withSheet(row: GridRow, sheet: string | null): GridRow;
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
  /**
   * Колонки для свёртки одинаковых позиций. `null` — свернуть нечем: в файле
   * заказчика может не оказаться колонки с наименованием, и группировать
   * строки тогда не по чему.
   */
  collapseFields?(columns: EditorColumn[]): CollapseFields | null;
  /**
   * Колонка объёма — по ней узнаются строки-вычеты (объём < 0), которые
   * прячет режим «Убрать минусы». `null` — колонки объёма в документе нет, и
   * прятать не по чему.
   *
   * Спрашиваем у адаптера, а не ищем сами: у сметы это поле `qty`, а у плоских
   * документов колонка называется так, как её назвал заказчик.
   */
  qtyKey?(columns: EditorColumn[]): string | null;
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
