import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Pencil, Check, X, Trash2 } from 'lucide-react';
import { ProjectCard, TaskBrief, TaskType, TASK_TYPE_LABELS, STATUS_LABELS } from '../types';
import { listProjects, createProject, getProject, getUnassignedTasks, updateProject } from '../api/projects';
import { updateTask } from '../api/tasks';
import { deleteTask } from '../api/admin';
import { useTaskSync } from '../stores/taskSync';

const SIDEBAR_WIDTH = 260;

// Tasks that are sub-tasks of other tasks — show only inside parent task page, not in sidebar
const HIDDEN_TASK_TYPES = new Set(['CHECK_LIST_COMPLETENESS', 'CHECK_PROJECT_COMPLETENESS']);

const STATUS_DOT_COLOR: Record<string, string> = {
  pending: '#f59e0b',
  processing: '#3b82f6',
  completed: '#16a34a',
  failed: '#dc2626',
  cancelled: '#94a3b8',
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
}

const iconStyle: React.CSSProperties = {
  color: '#94a3b8',
  cursor: 'pointer',
  flexShrink: 0,
};

const ProjectsSidebar: React.FC = () => {
  const navigate = useNavigate();

  const { version: taskSyncVersion } = useTaskSync();
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [unassignedTasks, setUnassignedTasks] = useState<TaskBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [expanded, setExpanded] = useState<Set<string>>(new Set(['unassigned']));
  const [projectTasks, setProjectTasks] = useState<Record<string, TaskBrief[]>>({});
  const [loadingTasks, setLoadingTasks] = useState<Set<string>>(new Set());

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);

  // Inline edit state
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [projectsData, unassigned] = await Promise.all([
        listProjects(),
        getUnassignedTasks(),
      ]);
      setProjects(projectsData);
      setUnassignedTasks(unassigned.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)));
      // сбрасываем кэш задач по проектам — они будут перезагружены при раскрытии
      setProjectTasks({});
    } catch {
      setError('Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [taskSyncVersion]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingProjectId, editingTaskId]);

  async function toggleSection(id: string) {
    const isExpanding = !expanded.has(id);
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

    if (isExpanding && id !== 'unassigned' && !projectTasks[id]) {
      setLoadingTasks(prev => new Set(prev).add(id));
      try {
        const detail = await getProject(id);
        setProjectTasks(prev => ({ ...prev, [id]: detail.tasks.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)) }));
      } catch {
        // ignore
      } finally {
        setLoadingTasks(prev => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await createProject({ name: newName.trim(), description: newDesc.trim() || undefined });
      setNewName('');
      setNewDesc('');
      setShowCreate(false);
      await loadData();
    } catch {
      setError('Ошибка при создании');
    } finally {
      setCreating(false);
    }
  }

  function startProjectEdit(id: string, currentName: string, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingTaskId(null);
    setEditingProjectId(id);
    setEditValue(currentName);
  }

  function startTaskEdit(taskId: string, currentName: string, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingProjectId(null);
    setEditingTaskId(taskId);
    setEditValue(currentName);
  }

  function cancelEdit() {
    setEditingProjectId(null);
    setEditingTaskId(null);
    setEditValue('');
  }

  async function saveProjectEdit(projectId: string) {
    const trimmed = editValue.trim();
    if (!trimmed) { cancelEdit(); return; }
    try {
      await updateProject(projectId, { name: trimmed });
      setProjects(prev => prev.map(p => p.id === projectId ? { ...p, name: trimmed } : p));
    } catch {
      setError('Ошибка при сохранении');
    }
    cancelEdit();
  }

  async function saveTaskEdit(taskId: string, isUnassigned: boolean, projectId?: string) {
    const trimmed = editValue.trim();
    if (!trimmed) { cancelEdit(); return; }
    try {
      await updateTask(taskId, { name: trimmed });
      const updater = (tasks: TaskBrief[]) =>
        tasks.map(t => t.id === taskId ? { ...t, name: trimmed } : t);
      if (isUnassigned) {
        setUnassignedTasks(updater);
      } else if (projectId) {
        setProjectTasks(prev => ({
          ...prev,
          [projectId]: updater(prev[projectId] ?? []),
        }));
      }
    } catch {
      setError('Ошибка при сохранении');
    }
    cancelEdit();
  }

  function handleProjectEditKeyDown(e: React.KeyboardEvent, projectId: string) {
    if (e.key === 'Enter') { e.preventDefault(); saveProjectEdit(projectId); }
    if (e.key === 'Escape') cancelEdit();
  }

  function handleTaskEditKeyDown(e: React.KeyboardEvent, taskId: string, isUnassigned: boolean, projectId?: string) {
    if (e.key === 'Enter') { e.preventDefault(); saveTaskEdit(taskId, isUnassigned, projectId); }
    if (e.key === 'Escape') cancelEdit();
  }

  async function handleDeleteTask(taskId: string, isUnassigned: boolean, projectId?: string) {
    if (!window.confirm('Переместить задачу в корзину?')) return;
    try {
      await deleteTask(taskId);
      const now = new Date().toISOString();
      const markDeleted = (tasks: TaskBrief[]) =>
        tasks.map(t => t.id === taskId ? { ...t, deleted_at: now } : t);
      if (isUnassigned) {
        setUnassignedTasks(markDeleted);
      } else if (projectId) {
        setProjectTasks(prev => ({ ...prev, [projectId]: markDeleted(prev[projectId] ?? []) }));
      }
    } catch {
      setError('Не удалось переместить задачу в корзину');
    }
  }

  function renderTaskItem(task: TaskBrief, isUnassigned: boolean, projectId?: string) {
    const label = TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type;
    const displayName = task.name || label;
    const isInTrash = !!task.deleted_at;
    const dotColor = isInTrash ? '#cbd5e1' : (STATUS_DOT_COLOR[task.status] ?? '#94a3b8');
    const subtitle = task.source_file_name ?? formatDate(task.created_at);
    const statusLabel = STATUS_LABELS[task.status as keyof typeof STATUS_LABELS] ?? task.status;
    const isEditing = !isInTrash && editingTaskId === task.id;

    return (
      <div
        key={task.id}
        title={isEditing ? undefined : isInTrash ? `${displayName}\nВ корзине` : `${displayName}\n${statusLabel}`}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '7px',
          padding: '6px 8px 6px 28px',
          margin: '1px 4px',
          borderRadius: '5px',
          opacity: isInTrash ? 0.55 : 1,
        }}
        onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#e2e8f0')}
        onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            backgroundColor: dotColor,
            flexShrink: 0,
            marginTop: 4,
          }}
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          {isEditing ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <input
                ref={editInputRef}
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onKeyDown={e => handleTaskEditKeyDown(e, task.id, isUnassigned, projectId)}
                onClick={e => e.stopPropagation()}
                style={{
                  flex: 1,
                  fontSize: '12px',
                  border: '1px solid #93c5fd',
                  borderRadius: '4px',
                  padding: '2px 5px',
                  outline: 'none',
                  minWidth: 0,
                }}
              />
              <Check
                size={13}
                style={{ ...iconStyle, color: '#16a34a' }}
                onClick={e => { e.stopPropagation(); saveTaskEdit(task.id, isUnassigned, projectId); }}
              />
              <X
                size={13}
                style={{ ...iconStyle, color: '#dc2626' }}
                onClick={e => { e.stopPropagation(); cancelEdit(); }}
              />
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <div
                onClick={() => navigate(`/tasks/${task.id}/status`)}
                style={{
                  fontSize: '12px',
                  color: isInTrash ? '#94a3b8' : '#1e293b',
                  lineHeight: '1.3',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  cursor: 'pointer',
                  flex: 1,
                  minWidth: 0,
                  textDecoration: isInTrash ? 'line-through' : 'none',
                }}
              >
                {displayName}
              </div>
              {!isInTrash && (
                <>
                  <Pencil
                    size={11}
                    style={iconStyle}
                    onClick={e => startTaskEdit(task.id, displayName, e)}
                  />
                  <Trash2
                    size={11}
                    style={{ ...iconStyle, color: '#ef4444' }}
                    onClick={e => { e.stopPropagation(); handleDeleteTask(task.id, isUnassigned, projectId ?? undefined); }}
                  />
                </>
              )}
            </div>
          )}
          {!isEditing && (
            <div
              style={{
                fontSize: '11px',
                color: '#94a3b8',
                marginTop: '1px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {isInTrash ? 'В корзине' : subtitle}
            </div>
          )}
        </div>
      </div>
    );
  }

  function renderSection(
    id: string,
    label: string,
    tasks: TaskBrief[],
    taskCount: number,
    isUnassigned: boolean,
    isLoadingSection?: boolean,
  ) {
    const isOpen = expanded.has(id);
    const isEditingProject = !isUnassigned && editingProjectId === id;

    return (
      <div key={id} style={{ marginBottom: '1px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '6px 8px',
            margin: '0 4px',
            borderRadius: '5px',
            userSelect: 'none',
          }}
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#e2e8f0')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          {/* Toggle arrow */}
          <span
            onClick={e => { e.stopPropagation(); toggleSection(id); }}
            style={{
              fontSize: '8px',
              color: '#64748b',
              display: 'inline-block',
              transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
              transition: 'transform 0.15s',
              lineHeight: 1,
              flexShrink: 0,
              cursor: 'pointer',
              padding: '2px',
            }}
          >
            ▶
          </span>

          {/* Project name / edit input */}
          {isEditingProject ? (
            <>
              <input
                ref={editInputRef}
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onKeyDown={e => handleProjectEditKeyDown(e, id)}
                onClick={e => e.stopPropagation()}
                style={{
                  flex: 1,
                  fontSize: '12px',
                  fontWeight: 600,
                  border: '1px solid #93c5fd',
                  borderRadius: '4px',
                  padding: '2px 6px',
                  outline: 'none',
                  minWidth: 0,
                }}
              />
              <Check
                size={14}
                style={{ ...iconStyle, color: '#16a34a' }}
                onClick={e => { e.stopPropagation(); saveProjectEdit(id); }}
              />
              <X
                size={14}
                style={{ ...iconStyle, color: '#dc2626' }}
                onClick={e => { e.stopPropagation(); cancelEdit(); }}
              />
            </>
          ) : (
            <>
              <span
                onClick={isUnassigned ? undefined : e => { e.stopPropagation(); navigate(`/projects/${id}`); }}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#334155',
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  cursor: isUnassigned ? 'default' : 'pointer',
                }}
              >
                {label}
              </span>
              {!isUnassigned && (
                <Pencil
                  size={12}
                  style={iconStyle}
                  onClick={e => startProjectEdit(id, label, e)}
                />
              )}
              <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 500, flexShrink: 0 }}>
                {taskCount}
              </span>
            </>
          )}
        </div>

        {isOpen && (
          <div>
            {isLoadingSection ? (
              <div style={{ padding: '5px 28px', fontSize: '11px', color: '#94a3b8' }}>
                Загрузка...
              </div>
            ) : tasks.length === 0 ? (
              <div style={{ padding: '5px 28px', fontSize: '11px', color: '#94a3b8' }}>
                Нет задач
              </div>
            ) : (
              tasks.map(task => renderTaskItem(task, isUnassigned, isUnassigned ? undefined : id))
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      style={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        borderRight: '1px solid #e2e8f0',
        backgroundColor: '#f8fafc',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header: new project button */}
      <div
        style={{
          padding: '10px 10px 8px',
          borderBottom: '1px solid #e2e8f0',
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => setShowCreate(v => !v)}
          style={{
            width: '100%',
            padding: '7px 10px',
            backgroundColor: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: '7px',
            cursor: 'pointer',
            fontSize: '12px',
            fontWeight: 600,
            textAlign: 'left',
          }}
        >
          + Новый проект
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <form
          onSubmit={handleCreate}
          style={{
            padding: '10px',
            borderBottom: '1px solid #e2e8f0',
            backgroundColor: '#fff',
            flexShrink: 0,
          }}
        >
          <input
            type="text"
            placeholder="Название *"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            required
            style={{
              width: '100%',
              padding: '6px 8px',
              border: '1px solid #e2e8f0',
              borderRadius: '5px',
              fontSize: '12px',
              marginBottom: '6px',
              boxSizing: 'border-box',
              outline: 'none',
            }}
          />
          <textarea
            placeholder="Описание"
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            rows={2}
            style={{
              width: '100%',
              padding: '6px 8px',
              border: '1px solid #e2e8f0',
              borderRadius: '5px',
              fontSize: '12px',
              marginBottom: '6px',
              resize: 'vertical',
              boxSizing: 'border-box',
              outline: 'none',
            }}
          />
          <div style={{ display: 'flex', gap: '5px' }}>
            <button
              type="submit"
              disabled={creating}
              style={{
                flex: 1,
                padding: '5px 8px',
                backgroundColor: '#2563eb',
                color: '#fff',
                border: 'none',
                borderRadius: '5px',
                cursor: creating ? 'not-allowed' : 'pointer',
                fontSize: '11px',
                fontWeight: 600,
              }}
            >
              {creating ? '...' : 'Создать'}
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              style={{
                padding: '5px 8px',
                backgroundColor: 'transparent',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: '5px',
                cursor: 'pointer',
                fontSize: '11px',
              }}
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            padding: '6px 10px',
            fontSize: '11px',
            color: '#dc2626',
            backgroundColor: '#fef2f2',
            borderBottom: '1px solid #fecaca',
            flexShrink: 0,
          }}
        >
          {error}
        </div>
      )}

      {/* Scrollable tree */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {loading ? (
          <div
            style={{
              padding: '24px 10px',
              textAlign: 'center',
              color: '#94a3b8',
              fontSize: '12px',
            }}
          >
            Загрузка...
          </div>
        ) : (
          <>
            {renderSection('unassigned', 'Без проекта', unassignedTasks, unassignedTasks.length, true)}

            {projects.length > 0 && (
              <div
                style={{ height: '1px', backgroundColor: '#e2e8f0', margin: '6px 10px' }}
              />
            )}

            {projects.map(p =>
              renderSection(
                p.id,
                p.name,
                projectTasks[p.id] ?? [],
                p.unestimated + p.estimated + p.optimized + p.other,
                false,
                loadingTasks.has(p.id),
              ),
            )}

            {projects.length === 0 && (
              <div style={{ padding: '10px 12px', fontSize: '11px', color: '#94a3b8' }}>
                Проектов пока нет
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default ProjectsSidebar;
