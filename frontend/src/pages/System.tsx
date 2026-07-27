import React, { useCallback, useEffect, useState } from 'react';
import { Archive, RotateCcw } from 'lucide-react';
import Layout from '../components/Layout';
import { useAuthStore } from '../stores/auth';
import { getUnassignedTasks, archiveTask } from '../api/projects';
import { TaskBrief, TASK_TYPE_LABELS } from '../types';
import { useDashboardStats } from '../hooks/useDashboardStats';
import DashboardPulse from '../components/dashboard/DashboardPulse';
import DashboardQueue from '../components/dashboard/DashboardQueue';
import DashboardErrors from '../components/dashboard/DashboardErrors';
import DashboardFunnel from '../components/dashboard/DashboardFunnel';
import DashboardProjects from '../components/dashboard/DashboardProjects';
import DashboardChart from '../components/dashboard/DashboardChart';
import DashboardPriceLists from '../components/dashboard/DashboardPriceLists';
import DashboardCosts from '../components/dashboard/DashboardCosts';
import {
  useUnassignedInbox,
  UnassignedGroup,
  UnassignedModals,
} from '../components/inbox/UnassignedInbox';

const System: React.FC = () => {
  // Дашборд-агрегаты доступны только менеджеру (бэкенд отдаёт 403 остальным),
  // поэтому запрос статистики включаем лишь для него. «Входящий» — для всех.
  const isManager = useAuthStore(s => s.isManager);
  const { data, loading, error, refetch } = useDashboardStats(isManager);
  const [reloadToken, setReloadToken] = useState(0);
  const inbox = useUnassignedInbox(reloadToken);
  // Раздел «Входящего»: активные задачи или архив задач «Без проекта».
  const [section, setSection] = useState<'active' | 'archive'>('active');

  // Обновление одной кнопкой: и дашборд-агрегаты, и ничейные задачи.
  const refreshAll = useCallback(() => {
    refetch();
    setReloadToken(t => t + 1);
  }, [refetch]);

  return (
    <Layout>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: '#1e293b', margin: 0 }}>Входящий</h1>
            <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
              Что требует внимания: готовые к проверке, упавшие, ждущие решения · обновление каждые 30 сек
            </p>
          </div>
          <button
            onClick={refreshAll}
            style={{
              fontSize: 13,
              padding: '6px 14px',
              border: '1px solid #e2e8f0',
              borderRadius: 7,
              backgroundColor: '#f8fafc',
              color: '#64748b',
              cursor: 'pointer',
            }}
          >
            Обновить
          </button>
        </div>

        {/* Переключатель разделов «Входящего»: активные задачи / архив «Без проекта» */}
        <div style={{ display: 'inline-flex', gap: 4, marginBottom: 20, backgroundColor: '#f1f5f9', borderRadius: 9, padding: 3 }}>
          {([['active', 'Активные'], ['archive', 'Архив']] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setSection(key)}
              style={{
                fontSize: 13,
                fontWeight: 600,
                padding: '6px 16px',
                border: 'none',
                borderRadius: 7,
                cursor: 'pointer',
                backgroundColor: section === key ? '#ffffff' : 'transparent',
                color: section === key ? '#1e293b' : '#64748b',
                boxShadow: section === key ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {section === 'archive' && <ArchivedLooseTasks reloadToken={reloadToken} onChange={refreshAll} />}

        {section === 'active' && (
          <>
        {/* Стартовая загрузка: для менеджера ждём агрегаты, для остальных — «Входящий» */}
        {(isManager ? loading && !data : inbox.loading) &&
          !inbox.ready.length && !inbox.gate.length && !inbox.other.length && (
            <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
              Загрузка...
            </div>
          )}

        {isManager && error && (
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: 8,
              color: '#dc2626',
              fontSize: 14,
              marginBottom: 20,
            }}
          >
            {error}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {/* ─── Входящий: смысловые группы «что требует меня» (для всех ролей) ─── */}

          {/* Готовые к проверке — джоб завершён, ждёт человека */}
          {inbox.ready.length > 0 && (
            <Section>
              <GroupHeader
                title="Готовые к проверке"
                count={inbox.ready.length}
                accent="#16a34a"
                hint="Смета рассчитана — проверьте, скачайте или оптимизируйте"
              />
              <UnassignedGroup tasks={inbox.ready} inbox={inbox} />
            </Section>
          )}

          {/* Упавшие — resume/retry (журнал ошибок по всем задачам, только менеджер) */}
          {isManager && data && (
            <Section>
              <DashboardErrors groups={data.errors} onResume={refreshAll} />
            </Section>
          )}

          {/* Ждут решения на гейте — перечень готов, смета не запущена.
              Основано на доступных данных: ничейные перечни без сметы. */}
          {inbox.gate.length > 0 && (
            <Section>
              <GroupHeader
                title="Ждут решения на гейте"
                count={inbox.gate.length}
                accent="#d97706"
                hint="Перечень готов — решите: рассчитать смету? (по доступным данным)"
              />
              <UnassignedGroup tasks={inbox.gate} inbox={inbox} />
            </Section>
          )}

          {/* Идёт — активная очередь (только менеджер) */}
          {isManager && data && (
            <Section>
              <DashboardQueue tasks={data.active_queue} onCancel={refreshAll} />
            </Section>
          )}

          {/* Прочие ничейные задачи — чтобы не потерять доступ */}
          {inbox.other.length > 0 && (
            <Section>
              <GroupHeader
                title="Без проекта"
                count={inbox.other.length}
                accent="#64748b"
                hint="Задачи, не привязанные ни к одному проекту"
              />
              <UnassignedGroup tasks={inbox.other} inbox={inbox} />
            </Section>
          )}

          {/* ─── Сводка и аналитика (только менеджер) ─── */}
          {isManager && data && (
            <>
              <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 4, marginTop: 4 }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: '#334155', margin: '0 0 4px' }}>
                  Сводка и аналитика
                </h2>
                <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>
                  Оперативная картина работы сервиса
                </p>
              </div>

              <Section>
                <DashboardPulse pulse={data.pulse} />
              </Section>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                <Section>
                  <DashboardFunnel funnel={data.quality_funnel} />
                </Section>
                <Section>
                  <DashboardChart data={data.task_chart} />
                </Section>
              </div>

              <Section>
                <DashboardProjects projects={data.projects} orphanCount={data.orphan_tasks_count} />
              </Section>

              <Section>
                <DashboardPriceLists priceLists={data.price_lists} />
              </Section>

              <Section>
                <DashboardCosts costs={data.api_costs} />
              </Section>
            </>
          )}
        </div>
          </>
        )}
      </div>

      <UnassignedModals inbox={inbox} />
    </Layout>
  );
};

