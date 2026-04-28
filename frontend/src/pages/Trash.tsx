import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2, RotateCcw, X, Eraser } from 'lucide-react';
import Layout from '../components/Layout';
import { LumaSpin } from '../components/ui/LumaSpin';
import { TASK_TYPE_LABELS, TaskType } from '../types';
import { TrashTaskItem, getMyTrashTasks, restoreMyTask, permanentDeleteMyTask, clearMyTrash } from '../api/tasks';
import { useTaskSync } from '../stores/taskSync';

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'В очереди',
  processing: 'Обрабатывается',
  completed: 'Завершена',
  failed: 'Ошибка',
  cancelled: 'Отменена',
};

const Trash: React.FC = () => {
  const navigate = useNavigate();
  const { version: taskSyncVersion } = useTaskSync();
  const [tasks, setTasks] = useState<TrashTaskItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getMyTrashTasks({ page_size: 100 });
      setTasks(data.items);
      setTotal(data.total);
    } catch {
      setError('Не удалось загрузить корзину');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, taskSyncVersion]);

  async function handleRestore(taskId: string) {
    setRestoringId(taskId);
    try {
      await restoreMyTask(taskId);
      setTasks(prev => prev.filter(t => t.id !== taskId));
      setTotal(prev => prev - 1);
    } catch {
      setError('Не удалось восстановить задачу');
    } finally {
      setRestoringId(null);
    }
  }

  async function handlePermanentDelete(taskId: string) {
    if (!window.confirm('Удалить задачу навсегда? Это действие нельзя отменить.')) return;
    setDeletingId(taskId);
    try {
      await permanentDeleteMyTask(taskId);
      setTasks(prev => prev.filter(t => t.id !== taskId));
      setTotal(prev => prev - 1);
    } catch {
      setError('Не удалось удалить задачу');
    } finally {
      setDeletingId(null);
    }
  }

  async function handleClearTrash() {
    if (!window.confirm(`Удалить все ${total} задач из корзины навсегда? Это действие нельзя отменить.`)) return;
    setClearing(true);
    setError('');
    try {
      await clearMyTrash();
      setTasks([]);
      setTotal(0);
    } catch {
      setError('Не удалось очистить корзину');
    } finally {
      setClearing(false);
    }
  }

  return (
    <Layout>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            backgroundColor: '#fef2f2', display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            <Trash2 size={18} color="#dc2626" />
          </div>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: 0 }}>Корзина</h1>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
              {total > 0 ? `${total} удалённых задач` : 'Корзина пуста'}
            </div>
          </div>
          {total > 0 && !loading && (
            <button
              onClick={handleClearTrash}
              disabled={clearing}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '7px 14px',
                backgroundColor: clearing ? '#fef2f2' : '#fff',
                color: '#dc2626',
                border: '1px solid #fecaca',
                borderRadius: 8,
                cursor: clearing ? 'not-allowed' : 'pointer',
                fontSize: 13,
                fontWeight: 500,
                opacity: clearing ? 0.7 : 1,
                transition: 'background-color 0.15s',
                flexShrink: 0,
              }}
              onMouseEnter={e => { if (!clearing) (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#fef2f2'; }}
              onMouseLeave={e => { if (!clearing) (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#fff'; }}
            >
              <Eraser size={14} />
              {clearing ? 'Очистка...' : 'Очистить корзину'}
            </button>
          )}
        </div>

        {error && (
          <div style={{
            padding: '10px 14px', backgroundColor: '#fef2f2', color: '#dc2626',
            borderRadius: 8, fontSize: 13, marginBottom: 16,
            border: '1px solid #fecaca',
          }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
            <LumaSpin size="md" />
          </div>
        ) : tasks.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '60px 0',
            color: '#94a3b8', fontSize: 14,
          }}>
            <Trash2 size={40} color="#e2e8f0" style={{ marginBottom: 12 }} />
            <div>Корзина пуста</div>
            <div style={{ fontSize: 12, marginTop: 4 }}>Удалённые задачи будут отображаться здесь</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {tasks.map(task => {
              const typeLabel = TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type;
              const displayName = task.name || typeLabel;
              const statusLabel = STATUS_LABELS[task.status] ?? task.status;
              const isRestoring = restoringId === task.id;
              const isDeleting = deletingId === task.id;

              return (
                <div
                  key={task.id}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 16px',
                    backgroundColor: '#ffffff',
                    border: '1px solid #e2e8f0',
                    borderRadius: 8,
                    opacity: isRestoring || isDeleting ? 0.6 : 1,
                    transition: 'opacity 0.15s',
                  }}
                >
                  {/* Icon */}
                  <div style={{
                    width: 32, height: 32, borderRadius: 7,
                    backgroundColor: '#f8fafc',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    <Trash2 size={14} color="#94a3b8" />
                  </div>

                  {/* Info */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: 13, fontWeight: 600, color: '#1e293b',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {displayName}
                    </div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                      {typeLabel} · {statusLabel} · удалено {formatDate(task.deleted_at)}
                    </div>
                  </div>

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                    <button
                      onClick={() => handleRestore(task.id)}
                      disabled={isRestoring || isDeleting}
                      title="Восстановить"
                      style={{
                        display: 'flex', alignItems: 'center', gap: 5,
                        padding: '6px 10px',
                        backgroundColor: '#f0fdf4',
                        color: '#15803d',
                        border: '1px solid #bbf7d0',
                        borderRadius: 6,
                        cursor: 'pointer',
                        fontSize: 12,
                        fontWeight: 500,
                        opacity: isRestoring ? 0.6 : 1,
                      }}
                    >
                      <RotateCcw size={12} />
                      {isRestoring ? '...' : 'Восстановить'}
                    </button>
                    <button
                      onClick={() => handlePermanentDelete(task.id)}
                      disabled={isRestoring || isDeleting}
                      title="Удалить навсегда"
                      style={{
                        display: 'flex', alignItems: 'center', gap: 5,
                        padding: '6px 10px',
                        backgroundColor: '#fef2f2',
                        color: '#dc2626',
                        border: '1px solid #fecaca',
                        borderRadius: 6,
                        cursor: 'pointer',
                        fontSize: 12,
                        fontWeight: 500,
                        opacity: isDeleting ? 0.6 : 1,
                      }}
                    >
                      <X size={12} />
                      {isDeleting ? '...' : 'Удалить'}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {tasks.length > 0 && !loading && (
          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <button
              onClick={() => navigate(-1)}
              style={{
                padding: '8px 20px',
                backgroundColor: 'transparent',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: 7,
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              Назад
            </button>
          </div>
        )}
      </div>
    </Layout>
  );
};

export default Trash;
