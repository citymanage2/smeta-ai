import React, { useCallback, useMemo, useState } from 'react';
import { Sparkles } from 'lucide-react';

import { AnalogRowIn, DocumentRef, startAnalogs } from '../../../api/documents';
import { GridRow, RowKind, toNumber } from '../adapters/types';
import Hint from '../Hint';

/**
 * «Найти аналоги» — запуск фонового поиска более дешёвой замены.
 *
 * Поиск идёт в интернете и стоит денег, а потолка позиций за запуск нет
 * (решение пользователя 2026-08-03). Единственный тормоз — подтверждение с
 * честной оценкой: сколько позиций, сколько это займёт и что поиск платный.
 */

interface Props {
  documentRef: DocumentRef;
  rows: GridRow[];
  selectedKeys: Set<string>;
  rowKind: (row: GridRow) => RowKind;
  /** Поиск по этому документу уже идёт — второй запускать нельзя. */
  busy: boolean;
  versionId?: string;
  onStarted: () => void;
  onNotice: (message: string) => void;
}

// Те же величины, что на сервере (`analogs_service`): пачка по 5 позиций,
// примерно 45 секунд на пачку, около двух поисков на позицию.
const BATCH_SIZE = 5;
const SECONDS_PER_BATCH = 45;
const SEARCHES_PER_POSITION = 2;

export function estimateAnalogsEffort(positions: number): {
  positions: number; searches: number; minutes: number;
} {
  if (positions <= 0) return { positions: 0, searches: 0, minutes: 0 };
  const batches = Math.ceil(positions / BATCH_SIZE);
  return {
    positions,
    searches: positions * SEARCHES_PER_POSITION,
    minutes: Math.max(1, Math.round((batches * SECONDS_PER_BATCH) / 60)),
  };
}

/** Выделенные строки → позиции для поиска. Разделы и строки без цены отсеиваются. */
export function selectedToAnalogRows(
  rows: GridRow[],
  selectedKeys: Set<string>,
  rowKind: (row: GridRow) => RowKind,
): AnalogRowIn[] {
  const picked: AnalogRowIn[] = [];
  for (const row of rows) {
    if (!selectedKeys.has(row.__key)) continue;
    const kind = rowKind(row);
    if (kind !== 'work' && kind !== 'material') continue;
    const price = toNumber(kind === 'work' ? row.price_work : row.price_material);
    if (price === null || price <= 0) continue;
    picked.push({
      row_id: row.__key,
      name: String(row.name ?? '').trim(),
      unit: row.unit === null || row.unit === undefined ? null : String(row.unit),
      qty: toNumber(row.qty),
      price,
      kind,
    });
  }
  return picked;
}

const FindAnalogs: React.FC<Props> = ({
  documentRef, rows, selectedKeys, rowKind, busy, versionId, onStarted, onNotice,
}) => {
  const [starting, setStarting] = useState(false);

  const positions = useMemo(
    () => selectedToAnalogRows(rows, selectedKeys, rowKind),
    [rows, selectedKeys, rowKind],
  );

  const handleClick = useCallback(async () => {
    if (positions.length === 0) return;
    const effort = estimateAnalogsEffort(positions.length);
    const confirmed = window.confirm(
      `Будет обработано позиций: ${effort.positions}. Это займёт примерно `
      + `${effort.minutes} мин.\n\nПоиск идёт в интернете через ИИ и стоит денег `
      + `(примерно ${effort.searches} поисков). Продолжить?`,
    );
    if (!confirmed) return;

    setStarting(true);
    try {
      await startAnalogs(documentRef, positions, versionId);
      onNotice('Идёт поиск аналогов — результат появится здесь по готовности');
      onStarted();
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      onNotice(detail || 'Не удалось запустить поиск аналогов');
    } finally {
      setStarting(false);
    }
  }, [documentRef, positions, versionId, onStarted, onNotice]);

  return (
    <Hint
      align="start"
      text={
        busy
          ? 'Поиск аналогов уже идёт — дождитесь результата'
          : positions.length === 0
            ? 'Поиск замены подешевле: отметьте галочками позиции с ценой, и ИИ поищет им аналоги в интернете'
            : `Найти замену подешевле для отмеченных позиций (${positions.length}). Это предложения — в смету попадёт только то, что вы примете`
      }
    >
      <button
        className="de-btn"
        onClick={handleClick}
        disabled={busy || starting || positions.length === 0}
      >
        <Sparkles size={14} />
        Найти аналоги{positions.length > 0 ? ` (${positions.length})` : ''}
      </button>
    </Hint>
  );
};

export default FindAnalogs;
