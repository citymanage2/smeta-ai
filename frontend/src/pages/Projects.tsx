import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { SectionLoader } from '../components/ui/LumaSpin';
import { ProjectCard } from '../types';
import { TASK_TYPE_LABELS } from '../types';
import { listProjects, createProject, deleteProject } from '../api/projects';

function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return '—';
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(cost);
}

function pluralTasks(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} задача`;
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return `${n} задачи`;
  return `${n} задач`;
}

interface DeleteConfirmProps {
  project: ProjectCard;
  onConfirm: () => void;
  onCancel: () => void;
  deleting: boolean;
}

const DeleteConfirmModal: React.FC<DeleteConfirmProps> = ({ project, onConfirm, onCancel, deleting }) => {
  const total = project.total_tasks ?? (project.unestimated + project.estimated + project.optimized + project.other);
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(15,23,42,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onCancel}
    >
      <div
        style={{
          background: '#fff', borderRadius: '14px', padding: '28px 32px',
          maxWidth: '420px', width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.18)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 12px', fontSize: '17px', fontWeight: 700, color: '#1e293b' }}>
          Удалить проект?
        </h3>
        <p style={{ margin: '0 0 8px', fontSize: '14px', color: '#475569', lineHeight: 1.5 }}>
          Проект <strong>«{project.name}»</strong> будет перемещён в корзину.
        </p>
        {total > 0 && (
          <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#dc2626', lineHeight: 1.5 }}>
            Вместе с ним в корзину попадут {pluralTasks(total)}.
          </p>
        )}
        {total === 0 && (
          <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#64748b' }}>
            В проекте нет задач.
          </p>
        )}
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            disabled={deleting}
            style={{
              padding: '9px 20px', background: 'transparent',
              border: '1px solid #e2e8f0', borderRadius: '8px',
              fontSize: '14px', cursor: 'pointer', color: '#64748b',
            }}
          >
            Отмена
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            style={{
              padding: '9px 20px', background: '#dc2626',
              border: 'none', borderRadius: '8px',
              fontSize: '14px', fontWeight: 600, cursor: deleting ? 'not-allowed' : 'pointer',
              color: '#fff', opacity: deleting ? 0.7 : 1,
            }}
          >
            {deleting ? 'Удаление...' : 'Удалить'}
          </button>
        </div>
      </div>
    </div>
  );
};

const Projects: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<ProjectCard | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    loadProjects();
  }, []);

  async function loadProjects() {
    setLoading(true);
    try {
      const data = await listProjects();
      setProjects(data);
    } catch {
      setError('Не удалось загрузить проекты. Проверьте соединение и обновите страницу.');
    } finally {
      setLoading(false);
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
      await loadProjects();
    } catch {
      setError('Ошибка при создании проекта');
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteConfirm() {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteProject(confirmDelete.id);
      setConfirmDelete(null);
      await loadProjects();
    } catch {
      setError('Ошибка при удалении проекта');
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Layout>
      <div style={{ maxWidth: '860px', margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#1e293b', margin: 0 }}>Проекты</h1>
          <button
            onClick={() => setShowCreate(!showCreate)}
            style={{
              padding: '8px 18px',
              backgroundColor: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 600,
            }}
          >
            + Новый проект
          </button>
        </div>

        {showCreate && (
          <form
            onSubmit={handleCreate}
            style={{
              backgroundColor: '#fff',
              border: '1px solid #e2e8f0',
              borderRadius: '12px',
              padding: '20px',
              marginBottom: '24px',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: 600 }}>Новый проект</h3>
            <input
              type="text"
              placeholder="Название проекта *"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '10px 12px',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                fontSize: '14px',
                marginBottom: '12px',
                boxSizing: 'border-box',
              }}
            />
            <textarea
              placeholder="Описание (необязательно)"
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
              rows={3}
              style={{
                width: '100%',
                padding: '10px 12px',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                fontSize: '14px',
                marginBottom: '12px',
                resize: 'vertical',
                boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="submit"
                disabled={creating}
                style={{
                  padding: '8px 18px',
                  backgroundColor: '#2563eb',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: creating ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 600,
                }}
              >
                {creating ? 'Создание...' : 'Создать'}
              </button>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                style={{
                  padding: '8px 18px',
                  backgroundColor: 'transparent',
                  color: '#64748b',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '14px',
                }}
              >
                Отмена
              </button>
            </div>
          </form>
        )}

        {error && (
          <div style={{ padding: '12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '8px', marginBottom: '16px' }}>
            {error}
          </div>
        )}

        {loading ? (
          <SectionLoader />
        ) : projects.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '48px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
            Проекты не найдены. Создайте первый проект.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '16px' }}>
            {projects.map(p => {
              const hasCost = p.total_cost !== null && p.total_cost !== undefined;
              const typeCounts = p.task_type_counts ?? {};
              const typeEntries = Object.entries(typeCounts).filter(([, cnt]) => cnt > 0);
              const totalTasks = p.total_tasks ?? (p.unestimated + p.estimated + p.optimized + p.other);

              return (
                <div
                  key={p.id}
                  onClick={() => navigate(`/projects/${p.id}`)}
                  style={{
                    backgroundColor: '#fff',
                    border: '1px solid #e2e8f0',
                    borderRadius: '12px',
                    padding: '20px 24px',
                    cursor: 'pointer',
                    transition: 'box-shadow 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)')}
                  onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                >
                  {/* Заголовок + сумма */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '14px' }}>
                    <div style={{ minWidth: 0 }}>
                      <h2 style={{ margin: '0 0 4px', fontSize: '17px', fontWeight: 600, color: '#1e293b' }}>{p.name}</h2>
                      {p.description && (
                        <p style={{ margin: 0, fontSize: '13px', color: '#64748b' }}>{p.description}</p>
                      )}
                    </div>
                    {hasCost && (
                      <div style={{ flexShrink: 0, textAlign: 'right' }}>
                        <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '2px', whiteSpace: 'nowrap' }}>
                          {p.summary_total != null ? 'Сводная сумма' : 'Сумма по сметам'}
                        </div>
                        <div style={{ fontSize: '18px', fontWeight: 700, color: p.summary_total != null ? '#7c3aed' : '#15803d', whiteSpace: 'nowrap' }}>
                          {formatCost(p.total_cost)}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Статусы задач */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: typeEntries.length > 0 ? '12px' : '0' }}>
                    {p.unestimated > 0 && (
                      <span style={{ padding: '3px 10px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                        {p.unestimated} не рассчитано
                      </span>
                    )}
                    {p.estimated > 0 && (
                      <span style={{ padding: '3px 10px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                        {p.estimated} рассчитано
                      </span>
                    )}
                    {p.optimized > 0 && (
                      <span style={{ padding: '3px 10px', backgroundColor: '#f0fdf4', color: '#15803d', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                        {p.optimized} оптимизировано
                      </span>
                    )}
                    {p.other > 0 && (
                      <span style={{ padding: '3px 10px', backgroundColor: '#f8fafc', color: '#64748b', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                        {p.other} прочих
                      </span>
                    )}
                    {totalTasks === 0 && (
                      <span style={{ fontSize: '12px', color: '#94a3b8' }}>Задач нет</span>
                    )}
                  </div>

                  {/* Виды задач */}
                  {typeEntries.length > 0 && (
                    <div style={{
                      borderTop: '1px solid #f1f5f9', paddingTop: '12px',
                      display: 'flex', flexDirection: 'column', gap: '5px',
                    }}>
                      {typeEntries.map(([type, count]) => (
                        <div key={type} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: '12px', color: '#64748b' }}>
                            {TASK_TYPE_LABELS[type] ?? type}
                          </span>
                          <span style={{
                            fontSize: '12px', fontWeight: 600, color: '#475569',
                            background: '#f1f5f9', borderRadius: '10px', padding: '1px 8px',
                          }}>
                            {count}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Кнопка удалить */}
                  <div
                    style={{ borderTop: '1px solid #f1f5f9', paddingTop: '12px', marginTop: '12px', display: 'flex', justifyContent: 'flex-end' }}
                    onClick={e => e.stopPropagation()}
                  >
                    <button
                      onClick={e => { e.stopPropagation(); setConfirmDelete(p); }}
                      style={{
                        padding: '5px 14px',
                        background: 'transparent',
                        border: '1px solid #fca5a5',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: '#dc2626',
                        cursor: 'pointer',
                        fontWeight: 500,
                      }}
                      onMouseEnter={e => { e.currentTarget.style.background = '#fef2f2'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                    >
                      Удалить проект
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {confirmDelete && (
        <DeleteConfirmModal
          project={confirmDelete}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setConfirmDelete(null)}
          deleting={deleting}
        />
      )}
    </Layout>
  );
};

export default Projects;
