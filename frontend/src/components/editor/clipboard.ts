import { EditorColumn, GridRow, toNumber } from './adapters/types';

/**
 * Буфер обмена для таблицы.
 *
 * react-data-grid 7 умеет копировать и вставлять только одну ячейку
 * (`PasteEvent` содержит ровно одну исходную и одну целевую), а вставка из
 * внешнего Excel не поддержана вовсе. Диапазоны — здесь: разбор и сборка TSV
 * (формат, в котором Excel кладёт таблицу в буфер) плюс аккуратное наложение
 * вставленного куска на существующие строки.
 *
 * Правила наложения намеренно консервативные — это смета, а не блокнот:
 *   * вставка не создаёт новых строк: лишнее обрезается и о нём сообщается;
 *   * вычисляемые и нередактируемые колонки пропускаются;
 *   * нечисловое значение в числовой колонке не затирает старое.
 */

export interface PasteOutcome {
  rows: GridRow[];
  /** Сколько ячеек реально изменилось. */
  applied: number;
  /** Строк не хватило — столько строк вставки отброшено. */
  droppedRows: number;
  /** Колонок не хватило справа — столько колонок отброшено. */
  droppedColumns: number;
  /** Значения, отклонённые как нечисловые в числовой колонке. */
  rejectedCells: number;
  /** Ячейки, пропущенные из-за нередактируемой колонки. */
  skippedReadonly: number;
}

/** Разбор того, что Excel кладёт в буфер: строки — \n, ячейки — табуляция. */
export function parseTsv(text: string): string[][] {
  if (text === '') return [];
  const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  // Хвостовой перевод строки Excel добавляет всегда — пустую строку от него не считаем.
  const lines = normalized.endsWith('\n') ? normalized.slice(0, -1) : normalized;
  if (lines === '') return [];
  return lines.split('\n').map((line) => line.split('\t'));
}

export function toTsv(matrix: unknown[][]): string {
  return matrix
    .map((row) => row.map((cell) => (cell === null || cell === undefined ? '' : String(cell))).join('\t'))
    .join('\n');
}

/** Прямоугольный кусок таблицы — для копирования в буфер. */
export function extractRange(
  rows: GridRow[],
  columns: EditorColumn[],
  range: { top: number; left: number; bottom: number; right: number },
): unknown[][] {
  const top = Math.max(0, Math.min(range.top, range.bottom));
  const bottom = Math.min(rows.length - 1, Math.max(range.top, range.bottom));
  const left = Math.max(0, Math.min(range.left, range.right));
  const right = Math.min(columns.length - 1, Math.max(range.left, range.right));

  const result: unknown[][] = [];
  for (let r = top; r <= bottom; r++) {
    const line: unknown[] = [];
    for (let c = left; c <= right; c++) {
      line.push(rows[r]?.[columns[c].key] ?? '');
    }
    result.push(line);
  }
  return result;
}

/**
 * Наложить вставленный кусок на строки начиная с якорной ячейки.
 *
 * `rows` не мутируются: возвращается новый массив, где изменены только
 * затронутые строки — так React не перерисовывает таблицу целиком.
 */
export function applyPaste(params: {
  rows: GridRow[];
  columns: EditorColumn[];
  anchorRow: number;
  anchorColumn: number;
  matrix: string[][];
  recalc?: (row: GridRow, changedKey: string, columns: EditorColumn[]) => GridRow;
}): PasteOutcome {
  const { rows, columns, anchorRow, anchorColumn, matrix, recalc } = params;
  const outcome: PasteOutcome = {
    rows, applied: 0, droppedRows: 0, droppedColumns: 0,
    rejectedCells: 0, skippedReadonly: 0,
  };

  if (matrix.length === 0 || rows.length === 0 || columns.length === 0) return outcome;
  if (anchorRow < 0 || anchorColumn < 0) return outcome;

  const availableRows = rows.length - anchorRow;
  const availableCols = columns.length - anchorColumn;
  outcome.droppedRows = Math.max(0, matrix.length - availableRows);
  outcome.droppedColumns = Math.max(
    0,
    Math.max(...matrix.map((line) => line.length)) - availableCols,
  );

  const next = [...rows];
  const usedRows = Math.min(matrix.length, availableRows);

  for (let r = 0; r < usedRows; r++) {
    const targetIndex = anchorRow + r;
    let row = { ...next[targetIndex] };
    let rowTouched = false;
    const usedCols = Math.min(matrix[r].length, availableCols);

    for (let c = 0; c < usedCols; c++) {
      const column = columns[anchorColumn + c];
      if (!column.editable || column.computed) {
        outcome.skippedReadonly += 1;
        continue;
      }

      const raw = matrix[r][c];
      let value: unknown = raw;
      if (column.numeric) {
        const parsed = toNumber(raw);
        if (parsed === null && raw.trim() !== '') {
          // Нечисло в числовой колонке — старое значение сохраняем.
          outcome.rejectedCells += 1;
          continue;
        }
        value = parsed;
      }

      if (row[column.key] === value) continue;
      row[column.key] = value;
      if (recalc) row = recalc(row, column.key, columns);
      rowTouched = true;
      outcome.applied += 1;
    }

    if (rowTouched) next[targetIndex] = row;
  }

  outcome.rows = outcome.applied > 0 ? next : rows;
  return outcome;
}

/** Человеческое описание того, что произошло при вставке. */
export function describePaste(outcome: PasteOutcome): string | null {
  if (outcome.applied === 0 && outcome.droppedRows === 0
      && outcome.rejectedCells === 0 && outcome.skippedReadonly === 0) {
    return null;
  }
  const parts = [`Вставлено значений: ${outcome.applied}`];
  if (outcome.droppedRows > 0) {
    parts.push(`не хватило строк — отброшено ${outcome.droppedRows}`);
  }
  if (outcome.droppedColumns > 0) {
    parts.push(`не хватило столбцов — отброшено ${outcome.droppedColumns}`);
  }
  if (outcome.rejectedCells > 0) {
    parts.push(`не число — пропущено ${outcome.rejectedCells}`);
  }
  if (outcome.skippedReadonly > 0) {
    parts.push(`нередактируемые ячейки — пропущено ${outcome.skippedReadonly}`);
  }
  return parts.join(', ');
}
