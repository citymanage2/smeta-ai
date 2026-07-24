import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Check, X, Trash2 } from 'lucide-react';
import Layout from '../components/Layout';
import { PageLoader } from '../components/ui/LumaSpin';
import { ProjectDetail as IProjectDetail, TaskBrief, TASK_TYPE_LABELS, ESTIMATE_TASK_TYPES } from '../types';
import { getProject, updateProject, deleteProject } from '../api/projects';
import { updateTask, softDeleteTask } from '../api/tasks';
import { useAuthStore } from '../stores/auth';
import OptimizeModal from '../components/OptimizeModal';
import HistoryModal from '../components/HistoryModal';
import { KanbanBoard } from '../components/kanban/KanbanBoard';
import { SmetaList } from '../components/SmetaList';

const ESTIMATION_LABELS: Record<string, string> = {
  unestimated: 'Не рассчитана',
  estimated: 'Рассчитана',
  optimizing: 'Оптимизируется',
  optimized: 'Оптимизирована',
  not_applicable: '—',
};

const ESTIMATION_COLORS: Record<string, { bg: string; text: string }> = {
  unestimated: { bg: '#fef2f2', text: '#dc2626' },
  estimated: { bg: '#fef9c3', text: '#854d0e' },
  optimizing: { bg: '#eff6ff', text: '#2563eb' },
  optimized: { bg: '#f0fdf4', text: '#15803d' },
  not_applicable: { bg: '#f8fafc', text: '#94a3b8' },
};

function formatCost(cost: number): string {
  return cost.toLocaleString('ru-RU') + ' ₽';
}

const iconBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  padding: '2px',
  display: 'inline-flex',
  alignItems: 'center',
  color: '#94a3b8',
};

function InlineEditName({
  value,
  onSave,
  inputStyle,
  iconSize = 16,
  hoverOnly = false,
}: {
  value: string;
  onSave: (name: string) => Promise<void>;
  inputStyle?: React.CSSProperties;
  iconSize?: number;
  hoverOnly?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saveError, setSaveError] = useState('');
  const [hovered, setHovered] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  async function save() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) {
      try {
        await onSave(trimmed);
        setSaveError('');
        setEditing(false);
      } catch {
        setSaveError('Не удалось сохранить имя. Попробуйте ещё раз.');
      }
    } else {
      setEditing(false);
    }
  }

  function cancel() {
    setDraft(value);
    setSaveError('');
    setEditing(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') cancel();
  }

  if (editing) {
    return (
      <>
        <span
          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
          onClick={e => e.stopPropagation()}
        >
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{
              border: '1px solid #93c5fd',
              borderRadius: '6px',
              padding: '4px 8px',
              outline: 'none',
              ...inputStyle,
            }}
          />
          <button style={{ ...iconBtnStyle, color: '#16a34a' }} onClick={save}>
            <Check size={iconSize} />
          </button>
          <button style={{ ...iconBtnStyle, color: '#dc2626' }} onClick={cancel}>
            <X size={iconSize} />
          </button>
        </span>
        {saveError && (
          <div style={{ fontSize: '12px', color: '#dc2626', marginTop: '4px' }}>{saveError}</div>
        )}
      </>
    );
  }

  const showIcon = !hoverOnly || hovered;

  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span>{value}</span>
      <button
        style={{ ...iconBtnStyle, opacity: showIcon ? 1 : 0, transition: 'opacity 0.15s' }}
        onClick={(e) => { e.stopPropagation(); setDraft(value); setEditing(true); }}
      >
        <Pencil size={iconSize} />
      </button>
    </span>
  );
}

function DescriptionRow({ description, onEdit }: { description: string | null; onEdit: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {description ? (
        <p style={{ margin: 0, fontSize: '14px', color: '#64748b' }}>{description}</p>
      ) : (
        <span style={{ fontSize: '13px', color: '#cbd5e1' }}>Без описания</span>
      )}
      <button
        style={{ ...iconBtnStyle, opacity: hovered ? 1 : 0, transition: 'opacity 0.15s' }}
        onClick={onEdit}
      >
        <Pencil size={14} />
      </button>
    </div>
  );
}

const ProjectDetailPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { isAdmin } = useAuthStore();

  const [project, setProject] = useState<IProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editingDesc, setEditingDesc] = useState(false);
  const [saving, setSaving] = useState(false);
  const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);
  const [historyTaskId, setHistoryTaskId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'smeta' | 'kanban' | 'tasks'>('smeta');
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);

  useEffect(() => {
    if (projectId) loadProject();
  }, [projectId]);

  async function loadProject() {
    setLoading(true);
    try {
      const data = await getProject(projectId!);
      setProject(data);
      setEditDesc(data.description ?? '');
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number }; request?: unknown };
      if (axiosErr.response?.status === 404) {
        setError('Проект не найден. Возможно, он был удалён.');
      } else if (axiosErr.request && !axiosErr.response) {
        setError('Не удалось загрузить проект. Проверьте соединение и обновите страницу.');
      } else {
        setError('Не удалось загрузить проект. Попробуйте обновить страницу.');
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveProjectName(name: string) {
    if (!projectId) return;
    const updated = await updateProject(projectId, { name });
    setProject(prev => prev ? { ...prev, name: updated.name } : prev);
  }

  async function handleSaveDesc(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    setSaving(true);
    try {
      const updated = await updateProject(projectId, { description: editDesc.trim() || undefined });
      setProject(prev => prev ? { ...prev, description: updated.description } : prev);
      setEditingDesc(false);
    } catch {
      setError('Не удалось сохранить описание. Попробуйте ещё раз.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteTask(taskId: string) {
    if (!window.confirm('Удалить задачу? Она будет перемещена в корзину.')) return;
    setDeletingTaskId(taskId);
    try {
      await softDeleteTask(taskId);
      setProject(prev => prev ? { ...prev, tasks: prev.tasks.filter(t => t.id !== taskId) } : prev);
    } catch {
      setError('Не удалось удалить задачу. Попробуйте ещё раз.');
    } finally {
      setDeletingTaskId(null);
    }
  }

  async function handleSaveTaskName(taskId: string, name: string) {
    await updateTask(taskId, { name });
    setProject(prev => prev ? {
      ...prev,
      tasks: prev.tasks.map(t => t.id === taskId ? { ...t, name } : t),
    } : prev);
  }

  async function handleDelete() {
    if (!projectId) return;
    if (!window.confirm('Удалить проект? Задачи останутся, но будут откреплены.')) return;
    try {
      await deleteProject(projectId);
      navigate('/projects');
    } catch {
      setError('Ошибка при удалении проекта');
    }
  }

  if (loading) {
    return <Layout><PageLoader /></Layout>;
  }

  if (error || !project) {
    return (
      <Layout>
        <div style={{ textAlign: 'center', padding: '48px', color: '#dc2626' }}>{error || 'Проект не найден'}</div>
      </Layout>
    );
  }

  const totalCost = project.tasks
    .filter(t => (t.estimation_status === 'estimated' || t.estimation_status === 'optimized') && t.cost)
    .reduce((sum, t) => sum + (t.cost as number), 0) || null;

  const optimizedCost = project.tasks
    .filter(t => t.estimation_status === 'optimized' && t.cost)
    .reduce((sum, t) => sum + (t.cost as number), 0) || null;

  return (
    <Layout>
      <div style={{ width: '90%', margin: '0 auto' }}>
        <button
          onClick={() => navigate('/projects')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#2563eb', fontSize: '14px', marginBottom: '16px', padding: 0 }}
        >
          ← Все проекты
        </button>

        <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '24px', marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div style={{ flex: 1, minWidth: 0, marginRight: '16px' }}>
              {/* Project name with inline edit */}
              <h1 style={{ margin: '0 0 8px', fontSize: '22px', fontWeight: 700, color: '#1e293b' }}>
                <InlineEditName
                  value={project.name}
                  onSave={handleSaveProjectName}
                  inputStyle={{ fontSize: '20px', fontWeight: 700, width: '280px' }}
                  iconSize={18}
                  hoverOnly
                />
              </h1>

              {/* Description */}
              {editingDesc ? (
                <form onSubmit={handleSaveDesc} style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                  <textarea
                    value={editDesc}
                    onChange={e => setEditDesc(e.target.value)}
                    rows={2}
                    style={{ flex: 1, padding: '6px 8px', border: '1px solid #93c5fd', borderRadius: '6px', fontSize: '14px', resize: 'vertical', outline: 'none' }}
                  />
                  <button type="submit" disabled={saving} style={{ ...iconBtnStyle, color: '#16a34a' }}>
                    <Check size={16} />
                  </button>
                  <button type="button" onClick={() => setEditingDesc(false)} style={{ ...iconBtnStyle, color: '#dc2626' }}>
                    <X size={16} />
                  </button>
                </form>
              ) : (
                <DescriptionRow
                  description={project.description ?? null}
                  onEdit={() => { setEditDesc(project.description ?? ''); setEditingDesc(true); }}
                />
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexShrink: 0 }}>
              <button
                onClick={() => navigate(`/projects/${projectId}/summary`)}
                style={{ padding: '7px 14px', backgroundColor: '#f5f3ff', border: '1px solid #ddd6fe', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#7c3aed', fontWeight: 500 }}
              >
                Сводная себестоимость
              </button>
              <button
                onClick={() => navigate(`/task/create?project_id=${projectId}`)}
                style={{ padding: '7px 14px', backgroundColor: '#2563eb', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#fff', fontWeight: 500 }}
              >
                + Новая задача
              </button>
              {isAdmin && (
                <button onClick={handleDelete} style={{ padding: '7px 14px', backgroundColor: '#fee2e2', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#dc2626', fontWeight: 500 }}>
                  Удалить
                </button>
              )}
            </div>
          </div>

          {/* Stats badges + totals */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '16px' }}>
            {project.unestimated > 0 && (
              <span style={{ padding: '4px 12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                {project.unestimated} не рассчитано
              </span>
            )}
            {project.estimated > 0 && (
              <span style={{ padding: '4px 12px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                {project.estimated} рассчитано
              </span>
            )}
            {project.optimized > 0 && (
              <span style={{ padding: '4px 12px', backgroundColor: '#f0fdf4', color: '#15803d', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                {project.optimized} оптимизировано
              </span>
            )}
            {project.other > 0 && (
              <span style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#64748b', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                {project.other} прочих задач
              </span>
            )}
          </div>

          {/* Cost totals */}
          {(project.has_summary || totalCost !== null || optimizedCost !== null) && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #f1f5f9', alignItems: 'center' }}>
              {project.has_summary ? (
                <>
                  <span style={{ padding: '3px 10px', backgroundColor: '#f5f3ff', color: '#7c3aed', borderRadius: '12px', fontSize: '12px', fontWeight: 500 }}>
                    Сводная сформирована
                  </span>
                  {project.summary_total ? (
                    <div>
                      <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 500 }}>Итого для заказчика: </span>
                      <span style={{ fontSize: '14px', fontWeight: 700, color: '#7c3aed' }}>{formatCost(project.summary_total)}</span>
                    </div>
                  ) : (
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>Откройте сводную для сохранения итога</span>
                  )}
                </>
              ) : (
                <>
                  {totalCost !== null && (
                    <div>
                      <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 500 }}>Итого по сметам: </span>
                      <span style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>{formatCost(totalCost as number)}</span>
                    </div>
                  )}
                  {optimizedCost !== null && (
                    <div>
                      <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 500 }}>Итого оптимизированных: </span>
                      <span style={{ fontSize: '14px', fontWeight: 700, color: '#15803d' }}>{formatCost(optimizedCost as number)}</span>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Переключатель вида */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          {([['smeta', 'Сметы'], ['kanban', 'Канбан'], ['tasks', 'Задачи']] as const).map(([mode, label]) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              style={{
                border: viewMode === mode ? '1px solid #93c5fd' : '1px solid #e2e8f0',
                background: viewMode === mode ? '#eff6ff' : '#fff',
                color: viewMode === mode ? '#2563eb' : '#64748b',
                borderRadius: '6px',
                padding: '6px 14px',
                fontSize: '13px',
                cursor: 'pointer',
                fontWeight: viewMode === mode ? 600 : 400,
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {viewMode === 'smeta' ? (
          <SmetaList projectId={project.id} onCardCreated={() => setViewMode('kanban')} />
        ) : viewMode === 'kanban' ? (
          <KanbanBoard projectId={project.id} />
        ) : (
          <>
        <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
          Задачи ({project.tasks.length})
        </h2>

        {project.tasks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
            Задач в проекте пока нет
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {project.tasks.map((task: TaskBrief) => {
              const estColors = ESTIMATION_COLORS[task.estimation_status] ?? ESTIMATION_COLORS.not_applicable;
              const isEstimateType = ESTIMATE_TASK_TYPES.has(task.task_type as any);
              const taskLabel = TASK_TYPE_LABELS[task.task_type as keyof typeof TASK_TYPE_LABELS] ?? task.task_type;
              const taskDisplayName = task.name || taskLabel;
              const showCost = !!task.cost &&
                (task.estimation_status === 'estimated' || task.estimation_status === 'optimized');
              const showOptimizedCost = !!task.cost &&
                task.estimation_status === 'optimized';

              return (
                <div
                  key={task.id}
                  onClick={() => { if (task.id) navigate(`/tasks/${task.id}/status`); }}
                  style={{
                    backgroundColor: '#fff',
                    border: '1px solid #e2e8f0',
                    borderRadius: '10px',
                    overflow: 'hidden',
                    cursor: 'pointer',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)')}
                  onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'none')}
                >
                  {/* Main task row */}
                  <div
                    style={{ padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      {/* Task name with inline edit */}
                      <div style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b', marginBottom: '2px' }}>
                        <InlineEditName
                          value={taskDisplayName}
                          onSave={(name) => handleSaveTaskName(task.id, name)}
                          inputStyle={{ fontSize: '13px', fontWeight: 600, width: '220px' }}
                          iconSize={14}
                          hoverOnly
                        />
                      </div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                        {new Date(task.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </div>

                      {/* Cost info */}
                      {showCost && (
                        <div style={{ marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
                          <div>
                            <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 500 }}>Сумма по смете: </span>
                            <span style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b' }}>{formatCost(task.cost as number)}</span>
                          </div>
                          {showOptimizedCost && (
                            <div>
                              <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 500 }}>Сумма оптимизированная: </span>
                              <span style={{ fontSize: '13px', fontWeight: 600, color: '#15803d' }}>{formatCost(task.cost as number)}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    <div
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0, marginLeft: '12px' }}
                    >
                      {isEstimateType && task.task_type !== 'ESTIMATE_OPTIMIZATION' && task.estimation_status === 'estimated' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setOptimizingTaskId(task.id); }}
                          style={{ padding: '4px 12px', backgroundColor: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                        >
                          Оптимизировать
                        </button>
                      )}
                      {['estimated', 'optimized'].includes(task.estimation_status) && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setHistoryTaskId(task.id); }}
                          style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#475569', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                        >
                          История
                        </button>
                      )}
                      {task.estimation_status !== 'not_applicable' && task.task_type !== 'ESTIMATE_OPTIMIZATION' && (
                        <span style={{ padding: '3px 10px', backgroundColor: estColors.bg, color: estColors.text, borderRadius: '12px', fontSize: '12px', fontWeight: 500 }}>
                          {ESTIMATION_LABELS[task.estimation_status]}
                        </span>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteTask(task.id); }}
                        disabled={deletingTaskId === task.id}
                        title="Удалить задачу"
                        style={{ ...iconBtnStyle, color: '#dc2626', opacity: deletingTaskId === task.id ? 0.5 : 1, padding: '4px' }}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>

                </div>
              );
            })}
          </div>
        )}
          </>
        )}
      </div>
      {optimizingTaskId && (
        <OptimizeModal
          taskId={optimizingTaskId}
          onClose={() => {
            setOptimizingTaskId(null);
            loadProject();
          }}
        />
      )}
      {historyTaskId && (
        <HistoryModal
          taskId={historyTaskId}
          onClose={() => {
            setHistoryTaskId(null);
            loadProject();
          }}
        />
      )}
    </Layout>
  );
};

export default ProjectDetailPage;
