import { GridRow } from './adapters/types';
import { EditorColumn } from './adapters/types';

/**
 * Данные для конструктора выгрузки-ведомости.
 *
 * Конструктор не знает ни про смету, ни про перечень: колонки и строки ему
 * даёт документ. Цены в строках уже с коэффициентом — так их показывает
 * редактор, и в файл должно уйти ровно то, что человек видел на экране.
 */

export interface ExportColumn {
  key: string;
  label: string;
  numeric: boolean;
}

export interface ExportRow {
  _id: string;
  /** Тип строки — по нему работают пресеты «Ведомость работ / материалов». */
  _kind?: 'work' | 'material' | 'section' | null;
  /** Раздел сводной, если выгрузка идёт по нескольким разделам. */
  _section?: string;
  /**
   * Лист документа. Сервер раскладывает выгрузку по листам с этими именами —
   * ключ служебный, чтобы не столкнуться с колонкой файла заказчика.
   */
  __sheet?: string | null;
  [field: string]: unknown;
}

export interface ExportHeaderOptions {
  title: string;
  object_name: string;
  project_name: string;
  show_date: boolean;
  show_total: boolean;
}

export interface ExportPayload {
  columns: ExportColumn[];
  rows: ExportRow[];
  header: ExportHeaderOptions;
  sheet_name: string;
  file_name?: string;
}

/** Пресеты «в один клик» (решение пользователя 3.4). */
export const PRESETS: Array<{
  id: 'works' | 'materials';
  label: string;
  kind: 'work' | 'material';
  /** Колонки другого типа в ведомости не нужны. */
  dropColumns: string[];
}> = [
  {
    id: 'works', label: 'Ведомость работ', kind: 'work',
    dropColumns: ['price_material', 'cost_material'],
  },
  {
    id: 'materials', label: 'Ведомость материалов', kind: 'material',
    dropColumns: ['price_work', 'cost_work'],
  },
];

/** Колонки таблицы редактора → колонки выгрузки. */
export function columnsFromEditor(columns: EditorColumn[]): ExportColumn[] {
  return columns.map((column) => ({
    key: column.key,
    label: column.name,
    numeric: column.numeric,
  }));
}

/** Строки таблицы редактора → строки выгрузки. */
export function rowsFromEditor(
  rows: GridRow[],
  columns: ExportColumn[],
  kindOf: (row: GridRow) => 'work' | 'material' | 'section' | null,
  sheetOf?: (row: GridRow) => string | null,
): ExportRow[] {
  return rows.map((row) => {
    const exported: ExportRow = { _id: row.__key, _kind: kindOf(row) };
    const sheet = sheetOf?.(row) ?? null;
    if (sheet !== null) exported.__sheet = sheet;
    for (const column of columns) exported[column.key] = row[column.key] ?? null;
    return exported;
  });
}
