import React, { useEffect, useState, useCallback } from 'react';
import {
  listProjects, createProject, updateProject, deleteProject,
  addTaskToProject, removeTaskFromProject, getProject,
  Project, TaskSummary,
} from '../api/projects';
import StatusBadge from './StatusBadge';

interface Props {
  selectedTaskId?: string;
  onSelectTask?: (taskId: string) => void;
  /** Tasks not yet in any project (passed from parent) */
  unassignedTasks?: TaskSummary[];
  onRefresh?: () => void;
}

const TASK_TYPE_LABEL: Record<string, string> = {
  LIST_FROM_TZ: 'Перечень из ТЗ',
  LIST_FROM_TZ_PROJECT: 'Перечень ТЗ+проект',
  SMETA_FROM_LIST: 'Смета из перечня',
  SMETA_FROM_TZ: 'Смета из ТЗ',
  SMETA_FROM_TZ_PROJECT: 'Смета ТЗ+проект',
  SMETA_FROM_PROJECT: 'Смета из проекта',
  SCAN_TO_EXCEL: 'Скан → Excel',
  COMPARE_PROJECT_SMETA: 'Сравнение',
  RESEARCH_PROJECT: 'Анализ проекта',
};

const ProjectsSidebar: React.FC<Props> = ({
  selectedTaskId,
  onSelectTask,
  unassignedTasks = [],
  onRefresh,
}) => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [projectTasks, setProjectTasks] = useState<Record<string, TaskSummary[]>>({});
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [loading, setLoading] = useState(false);
  const [dragOverProject, setDragOverProject] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await listProjects();
    setProjects(data);
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleProject = async (id: string) => {
    const open = !expanded[id];
    setExpanded(prev => ({ ...prev, [id]: open }));
    if (open && !projectTasks[id]) {
      const detail = await getProject(id);
      setProjectTasks(prev => ({ ...prev, [id]: detail.tasks }));
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setLoading(true);
    try {
      await createProject(newName.trim());
      setNewName('');
      setCreating(false);
      await load();
    } finally {
      setLoading(false);
    }
  };

  const handleRename = async (id: string) => {
    if (!editName.trim()) return;
    await updateProject(id, editName.trim());
    setEditingId(null);
    await load();
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Удалить проект "${name}"? Сметы не будут удалены.`)) return;
    await deleteProject(id);
    await load();
    onRefresh?.();
  };

  // Drag-and-drop (native HTML5 — no extra deps needed)
  const handleDragStart = (e: React.DragEvent, taskId: string) => {
    e.dataTransfer.setData('taskId', taskId);
  };

  const handleDrop = async (e: React.DragEvent, projectId: string) => {
    e.preventDefault();
    const taskId = e.dataTransfer.getData('taskId');
    if (!taskId) return;
    setDragOverProject(null);
    await addTaskToProject(projectId, taskId);
    const detail = await getProject(projectId);
    setProjectTasks(prev => ({ ...prev, [projectId]: detail.tasks }));
    onRefresh?.();
  };

  const handleRemoveFromProject = async (projectId: string, taskId: string) => {
    await removeTaskFromProject(projectId, taskId);
    setProjectTasks(prev => ({
      ...prev,
      [projectId]: (prev[projectId] || []).filter(t => t.id !== taskId),
    }));
    onRefresh?.();
  };

  const taskRow = (task: TaskSummary, projectId?: string) => (
    <div
      key={task.id}
      draggable
      onDragStart={e => handleDragStart(e, task.id)}
      onClick={() => onSelectTask?.(task.id)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 8px 5px 12px',
        borderRadius: 6,
        cursor: 'pointer',
        background: selectedTaskId === task.id ? '#eff6ff' : 'transparent',
        transition: 'background 0.12s',
        fontSize: 13,
        color: '#374151',
      }}
      onMouseEnter={e => {
        if (selectedTaskId !== task.id)
          e.currentTarget.style.background = '#f9fafb';
      }}
      onMouseLeave={e => {
        if (selectedTaskId !== task.id)
          e.currentTarget.style.background = 'transparent';
      }}
    >
      <span style={{ flexGrow: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {TASK_TYPE_LABEL[task.task_type.toUpperCase()] || task.task_type}
        {task.input_files?.[0]?.name && (
          <span style={{ color: '#9ca3af', marginLeft: 4, fontSize: 11 }}>
            · {task.input_files[0].name}
          </span>
        )}
      </span>
      <StatusBadge
        taskId={task.id}
        status={task.estimate_status}
        updatedBy={task.estimate_status_updated_by}
        readonly
      />
      {projectId && (
        <button
          title="Убрать из проекта"
          onClick={e => { e.stopPropagation(); handleRemoveFromProject(projectId, task.id); }}
          style={{
            border: 'none', background: 'transparent', cursor: 'pointer',
            color: '#d1d5db', fontSize: 14, padding: '0 2px', lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </div>
  );

  return (
    <div
      style={{
        width: 280,
        flexShrink: 0,
        borderRight: '1px solid #e5e7eb',
        height: '100%',
        overflowY: 'auto',
        background: '#fafafa',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <div style={{ padding: '14px 16px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#111827' }}>Проекты</span>
        <button
          onClick={() => setCreating(v => !v)}
          title="Создать проект"
          style={{
            border: 'none', background: '#2563eb', color: '#fff',
            borderRadius: 6, padding: '3px 10px', cursor: 'pointer', fontSize: 13,
          }}
        >
          +
        </button>
      </div>

      {/* New project form */}
      {creating && (
        <div style={{ padding: '0 12px 8px', display: 'flex', gap: 6 }}>
          <input
            autoFocus
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            placeholder="Название проекта"
            style={{
              flex: 1, padding: '5px 8px', borderRadius: 6,
              border: '1px solid #d1d5db', fontSize: 13,
            }}
          />
          <button
            onClick={handleCreate}
            disabled={loading}
            style={{
              border: 'none', background: '#2563eb', color: '#fff',
              borderRadius: 6, padding: '5px 10px', cursor: 'pointer', fontSize: 13,
            }}
          >
            ✓
          </button>
        </div>
      )}

      {/* Project list */}
      {projects.map(project => (
        <div key={project.id}>
          {/* Project header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '7px 10px',
              cursor: 'pointer',
              userSelect: 'none',
              background: dragOverProject === project.id ? '#dbeafe' : 'transparent',
              borderRadius: 6,
              transition: 'background 0.12s',
            }}
            onDragOver={e => { e.preventDefault(); setDragOverProject(project.id); }}
            onDragLeave={() => setDragOverProject(null)}
            onDrop={e => handleDrop(e, project.id)}
          >
            <span
              onClick={() => toggleProject(project.id)}
              style={{ flexGrow: 1, display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <span style={{ fontSize: 12 }}>{expanded[project.id] ? '▾' : '▸'}</span>
              <span style={{ fontSize: 14, marginRight: 2 }}>📁</span>
              {editingId === project.id ? (
                <input
                  autoFocus
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleRename(project.id);
                    if (e.key === 'Escape') setEditingId(null);
                  }}
                  onBlur={() => handleRename(project.id)}
                  onClick={e => e.stopPropagation()}
                  style={{
                    fontSize: 13, fontWeight: 600, border: '1px solid #93c5fd',
                    borderRadius: 4, padding: '1px 4px', width: 130,
                  }}
                />
              ) : (
                <span style={{ fontWeight: 600, fontSize: 13, color: '#1f2937' }}>
                  {project.name}
                </span>
              )}
              <span style={{ fontSize: 11, color: '#9ca3af', marginLeft: 'auto' }}>
                {project.tasks_count}
              </span>
            </span>
            <button
              title="Переименовать"
              onClick={e => { e.stopPropagation(); setEditingId(project.id); setEditName(project.name); }}
              style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#9ca3af', fontSize: 13 }}
            >
              ✎
            </button>
            <button
              title="Удалить проект"
              onClick={e => { e.stopPropagation(); handleDelete(project.id, project.name); }}
              style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#fca5a5', fontSize: 14 }}
            >
              🗑
            </button>
          </div>

          {/* Project tasks */}
          {expanded[project.id] && (
            <div style={{ paddingLeft: 8, paddingBottom: 4 }}>
              {(projectTasks[project.id] || []).length === 0 ? (
                <span style={{ fontSize: 12, color: '#9ca3af', padding: '4px 12px', display: 'block' }}>
                  Перетащите смету сюда
                </span>
              ) : (
                (projectTasks[project.id] || []).map(t => taskRow(t, project.id))
              )}
            </div>
          )}
        </div>
      ))}

      {/* Unassigned tasks */}
      {unassignedTasks.length > 0 && (
        <div style={{ marginTop: 12, borderTop: '1px solid #e5e7eb', paddingTop: 8 }}>
          <div style={{ padding: '4px 16px', fontSize: 11, fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Без проекта
          </div>
          {unassignedTasks.map(t => taskRow(t))}
        </div>
      )}
    </div>
  );
};

export default ProjectsSidebar;
