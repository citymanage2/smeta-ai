import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ProjectCard, TaskBrief, TaskType, TASK_TYPE_LABELS, STATUS_LABELS } from '../types';
import { listProjects, createProject, getProject, getUnassignedTasks } from '../api/projects';

const SIDEBAR_WIDTH = 260;

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

const ProjectsSidebar: React.FC = () => {
  const navigate = useNavigate();

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

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [projectsData, unassigned] = await Promise.all([
        listProjects(),
        getUnassignedTasks(),
      ]);
      setProjects(projectsData);
      setUnassignedTasks(unassigned);
    } catch {
      setError('Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

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
        setProjectTasks(prev => ({ ...prev, [id]: detail.tasks }));
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

  function renderTaskItem(task: TaskBrief) {
    const label = TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type;
    const dotColor = STATUS_DOT_COLOR[task.status] ?? '#94a3b8';
    const subtitle = task.source_file_name ?? formatDate(task.created_at);
    const statusLabel = STATUS_LABELS[task.status as keyof typeof STATUS_LABELS] ?? task.status;

    return (
      <div
        key={task.id}
        onClick={() => navigate(`/tasks/${task.id}/status`)}
        title={`${label}\n${statusLabel}`}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '7px',
          padding: '6px 8px 6px 28px',
          margin: '1px 4px',
          borderRadius: '5px',
          cursor: 'pointer',
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
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: '12px',
              color: '#1e293b',
              lineHeight: '1.3',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {label}
          </div>
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
            {subtitle}
          </div>
        </div>
      </div>
    );
  }

  function renderSection(
    id: string,
    label: string,
    tasks: TaskBrief[],
    taskCount: number,
    isLoadingSection?: boolean,
  ) {
    const isOpen = expanded.has(id);

    return (
      <div key={id} style={{ marginBottom: '1px' }}>
        <div
          onClick={() => toggleSection(id)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '6px 8px',
            margin: '0 4px',
            borderRadius: '5px',
            cursor: 'pointer',
            userSelect: 'none',
          }}
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#e2e8f0')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <span
            style={{
              fontSize: '8px',
              color: '#64748b',
              display: 'inline-block',
              transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
              transition: 'transform 0.15s',
              lineHeight: 1,
              flexShrink: 0,
            }}
          >
            ▶
          </span>
          <span
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#334155',
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {label}
          </span>
          <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 500, flexShrink: 0 }}>
            {taskCount}
          </span>
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
              tasks.map(task => renderTaskItem(task))
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
            {renderSection('unassigned', 'Без проекта', unassignedTasks, unassignedTasks.length)}

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
