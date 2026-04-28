import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Pencil, Check, X, Trash2, ChevronRight, ChevronsRight,
  FolderOpen, Plus,
} from 'lucide-react';
import { ProjectCard, TaskBrief, TaskType, TASK_TYPE_LABELS, STATUS_LABELS } from '../types';
import { listProjects, createProject, getProject, getUnassignedTasks, updateProject } from '../api/projects';
import { updateTask } from '../api/tasks';
import { deleteTask } from '../api/admin';
import { useTaskSync } from '../stores/taskSync';

const SIDEBAR_WIDTH = 264;
const SIDEBAR_COLLAPSED_WIDTH = 44;

const HIDDEN_TASK_TYPES = new Set(['CHECK_LIST_COMPLETENESS', 'CHECK_PROJECT_COMPLETENESS']);

const STATUS_DOT_COLOR: Record<string, string> = {
  pending: '#f59e0b',
  processing: '#3b82f6',
  completed: '#22c55e',
  failed: '#ef4444',
  cancelled: '#94a3b8',
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
}

interface Props {
  open: boolean;
  onToggle: () => void;
}

const ProjectsSidebar: React.FC<Props> = ({ open, onToggle }) => {
  const navigate = useNavigate();
  const location = useLocation();
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

  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [projectsData, unassigned] = await Promise.all([listProjects(), getUnassignedTasks()]);
      setProjects(projectsData);
      setUnassignedTasks(unassigned.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)));
      setProjectTasks({});
    } catch {
      setError('Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [taskSyncVersion]);

  useEffect(() => { loadData(); }, [loadData]);

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
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

    if (isExpanding && id !== 'unassigned' && !projectTasks[id]) {
      setLoadingTasks(prev => new Set(prev).add(id));
      try {
        const detail = await getProject(id);
        setProjectTasks(prev => ({
          ...prev,
          [id]: detail.tasks.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)),
        }));
      } catch {
        // ignore
      } finally {
        setLoadingTasks(prev => { const next = new Set(prev); next.delete(id); return next; });
      }
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await createProject({ name: newName.trim(), description: newDesc.trim() || undefined });
      setNewName(''); setNewDesc(''); setShowCreate(false);
      await loadData();
    } catch {
      setError('Ошибка при создании');
    } finally {
      setCreating(false);
    }
  }

  function startProjectEdit(id: string, currentName: string, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingTaskId(null); setEditingProjectId(id); setEditValue(currentName);
  }

  function startTaskEdit(taskId: string, currentName: string, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingProjectId(null); setEditingTaskId(taskId); setEditValue(currentName);
  }

  function cancelEdit() {
    setEditingProjectId(null); setEditingTaskId(null); setEditValue('');
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
      const updater = (tasks: TaskBrief[]) => tasks.map(t => t.id === taskId ? { ...t, name: trimmed } : t);
      if (isUnassigned) setUnassignedTasks(updater);
      else if (projectId) setProjectTasks(prev => ({ ...prev, [projectId]: updater(prev[projectId] ?? []) }));
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
      const removeTask = (tasks: TaskBrief[]) => tasks.filter(t => t.id !== taskId);
      if (isUnassigned) setUnassignedTasks(removeTask);
      else if (projectId) setProjectTasks(prev => ({ ...prev, [projectId]: removeTask(prev[projectId] ?? []) }));
    } catch {
      setError('Не удалось переместить задачу в корзину');
    }
  }

  function renderTaskItem(task: TaskBrief, isUnassigned: boolean, projectId?: string) {
    const label = TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type;
    const displayName = task.name || label;
    const dotColor = STATUS_DOT_COLOR[task.status] ?? '#94a3b8';
    const subtitle = task.source_file_name ?? formatDate(task.created_at);
    const statusLabel = STATUS_LABELS[task.status as keyof typeof STATUS_LABELS] ?? task.status;
    const isEditing = editingTaskId === task.id;

    return (
      <div key={task.id} title={isEditing ? undefined : `${displayName} · ${statusLabel}`} style={taskItemStyle} className="sidebar-task-item">
        {/* Status dot */}
        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: dotColor, flexShrink: 0, marginTop: 5 }} />

        <div style={{ minWidth: 0, flex: 1 }}>
          {isEditing ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <input
                ref={editInputRef}
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onKeyDown={e => handleTaskEditKeyDown(e, task.id, isUnassigned, projectId)}
                onClick={e => e.stopPropagation()}
                style={editInputStyle}
              />
              <Check size={13} style={iconGreen} onClick={e => { e.stopPropagation(); saveTaskEdit(task.id, isUnassigned, projectId); }} />
              <X size={13} style={iconRed} onClick={e => { e.stopPropagation(); cancelEdit(); }} />
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }} className="task-row-inner">
              <div
                onClick={() => {
                  const dest = task.task_type === 'ESTIMATE_OPTIMIZATION' && task.status === 'completed'
                    ? `/tasks/${task.id}/estimate`
                    : `/tasks/${task.id}/status`;
                  navigate(dest);
                }}
                style={taskNameStyle}
              >
                {displayName}
              </div>
              <div style={{ display: 'flex', gap: 2, flexShrink: 0 }} className="task-actions">
                <ActionBtn onClick={e => startTaskEdit(task.id, displayName, e)} title="Переименовать">
                  <Pencil size={11} />
                </ActionBtn>
                <ActionBtn onClick={e => { e.stopPropagation(); handleDeleteTask(task.id, isUnassigned, projectId ?? undefined); }} title="Удалить" danger>
                  <Trash2 size={11} />
                </ActionBtn>
              </div>
            </div>
          )}
          {!isEditing && (
            <div style={taskSubtitleStyle}>{subtitle}</div>
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
      <div key={id} style={{ marginBottom: 2 }}>
        {/* Section header */}
        <div
          style={sectionHeaderStyle}
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#f1f5f9')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          {/* Chevron toggle */}
          <button
            onClick={e => { e.stopPropagation(); toggleSection(id); }}
            style={chevronBtnStyle}
          >
            <ChevronRight
              size={13}
              style={{
                transition: 'transform 0.18s',
                transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                color: '#64748b',
              }}
            />
          </button>

          {/* Label / edit */}
          {isEditingProject ? (
            <>
              <input
                ref={editInputRef}
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onKeyDown={e => handleProjectEditKeyDown(e, id)}
                onClick={e => e.stopPropagation()}
                style={{ ...editInputStyle, fontWeight: 600 }}
              />
              <Check size={14} style={iconGreen} onClick={e => { e.stopPropagation(); saveProjectEdit(id); }} />
              <X size={14} style={iconRed} onClick={e => { e.stopPropagation(); cancelEdit(); }} />
            </>
          ) : (
            <>
              <span
                onClick={isUnassigned ? () => toggleSection(id) : e => { e.stopPropagation(); navigate(`/projects/${id}`); }}
                style={sectionLabelStyle(isUnassigned)}
              >
                {label}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, marginLeft: 'auto' }}>
                {!isUnassigned && (
                  <ActionBtn onClick={e => startProjectEdit(id, label, e)} title="Переименовать проект">
                    <Pencil size={11} />
                  </ActionBtn>
                )}
                <span style={badgeStyle}>{taskCount}</span>
              </div>
            </>
          )}
        </div>

        {/* Task list */}
        {isOpen && (
          <div>
            {isLoadingSection ? (
              <div style={emptyStyle}>Загрузка...</div>
            ) : tasks.length === 0 ? (
              <div style={emptyStyle}>Нет задач</div>
            ) : (
              tasks.map(task => renderTaskItem(task, isUnassigned, isUnassigned ? undefined : id))
            )}
          </div>
        )}
      </div>
    );
  }

  // ─── Collapsed sidebar ────────────────────────────────────────
  if (!open) {
    return (
      <div
        style={{
          width: SIDEBAR_COLLAPSED_WIDTH,
          minWidth: SIDEBAR_COLLAPSED_WIDTH,
          borderRight: '1px solid #e2e8f0',
          backgroundColor: '#ffffff',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          overflow: 'hidden',
          transition: 'width 0.22s ease',
        }}
      >
        {/* Action buttons */}
        <div style={{ padding: '10px 0 6px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, borderBottom: '1px solid #f1f5f9', width: '100%' }}>
          <CollapsedNavBtn
            onClick={() => navigate('/task/create')}
            tooltip="Создать задачу"
            active={location.pathname === '/task/create'}
          >
            <Plus size={16} />
          </CollapsedNavBtn>
          <CollapsedNavBtn
            onClick={() => setShowCreate(v => !v)}
            tooltip="Создать новый проект"
            active={false}
          >
            <FolderOpen size={14} />
          </CollapsedNavBtn>
        </div>

        {/* Project list */}
        <div style={{ flex: 1, overflowY: 'auto', width: '100%', padding: '6px 0' }}>
          {/* Без проекта */}
          <CollapsedProjectBtn
            onClick={() => navigate('/projects/unassigned')}
            tooltip="Без проекта"
            active={location.pathname === '/projects/unassigned'}
            initials="БП"
          />

          {projects.map(p => (
            <CollapsedProjectBtn
              key={p.id}
              onClick={() => navigate(`/projects/${p.id}`)}
              tooltip={p.name}
              active={location.pathname === `/projects/${p.id}`}
              initials={getInitials(p.name)}
            />
          ))}
        </div>

        {/* Expand button */}
        <button onClick={onToggle} data-tooltip="Показать панель" className="sidebar-fast-tooltip" style={toggleBtnStyle}>
          <ChevronsRight size={15} color="#64748b" />
        </button>
      </div>
    );
  }

  // ─── Expanded sidebar ─────────────────────────────────────────
  return (
    <div
      style={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        borderRight: '1px solid #e2e8f0',
        backgroundColor: '#ffffff',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        transition: 'width 0.22s ease',
      }}
    >
      {/* Header */}
      <div style={{ padding: '10px 10px 8px', borderBottom: '1px solid #f1f5f9', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={() => navigate('/task/create')}
            style={primaryBtnStyle}
          >
            <Plus size={13} />
            Новая задача
          </button>
          <button
            onClick={() => setShowCreate(v => !v)}
            title="Создать новый проект"
            style={secondaryBtnStyle}
          >
            <FolderOpen size={14} />
          </button>
        </div>
      </div>

      {/* Create form */}
      {showCreate && (
        <form onSubmit={handleCreate} style={createFormStyle}>
          <input
            type="text"
            placeholder="Название *"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            required
            style={formInputStyle}
          />
          <textarea
            placeholder="Описание (необязательно)"
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            rows={2}
            style={{ ...formInputStyle, resize: 'vertical', marginBottom: 6 }}
          />
          <div style={{ display: 'flex', gap: 5 }}>
            <button type="submit" disabled={creating} style={primaryBtnStyle}>
              {creating ? '...' : 'Создать'}
            </button>
            <button type="button" onClick={() => setShowCreate(false)} style={secondaryBtnStyle}>
              Отмена
            </button>
          </div>
        </form>
      )}

      {/* Error */}
      {error && (
        <div style={{ padding: '6px 10px', fontSize: 11, color: '#dc2626', backgroundColor: '#fef2f2', borderBottom: '1px solid #fecaca', flexShrink: 0 }}>
          {error}
        </div>
      )}

      {/* Scrollable tree */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0 48px' }}>
        {loading ? (
          <div style={{ padding: '24px 10px', textAlign: 'center', color: '#94a3b8', fontSize: 12 }}>
            Загрузка...
          </div>
        ) : (
          <>
            {renderSection('unassigned', 'Без проекта', unassignedTasks, unassignedTasks.length, true)}

            {projects.length > 0 && (
              <div style={{ height: 1, backgroundColor: '#f1f5f9', margin: '6px 12px' }} />
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

            {projects.length === 0 && !loading && (
              <div style={{ padding: '8px 12px', fontSize: 11, color: '#cbd5e1' }}>
                Проектов пока нет
              </div>
            )}
          </>
        )}
      </div>

      {/* Collapse button */}
      <button onClick={onToggle} style={collapseBarStyle}>
        <ChevronsRight size={14} style={{ transform: 'rotate(180deg)', color: '#64748b' }} />
        <span style={{ fontSize: 12, color: '#64748b', fontWeight: 500 }}>Скрыть</span>
      </button>
    </div>
  );
};

// ─── Styles ────────────────────────────────────────────────────────────────

const sectionHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
  padding: '5px 8px 5px 6px',
  margin: '0 4px',
  borderRadius: 6,
  userSelect: 'none',
  cursor: 'default',
  transition: 'background-color 0.1s',
};

const sectionLabelStyle = (isUnassigned: boolean): React.CSSProperties => ({
  fontSize: 12,
  fontWeight: 600,
  color: '#334155',
  flex: 1,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  cursor: isUnassigned ? 'pointer' : 'pointer',
  minWidth: 0,
});

const taskItemStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 7,
  padding: '5px 8px 5px 30px',
  margin: '1px 4px',
  borderRadius: 5,
  cursor: 'default',
  position: 'relative',
};

const taskNameStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#1e293b',
  lineHeight: '1.35',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  flex: 1,
  minWidth: 0,
};

const taskSubtitleStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#94a3b8',
  marginTop: 1,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
};

const chevronBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 20,
  height: 20,
  border: 'none',
  background: 'none',
  cursor: 'pointer',
  padding: 0,
  borderRadius: 4,
  flexShrink: 0,
};

