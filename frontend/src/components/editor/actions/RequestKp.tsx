import React, { useCallback, useState } from 'react';
import { Send } from 'lucide-react';

import RequestKpDialog from '../../kp/RequestKpDialog';
import Hint from '../Hint';
import {
  KP_CATEGORY_LABELS, KP_DEPARTMENT_LABELS, KpRequestBrief, KpSourceKind,
} from '../../../types/kp';

/**
 * «Запросить КП» — поставить отделу производства работ запрос по отмеченным
 * позициям (план plans/2026-09-14-zapros-kp.md, фаза 3).
 *
 * Документ действие не меняет: позиции запроса — снимок сохранённого
 * документа на сервере. Поэтому черновик кнопку не блокирует, а только
 * предупреждает в окне, что непринятые правки в запрос не попадут.
 *
 * Ключи строк приходят из стора редактора, где в свёрнутом режиме лежат
 * настоящие строки группы, а не ключ свёрнутой строки, — выделение группы
 * даёт все её строки.
 */

interface Props {
  cardId: string;
  kind: KpSourceKind;
  versionId: string | null;
  selectedKeys: Set<string>;
  isDirty: boolean;
  onNotice: (message: string) => void;
  onCreated?: (requests: KpRequestBrief[]) => void;
}

const RequestKp: React.FC<Props> = ({
  cardId, kind, versionId, selectedKeys, isDirty, onNotice, onCreated,
}) => {
  const [rowIds, setRowIds] = useState<string[] | null>(null);
  const count = selectedKeys.size;

  const handleCreated = useCallback((requests: KpRequestBrief[]) => {
    setRowIds(null);
    const parts = requests.map((request) => (
      `${KP_CATEGORY_LABELS[request.category].toLowerCase()} → ${KP_DEPARTMENT_LABELS[request.category]}`
      + ` (позиций: ${request.items_count})`
    ));
    onNotice(parts.length > 0 ? `Запрос КП отправлен: ${parts.join('; ')}` : 'Запрос КП отправлен');
    onCreated?.(requests);
  }, [onNotice, onCreated]);

  return (
    <>
      <Hint
        align="start"
        text={count === 0
          ? 'Запросить КП у отдела производства работ: сначала отметьте позиции галочками'
          : `Запросить КП по отмеченным позициям (${count}): материалы уйдут в снабжение, работы — подрядчикам`}
      >
        <button
          type="button"
          className="de-btn"
          onClick={() => setRowIds(Array.from(selectedKeys))}
          disabled={count === 0}
        >
          <Send size={14} />
          Запросить КП{count > 0 ? ` (${count})` : ''}
        </button>
      </Hint>

      {rowIds && (
        <RequestKpDialog
          cardId={cardId}
          kind={kind}
          versionId={versionId}
          rowIds={rowIds}
          isDirty={isDirty}
          onClose={() => setRowIds(null)}
          onCreated={handleCreated}
        />
      )}
    </>
  );
};

export default RequestKp;
