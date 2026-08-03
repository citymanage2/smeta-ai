import { EditorAdapter, GridRow } from './adapters/types';

/**
 * Операции над строками, общие для всех типов документов.
 *
 * Вынесены из компонента отдельно: это чистые функции над списком строк, их
 * можно проверить тестами без отрисовки таблицы.
 */

/**
 * Перенести строку мышкой: `key` встаёт выше или ниже `targetKey`.
 *
 * Порядок строк в смете — это порядок в документе и в скачиваемом файле,
 * поэтому переносится ровно одна строка, а остальные сохраняют свой порядок.
 */
export function moveRow(
  rows: GridRow[],
  key: string,
  targetKey: string,
  above: boolean,
): GridRow[] {
  if (key === targetKey) return rows;

  const from = rows.findIndex((row) => row.__key === key);
  const target = rows.findIndex((row) => row.__key === targetKey);
  if (from < 0 || target < 0) return rows;

  const without = rows.filter((_, index) => index !== from);
  // Позицию цели ищем уже в списке без перетаскиваемой строки: иначе при
  // переносе сверху вниз строка встала бы на один шаг мимо.
  const at = without.findIndex((row) => row.__key === targetKey);
  const insertAt = above ? at : at + 1;
  return [...without.slice(0, insertAt), rows[from], ...without.slice(insertAt)];
}

/**
 * Удалить отмеченные строки. В смете удаление работы уносит её материалы:
 * материал без своей работы — мусор, который потом ищут руками.
 */
export function removeRowsCascade(
  rows: GridRow[],
  selectedKeys: Set<string>,
  adapter: EditorAdapter,
): GridRow[] {
  const doomed = new Set(selectedKeys);

  if (adapter.rowFormat === 'estimate') {
    for (const row of rows) {
      if (adapter.rowKind(row) !== 'work') continue;
      if (!doomed.has(row.__key)) continue;
      const workId = String(row.lineage_id ?? row.__key);
      for (const candidate of rows) {
        const parent = candidate.work_row_id;
        if (parent != null && (String(parent) === workId || String(parent) === row.__key)) {
          doomed.add(candidate.__key);
        }
      }
    }
  }

  return rows.filter((row) => !doomed.has(row.__key));
}
