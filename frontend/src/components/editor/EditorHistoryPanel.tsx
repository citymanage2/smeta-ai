import React, { useCallback, useEffect, useState } from 'react';
import { RotateCcw, X } from 'lucide-react';
import {
  DocumentRef, HistoryEntry, getDocumentHistory, revertDocument,
} from '../../api/documents';
import { LumaSpin } from '../ui/LumaSpin';

interface Props {
  documentRef: DocumentRef;
  canWrite: boolean;
  onClose: () => void;
  onReverted: () => void;
}

function formatMoment(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

/** История правок: кто, когда и что именно поменял, с возможностью откатиться. */
export const EditorHistoryPanel: React.FC<Props> = ({
  documentRef, canWrite, onClose, onReverted,
}) => {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reverting, setReverting] = useState<string | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setEntries(await getDocumentHistory(documentRef));
      setError('');
    } catch {
      setError('Не удалось загрузить историю.');
    } finally {
      setLoading(false);
    }
  }, [documentRef]);

  useEffect(() => { load(); }, [load]);

  const handleRevert = async (entry: HistoryEntry) => {
    setReverting(entry.id);
    try {
      await revertDocument(documentRef, entry.id);
      onReverted();
      await load();
    } catch {
      setError('Не удалось откатить. Возможно, документ уже изменили.');
    } finally {
      setReverting(null);
    }
  };

  return (
    <aside className="de-history">
      <div className="de-history-head">
        <span className="de-history-title">История правок</span>
        <button className="de-icon-btn" onClick={onClose} title="Закрыть">
          <X size={14} />
        </button>
      </div>

      {loading && <div className="de-history-empty"><LumaSpin size="sm" color="#64748b" /></div>}
      {error && <div className="de-history-error">{error}</div>}

      {!loading && entries.length === 0 && !error && (
        <div className="de-history-empty">Правок ещё не было</div>
      )}

      <div className="de-history-list">
        {entries.map((entry) => {
          const isOpen = expanded === entry.id;
          return (
            <div key={entry.id} className="de-history-item">
              <button
                className="de-history-item-head"
                onClick={() => setExpanded(isOpen ? null : entry.id)}
              >
                <span className="de-history-who">{entry.user_name || 'Система'}</span>
                <span className="de-history-when">{formatMoment(entry.created_at)}</span>
                <span className="de-history-count">
                  {entry.changes_count > 0 ? `${entry.changes_count} изм.` : entry.operation_type}
                </span>
              </button>

              {isOpen && (
                <div className="de-history-body">
                  {entry.changes.length === 0 && (
                    <div className="de-history-note">{entry.description}</div>
                  )}
                  {entry.changes.map((change, index) => (
                    <div key={index} className="de-history-change">
                      <span className="de-history-row">стр. {change.row_number}</span>
                      <span className="de-history-field">{change.field}</span>
                      <span className="de-history-values">
                        {formatValue(change.previous)} → <strong>{formatValue(change.new)}</strong>
                      </span>
                    </div>
                  ))}
                  {entry.changes_count > entry.changes.length && (
                    <div className="de-history-note">
                      …и ещё {entry.changes_count - entry.changes.length} изменений
                    </div>
                  )}
                  {canWrite && (
                    <button
                      className="de-history-revert"
                      onClick={() => handleRevert(entry)}
                      disabled={reverting === entry.id}
                    >
                      <RotateCcw size={12} />
                      {reverting === entry.id ? 'Возвращаю…' : 'Вернуть как было'}
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
};

export default EditorHistoryPanel;
