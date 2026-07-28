import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { SectionLoader } from '../components/ui/LumaSpin';
import { ProjectCard, TaskBrief, TASK_TYPE_LABELS } from '../types';
import { listProjects, getUnassignedTasks, archiveProject, archiveTask } from '../api/projects';

// ---------------------------------------------------------------------------
// Единая точка входа в архив: проекты и «ничейные» задачи, перемещённые в архив.
// Переключатели «Активные / Архив» на страницах «Проекты» и «Входящий» остаются
// как есть — эта страница их не заменяет, а дополняет общим обзором.
// ---------------------------------------------------------------------------

function formatDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

const Archive: React.FC = () => {
  const navigate = useNavigate();

  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [tasks, setTasks] = useState<TaskBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [projData, taskData] = await Promise.all([
        listProjects(true),
        getUnassignedTasks(true),
      ]);
      setProjects(projData);
      setTasks(taskData);
    } catch {
      setError('Не удалось загрузить архив. Проверьте соединение и обновите страницу.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleRestoreProject(p: ProjectCard) {
    setBusyId(p.id);
    setError('');
    try {
      await archiveProject(p.id, false);
      setProjects(prev => prev.filter(x => x.id !== p.id));
    } catch {
      setError('Не удалось вернуть проект из архива.');
    } finally {
      setBusyId(null);
    }
  }

  async function handleRestoreTask(t: TaskBrief) {
    setBusyId(t.id);
    setError('');
    try {
      await archiveTask(t.id, false);
      setTasks(prev => prev.filter(x => x.id !== t.id));
    } catch {
      setError('Не удалось вернуть задачу из архива.');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Layout>
      <div style={{ maxWidth: '860px', margin: '0 auto' }}>
        <div style={{ marginBottom: '24px' }}>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#1e293b', margin: '0 0 4px' }}>Архив</h1>
          <p style={{ fontSize: '14px', color: '#64748b', margin: 0 }}>
            Проекты и задачи, перемещённые в архив
          </p>
        </div>

        {error && (
          <div style={{ padding: '12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '8px', marginBottom: '16px' }}>
            {error}
          </div>
        )}

        {loading ? (
          <SectionLoader />
        ) : (
          <>
            {/* ── Проекты в архиве ── */}
            <section style={{ marginBottom: '36px' }}>
              <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#334155', margin: '0 0 16px' }}>
                Проекты в архиве
              </h2>

              {projects.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#94a3b8', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                  В архиве нет проектов.
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
                        transition: 'box-shadow 0.15s',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)')}
                      onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' }}>
                        <div style={{ minWidth: 0 }}>
                          <h3 style={{ margin: '0 0 4px', fontSize: '17px', fontWeight: 600, color: '#1e293b' }}>{p.name}</h3>
                          {p.description && (
                            <p style={{ margin: '0 0 4px', fontSize: '13px', color: '#64748b' }}>{p.description}</p>
                          )}
                          {p.owner_name && (
                            <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                              Ответственный: <span style={{ color: '#475569', fontWeight: 500 }}>{p.owner_name}</span>
                            </div>
                          )}
                          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                            {formatDate(p.created_at)}
                          </div>
                        </div>

                        <button
                          onClick={e => { e.stopPropagation(); handleRestoreProject(p); }}
                          disabled={busyId === p.id}
                          style={{
                            flexShrink: 0,
                            padding: '5px 14px',
                            background: 'transparent',
                            border: '1px solid #cbd5e1',
                            borderRadius: '6px',
                            fontSize: '12px',
                            color: '#475569',
                            cursor: busyId === p.id ? 'not-allowed' : 'pointer',
                            fontWeight: 500,
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = '#f1f5f9'; }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                        >
                          {busyId === p.id ? 'Возврат…' : 'Вернуть из архива'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* ── Задачи без проекта в архиве ── */}
            <section>
              <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#334155', margin: '0 0 16px' }}>
                Задачи без проекта в архиве
              </h2>

              {tasks.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#94a3b8', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                  В архиве нет задач.
                </div>
              ) : (
                <div style={{ display: 'grid', gap: '8px' }}>
                  {tasks.map(t => {
                    const taskLabel = TASK_TYPE_LABELS[t.task_type] ?? t.task_type;
                    const taskDisplayName = t.name || taskLabel;
                    return (
                      <div
                        key={t.id}
                        onClick={() => navigate(`/tasks/${t.id}/status`)}
                        style={{
                          backgroundColor: '#fff',
                          border: '1px solid #e2e8f0',
                          borderRadius: 10,
                          padding: '14px 18px',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                          gap: '12px',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)')}
                        onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500, marginBottom: 3 }}>
                            Без проекта · {taskLabel}
                          </div>
                          <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
                            {taskDisplayName}
                          </div>
                          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
                            {formatDate(t.created_at)}
                          </div>
                          {t.owner_name && (
                            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
                              Ответственный: <span style={{ color: '#475569', fontWeight: 500 }}>{t.owner_name}</span>
                            </div>
                          )}
                        </div>

                        <button
                          onClick={e => { e.stopPropagation(); handleRestoreTask(t); }}
                          disabled={busyId === t.id}
                          style={{
                            flexShrink: 0,
                            padding: '5px 14px',
                            background: 'transparent',
                            border: '1px solid #cbd5e1',
                            borderRadius: '6px',
                            fontSize: '12px',
                            color: '#475569',
                            cursor: busyId === t.id ? 'not-allowed' : 'pointer',
                            fontWeight: 500,
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = '#f1f5f9'; }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                        >
                          {busyId === t.id ? 'Возврат…' : 'Вернуть из архива'}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </Layout>
  );
};

export default Archive;