const badgeStyle: React.CSSProperties = {
  fontSize: 10,
  color: '#94a3b8',
  fontWeight: 600,
  backgroundColor: '#f1f5f9',
  padding: '1px 6px',
  borderRadius: 10,
  minWidth: 18,
  textAlign: 'center',
};

const emptyStyle: React.CSSProperties = {
  padding: '4px 30px',
  fontSize: 11,
  color: '#cbd5e1',
  fontStyle: 'italic',
};

const editInputStyle: React.CSSProperties = {
  flex: 1,
  fontSize: 12,
  border: '1px solid #93c5fd',
  borderRadius: 4,
  padding: '2px 6px',
  outline: 'none',
  minWidth: 0,
  backgroundColor: '#fff',
};

const iconGreen: React.CSSProperties = { color: '#16a34a', cursor: 'pointer', flexShrink: 0 };
const iconRed: React.CSSProperties = { color: '#dc2626', cursor: 'pointer', flexShrink: 0 };

const primaryBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 5,
  flex: 1,
  padding: '7px 10px',
  backgroundColor: '#2563eb',
  color: '#fff',
  border: 'none',
  borderRadius: 7,
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
};

const secondaryBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 5,
  padding: '7px 10px',
  backgroundColor: 'transparent',
  color: '#64748b',
  border: '1px solid #e2e8f0',
  borderRadius: 7,
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 500,
};

