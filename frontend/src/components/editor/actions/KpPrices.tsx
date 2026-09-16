import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Tags } from 'lucide-react';

import { listCardKpRequests } from '../../../api/kpRequests';
import type { VersionBrief } from '../../../api/documents';
import KpApplyDialog from '../../kp/KpApplyDialog';
import Hint from '../Hint';
import type { KpApplyResult } from '../../../types/kp';

/**
 * «Цены из КП» в редакторе оптимизации (план plans/2026-09-14-zapros-kp.md,
 * фаза 8; критерий 30 спецификации).
 *
 * Кнопка активна, когда у карточки есть завершённые запросы КП и у оптимизации
 * есть строки. Есть ли в завершённых запросах подтверждённые цены, знает только
 * сервер — это покажет предпросмотр («Нет строк, которым можно поставить цену»).
 *
 * Цены ложатся поверх **последней неоткатанной** версии: активной в понимании
 * сервера может быть V0, поэтому версия выбирается здесь явно (проблема 30).
 * С непринятыми правками кнопка неактивна: новая версия строится из
 * сохранённых строк, и переход на неё молча выбросил бы черновик.
 */

interface Props {
  cardId: string;
  versions: VersionBrief[];
  rowsCount: number;
  isDirty: boolean;
  onApplied: (result: KpApplyResult) => void;
  onNotice: (message: string) => void;
}

/** Последняя неоткатанная версия — источник цен из КП. */
export function latestAliveVersion(versions: VersionBrief[]): VersionBrief | null {
  let latest: VersionBrief | null = null;
  for (const v of versions) {
    if (v.is_rolled_back) continue;
    if (!latest || v.version_number > latest.version_number) latest = v;
  }
  return latest;
}

const KpPrices: React.FC<Props> = ({
  cardId, versions, rowsCount, isDirty, onApplied, onNotice,
}) => {
  const [doneCount, setDoneCount] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listCardKpRequests(cardId)
      .then((list) => {
        if (!cancelled) setDoneCount(list.filter((r) => r.status === 'done').length);
      })
      .catch(() => { if (!cancelled) setDoneCount(0); });
    return () => { cancelled = true; };
  }, [cardId]);

  const latest = useMemo(() => latestAliveVersion(versions), [versions]);

  let reason: string | null = null;
  if (doneCount === null) reason = 'Проверяю завершённые запросы КП…';
  else if (doneCount === 0) reason = 'Нет завершённых запросов КП по этой смете';
  else if (rowsCount === 0) reason = 'В оптимизации нет строк';
  else if (!latest) reason = 'Нет версии оптимизации, к которой можно применить цены';
  else if (isDirty) reason = 'Сначала примените или отмените правки в таблице';

  const handleApplied = useCallback((result: KpApplyResult) => {
    setOpen(false);
    onNotice(`Цены из КП применены: строк ${result.applied_rows}, новая версия V${result.version_number}`);
    onApplied(result);
  }, [onApplied, onNotice]);

  return (
    <>
      <Hint
        align="start"
        text={reason ?? `Поставить в оптимизацию цены из завершённых запросов КП (${doneCount}): `
          + 'сначала предпросмотр, затем новая версия «Цены из КП»'}
      >
        <button
          type="button"
          className="de-btn"
          onClick={() => setOpen(true)}
          disabled={reason !== null}
        >
          <Tags size={14} />
          Цены из КП
        </button>
      </Hint>

      {open && latest && (
        <KpApplyDialog
          cardId={cardId}
          versionId={latest.id}
          onClose={() => setOpen(false)}
          onApplied={handleApplied}
        />
      )}
    </>
  );
};

export default KpPrices;
