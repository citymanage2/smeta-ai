import React, { useCallback, useEffect, useState } from 'react';
import { Bot, User as UserIcon, X } from 'lucide-react';
import {
  DocumentRef, Reconciliation, ReconciliationCell, ReconciliationRow,
  getDocumentReconciliation,
} from '../../api/documents';
import { LumaSpin } from '../ui/LumaSpin';
import { formatMoney, formatDecimal } from '../../utils/formatNumber';

interface Props {
  documentRef: DocumentRef;
  onClose: () => void;
}

function value(raw: string | null): string {
  return raw === null || raw === '' ? '—' : raw;
}

function money(amount: number | null): string {
  return amount === null ? '—' : `${formatMoney(amount)} ₽`;
}

/** «−13,79%» либо пусто, когда сравнивать не с чем (ноль в знаменателе). */
function percent(pct: number | null): string {
  if (pct === null) return '';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toString().replace('.', ',')}%`;
}

const STATUS_LABEL: Record<ReconciliationRow['status'], string> = {
  changed: '',
  added: 'позиции не было у ИИ',
  removed: 'позиция ИИ убрана',
};

/**
 * Сверка расчёта: что выдал ИИ, что из этого сделал сам сервис и что поправил
 * человек.
 *
 * Три колонки, а не две, потому что между ответом модели и правкой человека
 * строку меняют подбор цен по прайсу, проверка единиц, коэффициент и
 * оптимизация. Без разделения «сервис» / «человек» ошибки одного назначались бы
 * другому.
 */
export const ReconciliationPanel: React.FC<Props> = ({ documentRef, onClose }) => {
  const [data, setData] = useState<Reconciliation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getDocumentReconciliation(documentRef));
      setError('');
    } catch {
      setError('Не удалось загрузить сверку.');
    } finally {
      setLoading(false);
    }
  }, [documentRef]);

  useEffect(() => { load(); }, [load]);

  const renderCell = (cell: ReconciliationCell, index: number) => {
    const byHuman = cell.changed_by === 'human';
    return (
      <div key={index} className="de-recon-cell">
        <div className="de-recon-cell-head">
          <span className="de-recon-field">{cell.field}</span>
          <span className={`de-recon-author de-recon-author-${cell.changed_by}`}>
            {byHuman ? <UserIcon size={11} /> : <Bot size={11} />}
            <span>{byHuman ? (cell.user_name || 'человек') : 'сервис'}</span>
          </span>
        </div>

        <div className="de-recon-values">
          <span className="de-recon-step">
            <span className="de-recon-step-label">ИИ</span>
            <span className="de-recon-step-value">{value(cell.ai_value)}</span>
          </span>
          {/* Шаг сервиса показывается, только когда он что-то изменил: иначе
              это то же число дважды и лишний шум в узкой панели. */}
          {cell.service_value !== cell.ai_value && (
            <span className="de-recon-step">
              <span className="de-recon-step-label">сервис</span>
              <span className="de-recon-step-value">{value(cell.service_value)}</span>
            </span>
          )}
          <span className="de-recon-step de-recon-step-final">
            <span className="de-recon-step-label">итог</span>
            <strong className="de-recon-step-value">{value(cell.current_value)}</strong>
          </span>
        </div>

        {(cell.delta !== null || cell.price_source) && (
          <div className="de-recon-meta">
            {cell.delta !== null && (
              <span className={cell.delta < 0 ? 'de-recon-down' : 'de-recon-up'}>
                {cell.delta > 0 ? '+' : ''}{formatDecimal(cell.delta)} {percent(cell.delta_pct)}
              </span>
            )}
            {cell.price_source && (
              <span className="de-recon-source">цена из: {cell.price_source}</span>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside className="de-history de-recon">
      <div className="de-history-head">
        <span className="de-history-title">Сверка с расчётом ИИ</span>
        <button className="de-icon-btn" onClick={onClose} title="Закрыть">
          <X size={14} />
        </button>
      </div>

      {loading && <div className="de-history-empty"><LumaSpin size="sm" color="#64748b" /></div>}
      {error && <div className="de-history-error">{error}</div>}

      {!loading && !error && data && !data.has_baseline && (
        <div className="de-history-empty">
          Расчёт ИИ по этому документу не сохранён — он считался до появления
          сверки. Сравнить не с чем; новые расчёты будут сверяться.
        </div>
      )}

      {!loading && !error && data?.has_baseline && (
        <>
          <div className="de-recon-summary">
            {data.totals.ai_total !== null && (
              <div className="de-recon-total">
                <span>ИИ насчитал</span>
                <span>{money(data.totals.ai_total)}</span>
              </div>
            )}
            {data.totals.current_total !== null && (
              <div className="de-recon-total">
                <span>Сейчас</span>
                <span><strong>{money(data.totals.current_total)}</strong></span>
              </div>
            )}
            {data.totals.delta !== null && data.totals.delta !== 0 && (
              <div className={`de-recon-total ${data.totals.delta < 0 ? 'de-recon-down' : 'de-recon-up'}`}>
                <span>Разница</span>
                <span>
                  {data.totals.delta > 0 ? '+' : ''}{money(data.totals.delta)}
                  {' '}{percent(data.totals.delta_pct)}
                </span>
              </div>
            )}
            <div className="de-recon-counts">
              ячеек поправил человек: {data.counts.cells_by_human} · изменил
              сервис: {data.counts.cells_by_service}
            </div>
            {data.baseline_truncated && (
              <div className="de-history-note">
                ИИ выдал {data.ai_row_count} строк, сверено {data.compared_row_count} —
                снимок сохранён не целиком, остальные строки в сверку не попали.
              </div>
            )}
            {data.match_mode === 'name_unit' && (
              <div className="de-history-note">
                Строки документа пересобраны заново, поэтому сверка идёт по
                наименованию и единице. Позиции с одинаковым названием не
                сопоставлены — их лучше проверить глазами.
              </div>
            )}
          </div>

          {data.rows.length === 0 && (
            <div className="de-history-empty">
              Документ совпадает с расчётом ИИ — ничего не меняли.
            </div>
          )}

          <div className="de-history-list">
            {data.rows.map((row) => (
              <div key={row.row_key} className="de-recon-row">
                <div className="de-recon-row-head">
                  {row.row_number !== null && (
                    <span className="de-history-row">стр. {row.row_number}</span>
                  )}
                  <span className="de-recon-name">{row.row_name || 'без наименования'}</span>
                </div>
                {row.status !== 'changed' && (
                  <div className={`de-recon-status de-recon-status-${row.status}`}>
                    {STATUS_LABEL[row.status]}
                    {row.changed_by === 'human' ? ' (человек)' : ' (сервис)'}
                  </div>
                )}
                {row.cells.map(renderCell)}
              </div>
            ))}
            {data.truncated && (
              <div className="de-history-note">
                Показаны первые расхождения. Их слишком много, чтобы уместить все.
              </div>
            )}
          </div>
        </>
      )}
    </aside>
  );
};

export default ReconciliationPanel;
