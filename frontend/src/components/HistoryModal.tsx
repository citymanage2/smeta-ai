// frontend/src/components/HistoryModal.tsx
import React, { useState, useEffect } from 'react';
import { getTaskHistory, revertHistory } from '../api/tasks';
import { HistoryEntry } from '../types';

interface HistoryModalProps {
  taskId: string;
  onClose: () => void;
}

const OPERATION_ICONS: Record<string, string> = {
  optimization: '🔧',
  analog: '🔄',
  manual_edit: '✏️',
  revert: '⏮',
};

const OPERATION_LABELS: Record<string, string> = {
  optimization: 'Оптимизация',
  analog: 'Аналог',
  manual_edit: 'Редактирование',
  revert: 'Откат',
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const HistoryModal: React.FC<HistoryModalProps> = ({ taskId, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [fetchError, setFetchError] = useState('');
  const [revertingId, setRevertingId] = useState<string | null>(null);
  const [dependentEntries, setDependentEntries] = useState<
    Array<{ id: string; description: string; created_at: string }>
  >([]);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    loadHistory();
  }, [taskId]);

  async function loadHistory() {
    setLoading(true);
    setFetchError('');
    try {
      const data = await getTaskHistory(taskId);
      setEntries(data);
    } catch {
      setFetchError('Не удалось загрузить историю изменений');
    } finally {
      setLoading(false);
    }
  }

  async function handleRevertClick(entryId: string) {
    setActionPending(true);
    setActionError('');
    try {
      const result = await revertHistory(taskId, entryId, false);
      if (result.reverted) {
        onClose();
      } else if (result.warning) {
        setRevertingId(entryId);
        setDependentEntries(result.dependent_entries || []);
      }
    } catch {
      setActionError('Ошибка при попытке отката');
    } finally {
      setActionPending(false);
    }
  }

  async function handleConfirmRevert() {
    if (!revertingId) return;
    setActionPending(true);
    setActionError('');
    try {
      await revertHistory(taskId, revertingId, true);
      onClose();
    } catch {
      setActionError('Ошибка при выполнении отката');
    } finally {
      setActionPending(false);
    }
  }

  function cancelRevert() {
    setRevertingId(null);
    setDependentEntries([]);
    setActionError('');
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: '12px',
          padding: '24px',
          width: '560px',
          maxWidth: '95vw',
          maxHeight: '80vh',
          overflowY: 'auto',
          boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '20px',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: '#1e293b' }}>
            История изменений
          </h3>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: '22px',
              color: '#94a3b8',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Warning panel */}
        {revertingId && (
          <div
            style={{
              background: '#fef3c7',
              border: '1px solid #fcd34d',
              borderRadius: '8px',
              padding: '16px',
              marginBottom: '16px',
            }}
          >
            <p style={{ margin: '0 0 10px', fontWeight: 600, color: '#92400e' }}>
              Следующие изменения будут удалены:
            </p>
            <ul style={{ margin: '0 0 14px', paddingLeft: '20px' }}>
              {dependentEntries.map((d) => (
                <li key={d.id} style={{ fontSize: '13px', marginBottom: '4px', color: '#78350f' }}>
                  {d.description}{' '}
                  <span style={{ color: '#a16207' }}>({formatDate(d.created_at)})</span>
                </li>
              ))}
            </ul>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={cancelRevert}
                style={{
                  padding: '7px 16px',
                  background: '#f1f5f9',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                Отмена
              </button>
              <button
                onClick={handleConfirmRevert}
                disabled={actionPending}
                style={{
                  padding: '7px 16px',
                  background: '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: actionPending ? 'not-allowed' : 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                  opacity: actionPending ? 0.7 : 1,
                }}
              >
                {actionPending ? 'Откатываем...' : 'Подтвердить откат'}
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {(fetchError || actionError) && (
          <p style={{ color: '#dc2626', fontSize: '14px', marginBottom: '12px' }}>
            {fetchError || actionError}
          </p>
        )}

        {/* Loading */}
        {loading && (
          <p style={{ color: '#94a3b8', textAlign: 'center', padding: '20px 0' }}>
            Загрузка...
          </p>
        )}

        {/* Empty state */}
        {!loading && entries.length === 0 && !fetchError && (
          <p style={{ color: '#94a3b8', textAlign: 'center', padding: '20px 0' }}>
            Нет истории изменений
          </p>
        )}

        {/* Entry list */}
        {!loading &&
          entries.map((entry) => (
            <div
              key={entry.id}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                padding: '12px 0',
                borderBottom: '1px solid #f1f5f9',
              }}
            >
              <div style={{ flex: 1, marginRight: '12px' }}>
                <div style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>
                  {OPERATION_ICONS[entry.operation_type] ?? '•'}{' '}
                  {OPERATION_LABELS[entry.operation_type] ?? entry.operation_type}
                </div>
                <div style={{ fontSize: '13px', color: '#475569', marginTop: '2px' }}>
                  {entry.description}
                </div>
                <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                  {formatDate(entry.created_at)}
                </div>
              </div>
              {entry.operation_type !== 'revert' && !revertingId && (
                <button
                  onClick={() => handleRevertClick(entry.id)}
                  disabled={actionPending}
                  style={{
                    padding: '5px 12px',
                    background: '#fef2f2',
                    color: '#dc2626',
                    border: '1px solid #fecaca',
                    borderRadius: '8px',
                    cursor: actionPending ? 'not-allowed' : 'pointer',
                    fontSize: '12px',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    opacity: actionPending ? 0.6 : 1,
                  }}
                >
                  Откатить
                </button>
              )}
            </div>
          ))}
      </div>
    </div>
  );
};

export default HistoryModal;