// Скрытые служебные типы — как в useUnassignedInbox, чтобы список архива совпадал.
const HIDDEN_TASK_TYPES = new Set(['CHECK_LIST_COMPLETENESS', 'CHECK_PROJECT_COMPLETENESS']);

// ─── Архив задач «Без проекта»: простой список карточек с возвратом из архива ───
const ArchivedLooseTasks: React.FC<{ reloadToken: number; onChange: () => void }> = ({
  reloadToken, onChange,
}) => {
  const [tasks, setTasks] = useState<TaskBrief[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getUnassignedTasks(true);
      setTasks(data.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)));
    } catch {
      /* при ошибке оставляем прежний список */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, reloadToken]);

  const restore = useCallback(async (taskId: string) => {
    await archiveTask(taskId, false);
    setTasks(prev => prev.filter(t => t.id !== taskId));
    onChange();
  }, [onChange]);

  if (loading && tasks.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
        Загрузка...
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
        В архиве нет задач «Без проекта»
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {tasks.map(task => {
        const taskLabel = TASK_TYPE_LABELS[task.task_type] ?? task.task_type;
        return (
          <div
            key={task.id}
            style={{
              backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 10,
              padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500, marginBottom: 3, display: 'flex', alignItems: 'center', gap: 4 }}>
                <Archive size={12} /> В архиве · {taskLabel}
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
                {task.name || taskLabel}
              </div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
                {new Date(task.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </div>
              {task.owner_name && (
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
                  Ответственный: <span style={{ color: '#475569', fontWeight: 500 }}>{task.owner_name}</span>
                </div>
              )}
            </div>
            <button
              onClick={() => restore(task.id)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0, marginLeft: 12,
                padding: '4px 12px', backgroundColor: '#f8fafc', color: '#475569',
                border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600,
              }}
            >
              <RotateCcw size={13} /> Вернуть из архива
            </button>
          </div>
        );
      })}
    </div>
  );
};

const GroupHeader: React.FC<{ title: string; count: number; accent: string; hint?: string }> = ({
  title, count, accent, hint,
}) => (
  <div style={{ marginBottom: 12 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: accent, display: 'inline-block' }} />
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: 0 }}>{title}</h2>
      <span
        style={{
          fontSize: 12,
          fontWeight: 500,
          color: '#64748b',
          backgroundColor: '#f1f5f9',
          borderRadius: 20,
          padding: '2px 8px',
        }}
      >
        {count}
      </span>
    </div>
    {hint && <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0 16px' }}>{hint}</p>}
  </div>
);

const Section: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      backgroundColor: '#ffffff',
      border: '1px solid #e2e8f0',
      borderRadius: 12,
      padding: '20px 24px',
    }}
  >
    {children}
  </div>
);

export default System;
