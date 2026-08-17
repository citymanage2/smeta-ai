import React, { useMemo, useState } from 'react';
import { FailedTaskGroup } from '../../api/dashboard';
import { resumeTask } from '../../api/tasks';
import { ChevronRight } from 'lucide-react';
import { formatTaskError } from '../../utils/formatError';
import StageErrorNote from '../kanban/StageErrorNote';

const TASK_TYPE_LABELS: Record<string, string> = {
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
  LIST_FROM_PROJECT: 'Перечень из проекта',
  CHECK_LIST_COMPLETENESS: 'Проверка полноты (Гранд)',
  CHECK_PROJECT_COMPLETENESS: 'Проверка полноты (проект)',
  ESTIMATE_FROM_LIST: 'Смета из перечня',
  ESTIMATE_OPTIMIZATION: 'Оптимизация сметы',
};

type Period = '1' | '7' | '30';

interface Props {
  groups: FailedTaskGroup[];
  onResume: () => void;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const DashboardErrors: React.FC<Props> = ({ groups, onResume }) => {
  const [period, setPeriod] = useState<Period>('7');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [resuming, setResuming] = useState<Set<string>>(new Set());

  // Бэкенд группирует по техническому тексту — он же ключ диагностики. Человеку
  // нужна причина: «KeyError: 'unit'» и голое «'unit'» — одна и та же беда, и в
  // журнале это одна строка со счётчиком, а не два одинаковых заголовка.
  const causes = useMemo(() => {
    const cutoff = Date.now() - parseInt(period) * 86_400_000;
    const filtered = groups.filter((g) => new Date(g.last_failed_at).getTime() >= cutoff);
    const byCause = new Map<string, FailedTaskGroup>();
    for (const g of filtered) {
      const cause = formatTaskError(g.pattern);
      const key = `${cause}::${g.task_type}`;
      const merged = byCause.get(key);
      if (!merged) {
        byCause.set(key, { ...g, pattern: cause, tasks: [...g.tasks] });
        continue;
      }
      merged.count += g.count;
      merged.tasks.push(...g.tasks);
      if (new Date(g.last_failed_at) > new Date(merged.last_failed_at)) {
        merged.last_failed_at = g.last_failed_at;
      }
    }
    const list = [...byCause.values()];
    for (const g of list) {
      g.tasks.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    }
    return list.sort(
      (a, b) => new Date(b.last_failed_at).getTime() - new Date(a.last_failed_at).getTime()
    );
  }, [groups, period]);

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  async function handleResume(taskId: string) {
    setResuming((prev) => new Set(prev).add(taskId));
    try {
      await resumeTask(taskId);
      onResume();
    } finally {
      setResuming((prev) => {
        const next = new Set(prev);
        next.delete(taskId);
        return next;
      });
    }
  }

  function copyError(msg: string) {
    navigator.clipboard.writeText(msg).catch(() => {});
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: 0 }}>
          Журнал ошибок
          {causes.length > 0 && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 12,
                fontWeight: 500,
                color: '#dc2626',
                backgroundColor: '#fef2f2',
                borderRadius: 20,
                padding: '2px 8px',
              }}
            >
              {causes.reduce((s, g) => s + g.count, 0)}
            </span>
          )}
        </h2>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['1', '7', '30'] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                fontSize: 12,
                padding: '3px 10px',
                border: '1px solid',
                borderColor: period === p ? '#2563eb' : '#e2e8f0',
                borderRadius: 6,
                backgroundColor: period === p ? '#eff6ff' : '#fff',
                color: period === p ? '#2563eb' : '#64748b',
                cursor: 'pointer',
                fontWeight: period === p ? 600 : 400,
              }}
            >
              {p} {p === '1' ? 'день' : 'дн'}
            </button>
          ))}
        </div>
      </div>

      {causes.length === 0 ? (
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
          Ошибок нет
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {causes.map((group) => {
            const key = `${group.pattern}::${group.task_type}`;
            const isOpen = expanded.has(key);
            return (
              <div key={key} style={{ border: '1px solid #fecaca', borderRadius: 8, overflow: 'hidden' }}>
                <button
                  onClick={() => toggle(key)}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '10px 14px',
                    backgroundColor: '#fef2f2',
                    border: 'none',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  <ChevronRight
                    size={14}
                    color="#dc2626"
                    style={{ transform: isOpen ? 'rotate(90deg)' : undefined, transition: 'transform 0.15s', flexShrink: 0 }}
                  />
                  {/* Причина занимает до двух строк: одной строкой с многоточием
                      от объяснения оставался бы обрубок «Внутренняя ошибка…». */}
                  <span
                    style={{
                      fontSize: 13,
                      color: '#dc2626',
                      fontWeight: 600,
                      flex: 1,
                      minWidth: 0,
                      lineHeight: 1.4,
                      display: '-webkit-box',
                      WebkitBoxOrient: 'vertical',
                      WebkitLineClamp: 2,
                      overflow: 'hidden',
                    }}
                  >
                    {group.pattern}
                  </span>
                  <span style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}>
                    {TASK_TYPE_LABELS[group.task_type] ?? group.task_type}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '1px 7px',
                      borderRadius: 20,
                      backgroundColor: '#fca5a5',
                      color: '#7f1d1d',
                      marginLeft: 4,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    ×{group.count}
                  </span>
                  <span style={{ fontSize: 11, color: '#94a3b8', whiteSpace: 'nowrap', marginLeft: 8 }}>
                    {formatDate(group.last_failed_at)}
                  </span>
                </button>

                {isOpen && (
                  <div style={{ backgroundColor: '#fff' }}>
                    {group.tasks.map((task) => (
                      <div
                        key={task.id}
                        style={{
                          padding: '10px 14px',
                          borderTop: '1px solid #fee2e2',
                          fontSize: 12,
                          color: '#374151',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ color: '#64748b', marginBottom: 4 }}>
                              {formatDate(task.created_at)} · {TASK_TYPE_LABELS[task.task_type] ?? task.task_type}
                            </div>
                            {/* Тот же блок, что в карточке сметы и на доске:
                                причина словами, технический оригинал — под
                                «Подробности». */}
                            {/* Пустая причина — не пустое место: задача в журнале
                                есть, и человек должен знать, что причина не
                                записана, а не смотреть на одну дату. */}
                            <StageErrorNote message={task.error_message || formatTaskError(null)} />
                          </div>
                          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                            <button
                              onClick={() => handleResume(task.id)}
                              disabled={resuming.has(task.id)}
                              style={actionBtnStyle('#2563eb', '#eff6ff')}
                            >
                              {resuming.has(task.id) ? '...' : 'Перезапустить'}
                            </button>
                            <button
                              onClick={() => copyError(task.error_message ?? '')}
                              style={actionBtnStyle('#64748b', '#f8fafc')}
                            >
                              Копировать
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

function actionBtnStyle(color: string, bg: string): React.CSSProperties {
  return {
    fontSize: 11,
    padding: '3px 9px',
    border: `1px solid ${color}22`,
    borderRadius: 5,
    backgroundColor: bg,
    color,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  };
}

export default DashboardErrors;
