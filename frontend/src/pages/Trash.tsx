import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2, RotateCcw, X, Eraser, FolderOpen, LayoutDashboard } from 'lucide-react';
import Layout from '../components/Layout';
import { LumaSpin } from '../components/ui/LumaSpin';
import { TASK_TYPE_LABELS, TaskType } from '../types';
import { TrashTaskItem, getMyTrashTasks, restoreMyTask, permanentDeleteMyTask, clearMyTrash } from '../api/tasks';
import { TrashProjectItem, getTrashProjects, restoreProject, permanentDeleteProject, clearProjectTrash } from '../api/projects';
import { TrashCardItem, getTrashCards, restoreCard, permanentDeleteCard } from '../api/workflowCards';
import { useTaskSync } from '../stores/taskSync';
import { useAuthStore } from '../stores/auth';

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

type Tab = 'tasks' | 'projects' | 'cards';

const STAGE_LABELS: Record<string, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
};

const Trash: React.FC = () => {
  const navigate = useNavigate();
  const { version: taskSyncVersion } = useTaskSync();
  const { isAdmin } = useAuthStore();
  const [tab, setTab] = useState<Tab>('tasks');

  // Tasks state
  const [tasks, setTasks] = useState<TrashTaskItem[]>([]);
  const [tasksTotal, setTasksTotal] = useState(0);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksError, setTasksError] = useState('');
  const [restoringTaskId, setRestoringTaskId] = useState<string | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [clearingTasks, setClearingTasks] = useState(false);

  // Projects state
  const [projects, setProjects] = useState<TrashProjectItem[]>([]);
  const [projectsTotal, setProjectsTotal] = useState(0);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState('');
  const [restoringProjectId, setRestoringProjectId] = useState<string | null>(null);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [clearingProjects, setClearingProjects] = useState(false);

  // Cards state
  const [cards, setCards] = useState<TrashCardItem[]>([]);
  const [cardsTotal, setCardsTotal] = useState(0);
  const [cardsLoading, setCardsLoading] = useState(true);
  const [cardsError, setCardsError] = useState('');
  const [restoringCardId, setRestoringCardId] = useState<string | null>(null);
  const [deletingCardId, setDeletingCardId] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    setTasksLoading(true);
    setTasksError('');
    try {
      const data = await getMyTrashTasks({ page_size: 100 });
      setTasks(data.items);
      setTasksTotal(data.total);
    } catch {
      setTasksError('Не удалось загрузить удалённые задачи');
    } finally {
      setTasksLoading(false);
    }
  }, []);

  const loadProjects = useCallback(async () => {
    setProjectsLoading(true);
    setProjectsError('');
    try {
      const data = await getTrashProjects();
      setProjects(data.items);
      setProjectsTotal(data.total);
    } catch {
      setProjectsError('Не удалось загрузить удалённые проекты');
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  const loadCards = useCallback(async () => {
    setCardsLoading(true);
    setCardsError('');
    try {
      const data = await getTrashCards();
      setCards(data.items);
      setCardsTotal(data.total);
    } catch {
      setCardsError('Не удалось загрузить удалённые сметы');
    } finally {
      setCardsLoading(false);
    }
  }, []);

  useEffect(() => { loadTasks(); }, [loadTasks, taskSyncVersion]);
  useEffect(() => { loadProjects(); }, [loadProjects]);
  useEffect(() => { loadCards(); }, [loadCards]);

  async function handleRestoreTask(taskId: string) {
    setRestoringTaskId(taskId);
    try {
      await restoreMyTask(taskId);
      setTasks(prev => prev.filter(t => t.id !== taskId));
      setTasksTotal(prev => prev - 1);
    } catch {
      setTasksError('Не удалось восстановить задачу');
    } finally {
      setRestoringTaskId(null);
    }
  }

  async function handlePermanentDeleteTask(taskId: string) {
    if (!window.confirm('Удалить задачу навсегда? Это действие нельзя отменить.')) return;
    setDeletingTaskId(taskId);
    try {
      await permanentDeleteMyTask(taskId);
      setTasks(prev => prev.filter(t => t.id !== taskId));
      setTasksTotal(prev => prev - 1);
    } catch {
      setTasksError('Не удалось удалить задачу');
    } finally {
      setDeletingTaskId(null);
    }
  }

  async function handleClearTaskTrash() {
    // Корзина общая, а очистка — только своё: чужие удалённые задачи останутся.
    if (!window.confirm('Удалить свои задачи из корзины навсегда? Задачи коллег останутся. Это действие нельзя отменить.')) return;
    setClearingTasks(true);
    setTasksError('');
    try {
      await clearMyTrash();
      await loadTasks();
    } catch {
      setTasksError('Не удалось очистить корзину');
    } finally {
      setClearingTasks(false);
    }
  }

  async function handleRestoreProject(projectId: string) {
    setRestoringProjectId(projectId);
    try {
      await restoreProject(projectId);
      setProjects(prev => prev.filter(p => p.id !== projectId));
      setProjectsTotal(prev => prev - 1);
    } catch {
      setProjectsError('Не удалось восстановить проект');
    } finally {
      setRestoringProjectId(null);
    }
  }

  async function handlePermanentDeleteProject(projectId: string) {
    if (!window.confirm('Удалить проект навсегда? Все данные будут утеряны. Это действие нельзя отменить.')) return;
    setDeletingProjectId(projectId);
    try {
      await permanentDeleteProject(projectId);
      setProjects(prev => prev.filter(p => p.id !== projectId));
      setProjectsTotal(prev => prev - 1);
    } catch {
      setProjectsError('Не удалось удалить проект');
    } finally {
      setDeletingProjectId(null);
    }
  }

  async function handleClearProjectTrash() {
    if (!window.confirm(`Удалить все ${projectsTotal} проектов из корзины навсегда? Это действие нельзя отменить.`)) return;
    setClearingProjects(true);
    setProjectsError('');
    try {
      await clearProjectTrash();
      setProjects([]);
      setProjectsTotal(0);
    } catch {
      setProjectsError('Не удалось очистить корзину проектов');
    } finally {
      setClearingProjects(false);
    }
  }

  async function handleRestoreCard(cardId: string) {
    setRestoringCardId(cardId);
    try {
      await restoreCard(cardId);
      setCards(prev => prev.filter(c => c.id !== cardId));
      setCardsTotal(prev => prev - 1);
    } catch {
      setCardsError('Не удалось восстановить смету');
    } finally {
      setRestoringCardId(null);
    }
  }

  async function handlePermanentDeleteCard(cardId: string) {
    if (!window.confirm('Удалить смету и все её задачи навсегда? Это действие нельзя отменить.')) return;
    setDeletingCardId(cardId);
    try {
      await permanentDeleteCard(cardId);
      setCards(prev => prev.filter(c => c.id !== cardId));
      setCardsTotal(prev => prev - 1);
    } catch {
      setCardsError('Не удалось удалить смету');
    } finally {
      setDeletingCardId(null);
    }
  }

  const totalAll = tasksTotal + projectsTotal + cardsTotal;

  return (
    <Layout>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
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
              {totalAll > 0 ? `${totalAll} удалённых элементов` : 'Корзина пуста'}
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{
          display: 'flex', gap: 4, marginBottom: 20,
          borderBottom: '1px solid #e2e8f0', paddingBottom: 0,
        }}>
          {([
            { key: 'tasks' as Tab, label: 'Задачи', count: tasksTotal },
            { key: 'projects' as Tab, label: 'Проекты', count: projectsTotal },
            { key: 'cards' as Tab, label: 'Сметы', count: cardsTotal },
          ]).map(({ key, label, count }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                padding: '8px 16px',
                backgroundColor: 'transparent',
                border: 'none',
                borderBottom: tab === key ? '2px solid #3b82f6' : '2px solid transparent',
                color: tab === key ? '#3b82f6' : '#64748b',
                fontWeight: tab === key ? 600 : 400,
                fontSize: 14,
                cursor: 'pointer',
                marginBottom: -1,
                transition: 'color 0.15s',
              }}
            >
              {label}
              {count > 0 && (
                <span style={{
                  marginLeft: 6,
                  padding: '1px 6px',
                  backgroundColor: tab === key ? '#eff6ff' : '#f1f5f9',
                  color: tab === key ? '#3b82f6' : '#94a3b8',
                  borderRadius: 10,
                  fontSize: 11,
                  fontWeight: 600,
                }}>
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tasks tab */}
        {tab === 'tasks' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              {tasksTotal > 0 && !tasksLoading && (
                <button
                  onClick={handleClearTaskTrash}
                  disabled={clearingTasks}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '7px 14px',
                    backgroundColor: clearingTasks ? '#fef2f2' : '#fff',
                    color: '#dc2626',
                    border: '1px solid #fecaca',
                    borderRadius: 8,
                    cursor: clearingTasks ? 'not-allowed' : 'pointer',
                    fontSize: 13, fontWeight: 500,
                    opacity: clearingTasks ? 0.7 : 1,
                  }}
                >
                  <Eraser size={14} />
                  {clearingTasks ? 'Очистка...' : 'Очистить свои'}
                </button>
              )}
            </div>

            {tasksError && (
              <div style={{
                padding: '10px 14px', backgroundColor: '#fef2f2', color: '#dc2626',
                borderRadius: 8, fontSize: 13, marginBottom: 16,
                border: '1px solid #fecaca',
              }}>
                {tasksError}
              </div>
            )}

            {tasksLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
                <LumaSpin size="md" />
              </div>
            ) : tasks.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
                <Trash2 size={40} color="#e2e8f0" style={{ marginBottom: 12 }} />
                <div>Нет удалённых задач</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Удалённые задачи будут отображаться здесь</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {tasks.map(task => {
                  const typeLabel = TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type;
                  const displayName = task.name || typeLabel;
                  const statusLabel = STATUS_LABELS[task.status] ?? task.status;
                  const isRestoring = restoringTaskId === task.id;
                  const isDeleting = deletingTaskId === task.id;

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
                      <div style={{
                        width: 32, height: 32, borderRadius: 7,
                        backgroundColor: '#f8fafc',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                      }}>
                        <Trash2 size={14} color="#94a3b8" />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, color: '#1e293b',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {displayName}
                        </div>
                        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                          {typeLabel} · {statusLabel} · удалено {formatDate(task.deleted_at)}
                          {task.owner_name ? ` · ${task.owner_name}` : ''}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                        <button
                          onClick={() => handleRestoreTask(task.id)}
                          disabled={isRestoring || isDeleting}
                          title="Восстановить"
                          style={{
                            display: 'flex', alignItems: 'center', gap: 5,
                            padding: '6px 10px',
                            backgroundColor: '#f0fdf4', color: '#15803d',
                            border: '1px solid #bbf7d0', borderRadius: 6,
                            cursor: 'pointer', fontSize: 12, fontWeight: 500,
                            opacity: isRestoring ? 0.6 : 1,
                          }}
                        >
                          <RotateCcw size={12} />
                          {isRestoring ? '...' : 'Восстановить'}
                        </button>
                        <button
                          onClick={() => handlePermanentDeleteTask(task.id)}
                          disabled={isRestoring || isDeleting}
                          title="Удалить навсегда"
                          style={{
                            display: 'flex', alignItems: 'center', gap: 5,
                            padding: '6px 10px',
                            backgroundColor: '#fef2f2', color: '#dc2626',
                            border: '1px solid #fecaca', borderRadius: 6,
                            cursor: 'pointer', fontSize: 12, fontWeight: 500,
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
          </div>
        )}

        {/* Projects tab */}
        {tab === 'projects' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              {projectsTotal > 0 && !projectsLoading && isAdmin && (
                <button
                  onClick={handleClearProjectTrash}
                  disabled={clearingProjects}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '7px 14px',
                    backgroundColor: clearingProjects ? '#fef2f2' : '#fff',
                    color: '#dc2626',
                    border: '1px solid #fecaca',
                    borderRadius: 8,
                    cursor: clearingProjects ? 'not-allowed' : 'pointer',
                    fontSize: 13, fontWeight: 500,
                    opacity: clearingProjects ? 0.7 : 1,
                  }}
                >
                  <Eraser size={14} />
                  {clearingProjects ? 'Очистка...' : 'Очистить'}
                </button>
              )}
            </div>

            {projectsError && (
              <div style={{
                padding: '10px 14px', backgroundColor: '#fef2f2', color: '#dc2626',
                borderRadius: 8, fontSize: 13, marginBottom: 16,
                border: '1px solid #fecaca',
              }}>
                {projectsError}
              </div>
            )}

            {projectsLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
                <LumaSpin size="md" />
              </div>
            ) : projects.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
                <FolderOpen size={40} color="#e2e8f0" style={{ marginBottom: 12 }} />
                <div>Нет удалённых проектов</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Удалённые проекты будут отображаться здесь</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {projects.map(project => {
                  const isRestoring = restoringProjectId === project.id;
                  const isDeleting = deletingProjectId === project.id;

                  return (
                    <div
                      key={project.id}
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
                      <div style={{
                        width: 32, height: 32, borderRadius: 7,
                        backgroundColor: '#f8fafc',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                      }}>
                        <FolderOpen size={14} color="#94a3b8" />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, color: '#1e293b',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {project.name}
                        </div>
                        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                          {project.description
                            ? `${project.description} · `
                            : ''}
                          удалено {formatDate(project.deleted_at)}
                          {project.owner_name ? ` · ${project.owner_name}` : ''}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                        <button
                          onClick={() => handleRestoreProject(project.id)}
                          disabled={isRestoring || isDeleting}
                          title="Восстановить проект"
                          style={{
                            display: 'flex', alignItems: 'center', gap: 5,
                            padding: '6px 10px',
                            backgroundColor: '#f0fdf4', color: '#15803d',
                            border: '1px solid #bbf7d0', borderRadius: 6,
                            cursor: 'pointer', fontSize: 12, fontWeight: 500,
                            opacity: isRestoring ? 0.6 : 1,
                          }}
                        >
                          <RotateCcw size={12} />
                          {isRestoring ? '...' : 'Восстановить'}
                        </button>
                        {isAdmin && (
                          <button
                            onClick={() => handlePermanentDeleteProject(project.id)}
                            disabled={isRestoring || isDeleting}
                            title="Удалить навсегда"
                            style={{
                              display: 'flex', alignItems: 'center', gap: 5,
                              padding: '6px 10px',
                              backgroundColor: '#fef2f2', color: '#dc2626',
                              border: '1px solid #fecaca', borderRadius: 6,
                              cursor: 'pointer', fontSize: 12, fontWeight: 500,
                              opacity: isDeleting ? 0.6 : 1,
                            }}
                          >
                            <X size={12} />
                            {isDeleting ? '...' : 'Удалить'}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Cards tab */}
        {tab === 'cards' && (
          <div>
            {cardsError && (
              <div style={{
                padding: '10px 14px', backgroundColor: '#fef2f2', color: '#dc2626',
                borderRadius: 8, fontSize: 13, marginBottom: 16,
                border: '1px solid #fecaca',
              }}>
                {cardsError}
              </div>
            )}

            {cardsLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
                <LumaSpin size="md" />
              </div>
            ) : cards.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
                <LayoutDashboard size={40} color="#e2e8f0" style={{ marginBottom: 12 }} />
                <div>Нет удалённых смет</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Удалённые сметы будут отображаться здесь</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {cards.map(card => {
                  const isRestoring = restoringCardId === card.id;
                  const isDeleting = deletingCardId === card.id;
                  const stageLabel = STAGE_LABELS[card.stage] ?? card.stage;

                  return (
                    <div
                      key={card.id}
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
                      <div style={{
                        width: 32, height: 32, borderRadius: 7,
                        backgroundColor: '#f8fafc',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                      }}>
                        <LayoutDashboard size={14} color="#94a3b8" />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, color: '#1e293b',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {card.name}
                        </div>
                        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                          {card.project_name} · {stageLabel} · {card.task_count} {card.task_count === 1 ? 'задача' : 'задач'} · удалено {formatDate(card.deleted_at)}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                        <button
                          onClick={() => handleRestoreCard(card.id)}
                          disabled={isRestoring || isDeleting}
                          title="Восстановить смету"
                          style={{
                            display: 'flex', alignItems: 'center', gap: 5,
                            padding: '6px 10px',
                            backgroundColor: '#f0fdf4', color: '#15803d',
                            border: '1px solid #bbf7d0', borderRadius: 6,
                            cursor: 'pointer', fontSize: 12, fontWeight: 500,
                            opacity: isRestoring ? 0.6 : 1,
                          }}
                        >
                          <RotateCcw size={12} />
                          {isRestoring ? '...' : 'Восстановить'}
                        </button>
                        <button
                          onClick={() => handlePermanentDeleteCard(card.id)}
                          disabled={isRestoring || isDeleting}
                          title="Удалить навсегда"
                          style={{
                            display: 'flex', alignItems: 'center', gap: 5,
                            padding: '6px 10px',
                            backgroundColor: '#fef2f2', color: '#dc2626',
                            border: '1px solid #fecaca', borderRadius: 6,
                            cursor: 'pointer', fontSize: 12, fontWeight: 500,
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
          </div>
        )}

        {(tab === 'tasks' ? tasks.length : tab === 'projects' ? projects.length : cards.length) > 0 && !(tab === 'tasks' ? tasksLoading : tab === 'projects' ? projectsLoading : cardsLoading) && (
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
