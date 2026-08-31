import React, { useCallback } from 'react';
import Layout from '../components/Layout';
import { useAuthStore } from '../stores/auth';
import { useDashboardStats } from '../hooks/useDashboardStats';
import DashboardPulse from '../components/dashboard/DashboardPulse';
import DashboardQueue from '../components/dashboard/DashboardQueue';
import DashboardErrors from '../components/dashboard/DashboardErrors';
import DashboardFunnel from '../components/dashboard/DashboardFunnel';
import DashboardProjects from '../components/dashboard/DashboardProjects';
import DashboardChart from '../components/dashboard/DashboardChart';
import DashboardPriceLists from '../components/dashboard/DashboardPriceLists';
import DashboardCosts from '../components/dashboard/DashboardCosts';
import DashboardBalance from '../components/dashboard/DashboardBalance';

const System: React.FC = () => {
  // Дашборд-агрегаты доступны только менеджеру (бэкенд отдаёт 403 остальным),
  // поэтому запрос статистики включаем лишь для него.
  const isManager = useAuthStore(s => s.isManager);
  const { data, loading, error, refetch } = useDashboardStats(isManager);

  const refreshAll = useCallback(() => { refetch(); }, [refetch]);

  return (
    <Layout>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: '#1e293b', margin: 0 }}>Система</h1>
            <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
              Ошибки, очередь и сводка по сервису · обновление каждые 30 сек
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

        {/* Все блоки раздела — менеджерские: без роли показывать нечего */}
        {!isManager && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
            Раздел доступен руководителю отдела
          </div>
        )}

        {isManager && loading && !data && (
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

        {isManager && data && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
            {/* Упавшие — журнал ошибок по всем задачам */}
            <Section>
              <DashboardErrors groups={data.errors} onResume={refreshAll} />
            </Section>

            {/* Идёт — активная очередь */}
            <Section>
              <DashboardQueue tasks={data.active_queue} onCancel={refreshAll} />
            </Section>

            {/* ─── Сводка и аналитика ─── */}
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

            {/* Остаток — над расходами: «сколько осталось» важнее, чем «сколько потрачено» */}
            <Section>
              <DashboardBalance onChanged={refreshAll} />
            </Section>

            <Section>
              <DashboardCosts costs={data.api_costs} />
            </Section>
          </div>
        )}
      </div>
    </Layout>
  );
};

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