const createFormStyle: React.CSSProperties = {
  padding: '10px',
  borderBottom: '1px solid #f1f5f9',
  backgroundColor: '#fafafa',
  flexShrink: 0,
};

const formInputStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px 8px',
  border: '1px solid #e2e8f0',
  borderRadius: 5,
  fontSize: 12,
  marginBottom: 6,
  boxSizing: 'border-box',
  outline: 'none',
  backgroundColor: '#fff',
};

const collapseBarStyle: React.CSSProperties = {
  position: 'absolute',
  bottom: 0,
  left: 0,
  right: 0,
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  padding: '10px 12px',
  borderTop: '1px solid #f1f5f9',
  backgroundColor: '#ffffff',
  cursor: 'pointer',
  border: 'none',
  width: '100%',
  textAlign: 'left',
};

const toggleBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: '100%',
  padding: '12px 0',
  borderTop: '1px solid #f1f5f9',
  backgroundColor: '#ffffff',
  border: 'none',
  cursor: 'pointer',
};


// ─── ActionBtn: shows on hover of parent ──────────────────────────────────

interface ActionBtnProps {
  onClick: (e: React.MouseEvent) => void;
  title?: string;
  danger?: boolean;
  children: React.ReactNode;
}

const ActionBtn: React.FC<ActionBtnProps> = ({ onClick, title, danger, children }) => {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 20,
        height: 20,
        borderRadius: 4,
        border: 'none',
        cursor: 'pointer',
        backgroundColor: hovered ? (danger ? '#fee2e2' : '#f1f5f9') : 'transparent',
        color: hovered ? (danger ? '#dc2626' : '#334155') : '#94a3b8',
        padding: 0,
        transition: 'background-color 0.1s, color 0.1s',
      }}
    >
      {children}
    </button>
  );
};

