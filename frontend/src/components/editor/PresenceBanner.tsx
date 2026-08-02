import React from 'react';
import { AlertTriangle, Eye, Users } from 'lucide-react';
import { LockInfo, ReadonlyReason } from '../../api/documents';

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

export const ConflictBanner: React.FC<{ message: string; onReload: () => void }> = ({
  message, onReload,
}) => (
  <div className="de-banner de-banner-error">
    <AlertTriangle size={15} />
    <span>{message}</span>
    <button className="de-banner-action" onClick={onReload}>Перезагрузить</button>
  </div>
);
