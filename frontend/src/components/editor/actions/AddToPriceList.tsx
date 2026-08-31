import React, { useCallback, useMemo, useState } from 'react';
import { BookmarkPlus } from 'lucide-react';

import { DocumentRef, addToPriceList } from '../../../api/documents';
import { GridRow, RowKind } from '../adapters/types';
import { PricePosition } from './priceInsert';
import Hint from '../Hint';

/**
 * «В прайс» — отправить выделенные позиции в общий прайс.
 *
 * Работы уходят к псевдо-подрядчику «Из смет», материалы — ценой; единицы
 * измерения приводит к одному виду сервер. Разделы не отправляются: цены у них
 * нет, в прайсе им нечего делать.
 *
 * Документ действие не меняет, поэтому черновик ему не мешает и `rev` не
 * двигается — в отличие от действий с ценами.
 */

interface Props {
  documentRef: DocumentRef;
  rows: GridRow[];
  selectedKeys: Set<string>;
  rowKind: (row: GridRow) => RowKind;
  onNotice: (message: string) => void;
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
}

/** Выделенные строки → позиции прайса. Тип строки решает, какая цена берётся. */
export function selectedToPositions(
  rows: GridRow[],
  selectedKeys: Set<string>,
  rowKind: (row: GridRow) => RowKind,
): PricePosition[] {
  const positions: PricePosition[] = [];
  for (const row of rows) {
    if (!selectedKeys.has(row.__key)) continue;
    const kind = rowKind(row);
    if (kind !== 'work' && kind !== 'material') continue;
    positions.push({
      kind,
      name: String(row.name ?? '').trim(),
      unit: row.unit === null || row.unit === undefined ? null : String(row.unit),
      price: toNumber(kind === 'work' ? row.price_work : row.price_material),
    });
  }
  return positions;
}

const AddToPriceList: React.FC<Props> = ({
  documentRef, rows, selectedKeys, rowKind, onNotice,
}) => {
  const [busy, setBusy] = useState(false);

  const positions = useMemo(
    () => selectedToPositions(rows, selectedKeys, rowKind),
    [rows, selectedKeys, rowKind],
  );

  const handleClick = useCallback(async () => {
    if (positions.length === 0) return;
    setBusy(true);
    try {
      const summary = await addToPriceList(documentRef, positions);
      const reasons = Object.entries(summary.skipped_reasons ?? {})
        .map(([reason, count]) => `${reason} — ${count}`)
        .join(', ');
      onNotice(
        `В прайс: добавлено ${summary.added}, обновлено ${summary.updated}, `
        + `пропущено ${summary.skipped}${reasons ? ` (${reasons})` : ''}`,
      );
    } catch {
      onNotice('Не удалось записать позиции в прайс');
    } finally {
      setBusy(false);
    }
  }, [documentRef, positions, onNotice]);

  return (
    <Hint
      align="start"
      text={
        positions.length === 0
          ? 'Занести позиции в общий прайс: сначала отметьте галочками работы и материалы с ценой'
          : `Занести отмеченные позиции (${positions.length}) в общий прайс — они станут доступны во всех сметах`
      }
    >
      <button
        className="de-btn"
        onClick={handleClick}
        disabled={busy || positions.length === 0}
      >
        <BookmarkPlus size={14} />
        В прайс{positions.length > 0 ? ` (${positions.length})` : ''}
      </button>
    </Hint>
  );
};

export default AddToPriceList;
