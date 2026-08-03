import React from 'react';
import { AlertTriangle, Eye, GitCompare, Users } from 'lucide-react';
import { LockInfo, ReadonlyReason, SectionDivergence } from '../../api/documents';

const money = (value: number) => `${Math.round(value).toLocaleString('ru-RU')} ₽`;

const READONLY_TEXT: Record<ReadonlyReason, string> = {
  task_processing: 'Идёт расчёт — документ открыт только для просмотра. Правки станут доступны, когда расчёт закончится.',
  input_readonly: 'Это исходный файл заказчика. Он открыт только для просмотра и никогда не перезаписывается.',
  no_permission: 'У вас нет прав на изменение этого документа — только просмотр.',
};

export const ReadonlyBanner: React.FC<{ reason: ReadonlyReason }> = ({ reason }) => (
  <div className="de-banner de-banner-info">
    <Eye size={15} />
    <span>{READONLY_TEXT[reason]}</span>
  </div>
);

export const PresenceBanner: React.FC<{ lock: LockInfo }> = ({ lock }) => (
  <div className="de-banner de-banner-warn">
    <Users size={15} />
    <span>
      <strong>{lock.user_name}</strong> сейчас редактирует этот документ.
      Сохраняйте с осторожностью — вы можете перекрыть чужие правки.
    </span>
  </div>
);

/**
 * Раздел сводной и смета показывают разное.
 *
 * Так выглядят разделы, собранные до перехода на общие строки: раздел был
 * отдельной копией и мог годами жить своими числами. Затирать нельзя ни ту, ни
 * другую сторону — в разделе работа человека, в смете результат расчёта, —
 * поэтому обе показаны цифрами, а выбирает человек.
 */
export const SummaryDivergenceBanner: React.FC<{
  divergence: SectionDivergence;
  onResolve: (prefer: 'section' | 'estimate') => void;
}> = ({ divergence, onResolve }) => (
  <div className="de-banner de-banner-warn" data-testid="summary-divergence">
    <GitCompare size={15} />
    <span>
      Раздел и смета разошлись: в разделе {divergence.section_rows} строк на{' '}
      {money(divergence.section_total)}, в смете {divergence.estimate_rows} строк на{' '}
      {money(divergence.estimate_total)}. Пока не выберете, ничего не меняется.
    </span>
    <button className="de-banner-action" onClick={() => onResolve('section')}>
      Верны правки раздела
    </button>
    <button className="de-banner-action" onClick={() => onResolve('estimate')}>
      Верны строки сметы
    </button>
  </div>
);

export const ConflictBanner: React.FC<{ message: string; onReload: () => void }> = ({
  message, onReload,
}) => (
  <div className="de-banner de-banner-error">
    <AlertTriangle size={15} />
    <span>{message}</span>
    <button className="de-banner-action" onClick={onReload}>Перезагрузить</button>
  </div>
);