// ─── Helpers for collapsed project icons ──────────────────────────────────

function getInitials(name: string): string {
  const words = name.trim().split(/\s+/);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

// Action button (Plus, FolderOpen) with active/hover states
const CollapsedNavBtn: React.FC<{
  onClick: () => void;
  tooltip: string;
  active: boolean;
  children: React.ReactNode;
}> = ({ onClick, tooltip, active, children }) => {
  const [hovered, setHovered] = useState(false);
  const bg = active ? '#ffffff' : hovered ? '#f1f5f9' : 'transparent';
  const border = active ? '1.5px solid #bfdbfe' : '1.5px solid transparent';
  const color = active ? '#2563eb' : hovered ? '#334155' : '#94a3b8';
  return (
    <button
      onClick={onClick}
      data-tooltip={tooltip}
      className="sidebar-fast-tooltip"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 34,
        height: 34,
        borderRadius: 8,
        border,
        backgroundColor: bg,
        cursor: 'pointer',
        color,
        transition: 'background-color 0.12s, border-color 0.12s, color 0.12s',
        boxShadow: active ? '0 1px 4px rgba(37,99,235,0.10)' : 'none',
        padding: 0,
      }}
    >
      {React.cloneElement(children as React.ReactElement, { color })}
    </button>
  );
};

// Project icon button with active/hover states
const CollapsedProjectBtn: React.FC<{
  onClick: () => void;
  tooltip: string;
  active: boolean;
  initials: string;
}> = ({ onClick, tooltip, active, initials }) => {
  const [hovered, setHovered] = useState(false);
  const bg = active ? '#ffffff' : hovered ? '#f1f5f9' : 'transparent';
  const border = active ? '1.5px solid #bfdbfe' : '1.5px solid transparent';
  const textColor = active ? '#2563eb' : hovered ? '#334155' : '#94a3b8';
  return (
    <button
      onClick={onClick}
      data-tooltip={tooltip}
      className="sidebar-fast-tooltip"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100%',
        padding: '3px 0',
        border: 'none',
        backgroundColor: 'transparent',
        cursor: 'pointer',
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          backgroundColor: bg,
          border,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 11,
          fontWeight: 700,
          color: textColor,
          letterSpacing: '0.5px',
          flexShrink: 0,
          transition: 'background-color 0.12s, border-color 0.12s, color 0.12s',
          boxShadow: active ? '0 1px 4px rgba(37,99,235,0.10)' : 'none',
        }}
      >
        {initials}
      </div>
    </button>
  );
};

export default ProjectsSidebar;
