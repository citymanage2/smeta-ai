import { useCallback, useMemo, useState } from 'react';
import { RotateCcw, Wand2 } from 'lucide-react';

import { fixEmptyPrices, repriceEstimateItem } from '../../../api/tasks';
import { GridRow } from '../adapters/types';

/**
 * Действия с ценами — только для сметы и версий оптимизации.
 *
 * Раньше жили на странице задачи рядом с её собственной таблицей. Таблица
 * уехала в единый редактор — действия едут за ней.
 *
 * Оба действия пишут смету на сервере и поднимают `rev` документа. Поэтому при
 * непринятых правках они заблокированы: иначе правки человека сразу ушли бы в
 * конфликт, а он бы не понял, почему.
 */

interface Props {
  taskId: string;
  rows: GridRow[];
  selectedKeys: Set<string>;
  isDirty: boolean;
  onReload: () => void;
  onNotice: (message: string) => void;
  onStarted?: () => void;
}

/** Позиция-вычет (объём меньше нуля) корректирует объём соседней работы. */
function isDeduction(row: GridRow): boolean {
  const qty = Number(row.qty);
  return Number.isFinite(qty) && qty < 0;
}

/** Пустая цена — это отсутствие цены у обычной позиции. У вычета её и не должно быть. */
export function hasEmptyPrice(row: GridRow): boolean {
  if (isDeduction(row)) return false;
  const kind = String(row.type ?? '');
  if (kind === 'Работа' || kind === 'work') return !row.price_work;
  if (kind === 'Материал' || kind === 'material') return !row.price_material;
  return false;
}

const PriceActions: React.FC<Props> = ({
  taskId, rows, selectedKeys, isDirty, onReload, onNotice, onStarted,
}) => {
  const [busy, setBusy] = useState(false);

  const emptyCount = useMemo(() => rows.filter(hasEmptyPrice).length, [rows]);

  // Индекс строки в документе = индекс позиции в смете на сервере: обе стороны
  // читают один и тот же порядок строк рабочей версии.
  const repriceIndex = useMemo(() => {
    if (selectedKeys.size !== 1) return -1;
    const key = [...selectedKeys][0];
    const index = rows.findIndex((row) => row.__key === key);
    if (index < 0 || isDeduction(rows[index])) return -1;
    return index;
  }, [rows, selectedKeys]);

  const handleFix = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fixEmptyPrices(taskId);
      if (res.status === 'no_empty_items') {
        onNotice('Пустых цен не осталось');
      } else {
        onNotice(`Идёт подбор цен для ${res.empty_count} позиций — документ обновится по готовности`);
        onStarted?.();
      }
    } catch {
      onNotice('Не удалось запустить подбор цен');
    } finally {
      setBusy(false);
    }
  }, [taskId, onNotice, onStarted]);

  const handleReprice = useCallback(async () => {
    if (repriceIndex < 0) return;
    setBusy(true);
    try {
      const res = await repriceEstimateItem(taskId, repriceIndex);
      const price = res.work_price ?? res.material_price;
      onNotice(price != null ? `Новая цена: ${price} ₽` : 'Цена не найдена');
      // Цену записал сервер и поднял rev — состояние перечитываем, а не угадываем.
      onReload();
    } catch {
      onNotice('Не удалось пересчитать цену');
    } finally {
      setBusy(false);
    }
  }, [taskId, repriceIndex, onNotice, onReload]);

  const dirtyHint = isDirty ? 'Сначала примените правки' : undefined;

  return (
    <div className="de-price-actions">
      {emptyCount > 0 && (
        <button
          className="de-btn"
          onClick={handleFix}
          disabled={busy || isDirty}
          title={dirtyHint ?? 'Найти цены для позиций, у которых цены нет'}
        >
          <Wand2 size={14} />
          Исправить пустые цены ({emptyCount})
        </button>
      )}
      <button
        className="de-btn"
        onClick={handleReprice}
        disabled={busy || isDirty || repriceIndex < 0}
        title={
          dirtyHint
          ?? (repriceIndex < 0
            ? 'Выберите одну позицию (вычету цена не нужна)'
            : 'Найти актуальную цену для выбранной позиции')
        }
      >
        <RotateCcw size={14} />
        Цена
      </button>
    </div>
  );
};

export default PriceActions;
