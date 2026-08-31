import React from 'react';
import { useNavigate } from 'react-router-dom';
import { PulseBucket, PulseBucketDetail, PulseTaskRow, getPulseBucket } from '../../api/dashboard';
import { TASK_TYPE_LABELS } from '../../types';
import { formatDuration, formatTokens, formatUsd } from '../../utils/usageMetrics';
import { SectionLoader } from '../ui/LumaSpin';

interface Props {
  bucket: PulseBucket;
  title: string;
  onClose: () => void;
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 12px',
  fontSize: 12,
  fontWeight: 600,
  color: '#64748b',
  borderBottom: '1px solid #e2e8f0',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  fontSize: 13,
  color: '#1e293b',
  borderBottom: '1px solid #f1f5f9',
};

const numStyle: React.CSSProperties = { ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap' };

/** Название задачи, как его назвал человек; без имени — тип стадии. */
function taskLabel(row: PulseTaskRow): string {
  const type = TASK_TYPE_LABELS[row.task_type] ?? row.task_type;
  return row.name?.trim() ? row.name : type;
}

const PulseTasksModal: React.FC<Props> = ({ bucket, title, onClose }) => {
  const navigate = useNavigate();
  const [data, setData] = React.useState<PulseBucketDetail | null>(null);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    let cancelled = false;
    setData(null);
    setError('');
    getPulseBucket(bucket)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError('Не удалось загрузить список задач');
      });
    return () => {
      cancelled = true;
    };
  }, [bucket]);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
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
          borderRadius: 12,
          padding: 24,
          width: 900,
          maxWidth: '95vw',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1e293b', margin: 0 }}>{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            style={{
              border: 'none',
              background: 'transparent',
              fontSize: 22,
              lineHeight: 1,
              color: '#94a3b8',
              cursor: 'pointer',
            }}
          >
            ×
          </button>
        </div>

        {!data && !error && <SectionLoader message="Загружаем задачи..." />}
        {error && <div style={{ fontSize: 13, color: '#dc2626' }}>{error}</div>}

        {data && (
          <>
            {/* Итоги — над таблицей: сколько задач, сколько времени и денег ушло. */}
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Total label="Задач" value={String(data.count)} />
              <Total label="Время выполнения" value={formatDuration(data.total_work_seconds)} />
              <Total label="Токены" value={formatTokens(data.total_tokens)} />
              <Total label="Стоимость" value={formatUsd(data.total_cost_usd)} />
            </div>

            <div style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
              {data.tasks.length === 0 ? (
                <div style={{ fontSize: 13, color: '#94a3b8', padding: '24px 0', textAlign: 'center' }}>
                  Задач нет
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      <th style={thStyle}>Проект</th>
                      <th style={thStyle}>Задача</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Время выполнения</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Токены</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Стоимость</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.tasks.map((row) => (
                      <tr
                        key={row.id}
                        onClick={() => navigate(`/tasks/${row.id}/status`)}
                        style={{ cursor: 'pointer' }}
                        title="Открыть задачу"
                      >
                        <td style={{ ...tdStyle, color: row.project_name ? '#1e293b' : '#94a3b8' }}>
                          {row.project_name ?? 'Без проекта'}
                        </td>
                        <td style={tdStyle}>
                          {taskLabel(row)}
                          {row.name?.trim() && (
                            <span style={{ color: '#94a3b8', fontSize: 12 }}>
                              {' · '}
                              {TASK_TYPE_LABELS[row.task_type] ?? row.task_type}
                            </span>
                          )}
                        </td>
                        <td style={numStyle}>
                          {formatDuration(row.work_seconds)}
                          {/* Счётчик ещё растёт — иначе цифра выглядит итоговой. */}
                          {row.work_running && (
                            <span style={{ color: '#2563eb', fontSize: 12 }}>{' идёт'}</span>
                          )}
                        </td>
                        <td style={numStyle}>{formatTokens(row.tokens)}</td>
                        <td style={numStyle}>{formatUsd(row.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const Total: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div
    style={{
      backgroundColor: '#f8fafc',
      border: '1px solid #e2e8f0',
      borderRadius: 10,
      padding: '10px 16px',
      minWidth: 120,
    }}
  >
    <div style={{ fontSize: 12, color: '#64748b' }}>{label}</div>
    <div style={{ fontSize: 18, fontWeight: 700, color: '#1e293b' }}>{value}</div>
  </div>
);

export default PulseTasksModal;
