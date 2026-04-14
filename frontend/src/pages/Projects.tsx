import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { ProjectCard } from '../types';
import { listProjects, createProject, exportProject } from '../api/projects';

function formatCost(cost: number | null): string {
  if (cost === null || cost === undefined) return '—';
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(cost);
}

const Projects: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [exportingCard, setExportingCard] = useState<{ id: string; format: 'xlsx' | 'pdf' } | null>(null);

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

  async function handleCardExport(projectId: string, format: 'xlsx' | 'pdf', e: React.MouseEvent) {
    e.stopPropagation();
    setExportingCard({ id: projectId, format });
    try {
      await exportProject(projectId, format);
    } catch {
      setError('Ошибка при экспорте проекта');
    } finally {
      setExportingCard(null);
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
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '48px' }}>Загрузка...</div>
        ) : projects.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '48px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
            Проекты не найдены. Создайте первый проект.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '16px' }}>
            {projects.map(p => (
              <div
                key={p.id}
                onClick={() => navigate(`/projects/${p.id}`)}
                style={{
                  backgroundColor: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '12px',
                  padding: '20px 24px',
                  cursor: 'pointer',
                }}
                onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)')}
                onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
              >
                <h2 style={{ margin: '0 0 6px', fontSize: '17px', fontWeight: 600, color: '#1e293b' }}>{p.name}</h2>
                {p.description && (
                  <p style={{ margin: '0 0 12px', fontSize: '13px', color: '#64748b' }}>{p.description}</p>
                )}

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '10px' }}>
                  {p.unestimated > 0 && (
                    <span style={{ padding: '3px 10px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                      {p.unestimated} не рассчитано
                    </span>
                  )}
                  {p.estimated > 0 && (
                    <span style={{ padding: '3px 10px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                      {p.estimated} рассчитано{p.total_cost !== null ? ` · ${formatCost(p.total_cost)}` : ''}
                    </span>
                  )}
                  {p.optimized > 0 && (
                    <span style={{ padding: '3px 10px', backgroundColor: '#f0fdf4', color: '#15803d', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                      {p.optimized} оптимизировано
                    </span>
                  )}
                  {p.other > 0 && (
                    <span style={{ padding: '3px 10px', backgroundColor: '#f8fafc', color: '#64748b', borderRadius: '20px', fontSize: '12px', fontWeight: 500 }}>
                      {p.other} прочих задач
                    </span>
                  )}
                  {p.unestimated === 0 && p.estimated === 0 && p.optimized === 0 && p.other === 0 && (
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>Задач нет</span>
                  )}
                </div>

                <div
                  style={{ display: 'flex', gap: '8px', marginTop: '12px', borderTop: '1px solid #f1f5f9', paddingTop: '12px' }}
                  onClick={e => e.stopPropagation()}
                >
                  <button
                    onClick={e => handleCardExport(p.id, 'xlsx', e)}
                    disabled={exportingCard !== null}
                    style={{ padding: '4px 10px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '6px', cursor: exportingCard !== null ? 'not-allowed' : 'pointer', fontSize: '12px', color: '#15803d', fontWeight: 500 }}
                  >
                    {exportingCard?.id === p.id && exportingCard?.format === 'xlsx' ? '...' : '↓ xlsx'}
                  </button>
                  <button
                    onClick={e => handleCardExport(p.id, 'pdf', e)}
                    disabled={exportingCard !== null}
                    style={{ padding: '4px 10px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '6px', cursor: exportingCard !== null ? 'not-allowed' : 'pointer', fontSize: '12px', color: '#dc2626', fontWeight: 500 }}
                  >
                    {exportingCard?.id === p.id && exportingCard?.format === 'pdf' ? '...' : '↓ PDF'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default Projects;
