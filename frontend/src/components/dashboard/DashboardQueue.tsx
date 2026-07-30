import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ActiveTask } from '../../api/dashboard';
import { cancelTask } from '../../api/tasks';
import { describeEta } from '../../utils/eta';

const TASK_TYPE_LABELS: Record<string, string> = {
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
  LIST_FROM_PROJECT: 'Перечень из проекта',
  CHECK_LIST_COMPLETENESS: 'Проверка полноты (Гранд)',
  CHECK_PROJECT_COMPLETENESS: 'Проверка полноты (проект)',
  ESTIMATE_FROM_LIST: 'Смета из перечня',
  ESTIMATE_OPTIMIZATION: 'Оптимизация сметы',
};

function elapsedLabel(createdAt: string): { label: string; minutes: number } {
  const ms = Date.now() - new Date(createdAt).getTime();
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return { label: '< 1 мин', minutes };
  if (minutes < 60) return { label: `${minutes} мин`, minutes };
  const hours = Math.floor(minutes / 60);
  return { label: `${hours} ч ${minutes % 60} мин`, minutes };
}

function rowBg(task: ActiveTask): string {
  const { minutes } = elapsedLabel(task.created_at);
  if (task.status === 'processing') {
    if (minutes > 30) return '#fef2f2';
    if (minutes > 15) return '#fffbeb';
  } else if (task.status === 'pending' && minutes > 5) {
    return '#fffbeb';
  }
  return '#ffffff';
}

interface Props {
  tasks: ActiveTask[];
  onCancel: () => void;
}

const DashboardQueue: React.FC<Props> = ({ tasks, onCancel }) => {
  const navigate = useNavigate();
  const [cancelling, setCancelling] = React.useState<Set<string>>(new Set());

  async function handleCancel(taskId: string) {
    setCancelling((prev) => new Set(prev).add(taskId));
    try {
      await cancelTask(taskId);
      onCancel();
    } finally {
      setCancelling((prev) => {
        const next = new Set(prev);
        next.delete(taskId);
        return next;
      });
    }
  }

  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>
        Активная очередь
        <span
          style={{
            marginLeft: 8,
            fontSize: 12,
            fontWeight: 500,
            color: '#64748b',
            backgroundColor: '#f1f5f9',
            borderRadius: 20,
            padding: '2px 8px',
          }}
        >
          {tasks.length}
        </span>
      </h2>

      {tasks.length === 0 ? (
        <div
          style={{
            padding: '24px',
            textAlign: 'center',
            color: '#94a3b8',
            fontSize: 14,
            backgroundColor: '#f8fafc',
            borderRadius: 8,
            border: '1px solid #e2e8f0',
          }}
        >
          Нет активных задач
        </div>
      ) : (
        <div
          style={{
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            overflow: 'hidden',
          }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                <th style={thStyle}>Тип задачи</th>
                <th style={thStyle}>Проект</th>
                <th style={thStyle}>В очереди</th>
                <th style={thStyle}>Готовность</th>
                <th style={thStyle}>Прогресс</th>
                <th style={thStyle}>Статус</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task, i) => {
                const { label: elapsed } = elapsedLabel(task.created_at);
                const bg = rowBg(task);
                return (
                  <tr
                    key={task.id}
                    onClick={() => navigate(`/tasks/${task.id}/status`)}
                    title="Открыть задачу"
                    style={{
                      backgroundColor: bg,
                      borderBottom: i < tasks.length - 1 ? '1px solid #e2e8f0' : undefined,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#eff6ff')}
                    onMouseLeave={e => (e.currentTarget.style.backgroundColor = bg)}
                  >
                    <td style={tdStyle}>{TASK_TYPE_LABELS[task.task_type] ?? task.task_type}</td>
                    <td style={{ ...tdStyle, color: '#64748b' }}>{task.project_name ?? '—'}</td>
                    <td style={{ ...tdStyle, color: '#64748b', whiteSpace: 'nowrap' }}>{elapsed}</td>
                    <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                      <EtaCell task={task} />
                    </td>
                    <td style={{ ...tdStyle, color: '#64748b', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {task.progress_message ?? '—'}
                    </td>
                    <td style={tdStyle}>
                      <StatusBadge status={task.status} />
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      <button
                        onClick={e => { e.stopPropagation(); handleCancel(task.id); }}
                        disabled={cancelling.has(task.id)}
                        style={{
                          fontSize: 12,
                          padding: '3px 10px',
                          border: '1px solid #fca5a5',
                          borderRadius: 6,
                          backgroundColor: '#fff',
                          color: '#dc2626',
                          cursor: cancelling.has(task.id) ? 'not-allowed' : 'pointer',
                          opacity: cancelling.has(task.id) ? 0.5 : 1,
                        }}
                      >
                        Отменить
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

/** Когда стартует и когда будет результат. Прочерк — прогноза нет. */
const EtaCell: React.FC<{ task: ActiveTask }> = ({ task }) => {
  const view = describeEta(task.eta, task.status);
  if (!view) return <span style={{ color: '#94a3b8' }}>—</span>;

  return (
    <span title={view.hint} data-testid="queue-eta">
      {/* Позиция — над временем: задачи считаются по одной, и очередь читается
          именно как очередь. Минуты рядом — оценка, позиция — факт. */}
      {view.position && (
        <span
          data-testid="queue-position"
          style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#92400e' }}
        >
          {view.position}
        </span>
      )}
      <span style={{ color: '#1e293b', fontWeight: 500 }}>{view.ready}</span>
      {view.start && (
        <span style={{ display: 'block', fontSize: 11, color: '#64748b' }}>{view.start}</span>
      )}
      {view.rough && (
        <span style={{ display: 'block', fontSize: 11, color: '#94a3b8' }}>оценка грубая</span>
      )}
    </span>
  );
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const map: Record<string, { label: string; color: string; bg: string }> = {
    pending: { label: 'Ожидает', color: '#92400e', bg: '#fef3c7' },
    processing: { label: 'Обработка', color: '#1d4ed8', bg: '#dbeafe' },
  };
  const s = map[status] ?? { label: status, color: '#374151', bg: '#f1f5f9' };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: '2px 8px',
        borderRadius: 20,
        color: s.color,
        backgroundColor: s.bg,
        whiteSpace: 'nowrap',
      }}
    >
      {s.label}
    </span>
  );
};

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  textAlign: 'left',
  fontSize: 12,
  fontWeight: 600,
  color: '#64748b',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  fontSize: 13,
  color: '#1e293b',
};

export default DashboardQueue;
