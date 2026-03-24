import React, { useEffect, useState } from 'react';
import { listVersions, restoreVersion, VersionInfo } from '../api/projects';

interface Props {
  taskId: string;
  open: boolean;
  onClose: () => void;
  onRestored?: () => void;
}

const CHANGE_TYPE_LABEL: Record<string, string> = {
  before_optimization: 'До оптимизации',
  analogue_applied:    'Аналог применён',
  analogue_reverted:   'Аналог отменён',
  manual:              'Ручное изменение',
};

const VersionHistoryDrawer: React.FC<Props> = ({ taskId, open, onClose, onRestored }) => {
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    listVersions(taskId)
      .then(setVersions)
      .finally(() => setLoading(false));
  }, [open, taskId]);

  const handleRestore = async (versionId: string) => {
    if (!confirm('Откатить смету к этой версии? Текущие изменения будут потеряны.')) return;
    setRestoring(versionId);
    try {
      await restoreVersion(taskId, versionId);
      onRestored?.();
      onClose();
    } finally {
      setRestoring(null);
    }
  };

  if (!open) return null;

  return (
    <>
      {/* Overlay */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 100,
        }}
      />

      {/* Drawer */}
      <div
        style={{
          position: 'fixed', right: 0, top: 0, bottom: 0, width: 420,
          background: '#fff', zIndex: 101, boxShadow: '-4px 0 24px rgba(0,0,0,0.1)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '18px 20px', borderBottom: '1px solid #e5e7eb',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ fontWeight: 700, fontSize: 16, color: '#111827' }}>
            История изменений
          </span>
          <button
            onClick={onClose}
            style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              fontSize: 20, color: '#6b7280', lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 20px' }}>
          {loading && (
            <p style={{ color: '#6b7280', fontSize: 14 }}>Загрузка истории...</p>
          )}
          {!loading && versions.length === 0 && (
            <p style={{ color: '#9ca3af', fontSize: 14 }}>
              История изменений пуста. Она появится после первой оптимизации или применения аналога.
            </p>
          )}
          {versions.map((v, idx) => (
            <div
              key={v.id}
              style={{
                marginBottom: 16,
                border: '1px solid #e5e7eb',
                borderRadius: 10,
                overflow: 'hidden',
              }}
            >
              {/* Version header */}
              <div style={{
                background: '#f9fafb',
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontWeight: 600, fontSize: 13, color: '#111827' }}>
                    Версия {v.version_number}
                    {idx === 0 && (
                      <span style={{
                        marginLeft: 8, fontSize: 11, background: '#dbeafe',
                        color: '#1d4ed8', borderRadius: 6, padding: '1px 7px',
                      }}>
                        текущая
                      </span>
                    )}
                  </span>
                  <span style={{ fontSize: 12, color: '#6b7280' }}>
                    {CHANGE_TYPE_LABEL[v.change_type || ''] || v.change_type || 'Изменение'}
                    {' · '}
                    {new Date(v.created_at).toLocaleString('ru-RU')}
                  </span>
                </div>
                {idx > 0 && (
                  <button
                    disabled={restoring === v.id}
                    onClick={() => handleRestore(v.id)}
                    style={{
                      border: '1px solid #d1d5db',
                      background: restoring === v.id ? '#f3f4f6' : '#fff',
                      borderRadius: 7, padding: '5px 12px',
                      cursor: restoring === v.id ? 'not-allowed' : 'pointer',
                      fontSize: 12, color: '#374151', whiteSpace: 'nowrap',
                    }}
                  >
                    {restoring === v.id ? 'Откат...' : '↩ Откатить'}
                  </button>
                )}
              </div>

              {/* Description */}
              {v.change_description && (
                <div style={{ padding: '8px 14px', fontSize: 13, color: '#4b5563' }}>
                  {v.change_description}
                </div>
              )}

              {/* Stats */}
              <div style={{ padding: '6px 14px 10px', fontSize: 12, color: '#9ca3af' }}>
                {v.items_count} позиций
                {' · '}
                {v.created_by === 'auto' ? '⚡ автоматически' : '✏️ вручную'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
};

export default VersionHistoryDrawer;
