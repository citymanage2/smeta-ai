import { EstimateRow } from '../types';
import { formatQty } from './formatQty';

export interface RecalcResult {
  rows: EstimateRow[];
  recalcedIds: string[];
  overriddenIds: string[];
}

/**
 * Пересчитывает qty всех материалов, привязанных к работе changedWorkId.
 * Работает по нормативу qty_per_work_unit. Включает строки с qty_overridden=true.
 * Сохраняет qty_manual_backup только если он ещё не был задан.
 */
export function applyWorkQuantityChange(
  rows: EstimateRow[],
  changedWorkId: string,
  newQty: number | null,
): RecalcResult {
  const recalcedIds: string[] = [];
  const overriddenIds: string[] = [];

  const newRows = rows.map((r) => {
    if (r.type !== 'material' || r.work_row_id !== changedWorkId) return r;
    if (r.qty_per_work_unit == null) return r;

    const autoQty = (newQty ?? 0) * r.qty_per_work_unit;
    const wasOverridden = r.qty_overridden === true;

    recalcedIds.push(r.id);
    if (wasOverridden) overriddenIds.push(r.id);

    return {
      ...r,
      qty: autoQty,
      qty_manual_backup:
        wasOverridden && r.qty_manual_backup == null ? r.qty : r.qty_manual_backup,
    };
  });

  return { rows: newRows, recalcedIds, overriddenIds };
}

/**
 * Строит second-line комментарий для ячейки qty материала.
 * Возвращает пустую строку если нормативов нет.
 */
export function buildNormComment(row: EstimateRow, workUnit?: string): string {
  if (row.type !== 'material') return '';
  if (row.qty_per_work_unit == null) return '';

  if (row.qty_overridden) return 'задано вручную';

  const qty = row.qty ?? 0;
  const norm = row.qty_per_work_unit;
  const matUnit = row.unit || '';
  const perUnit = workUnit || 'ед.';

  return `авто: ${formatQty(qty)} ${matUnit} (норм. ${norm} на ${perUnit})`.trim();
}
