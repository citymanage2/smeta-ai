import React from 'react';
import Layout from '../components/Layout';
import { useDashboardStats } from '../hooks/useDashboardStats';
import DashboardPulse from '../components/dashboard/DashboardPulse';
import DashboardQueue from '../components/dashboard/DashboardQueue';
import DashboardErrors from '../components/dashboard/DashboardErrors';
import DashboardFunnel from '../components/dashboard/DashboardFunnel';
import DashboardProjects from '../components/dashboard/DashboardProjects';
import DashboardChart from '../components/dashboard/DashboardChart';
import DashboardPriceLists from '../components/dashboard/DashboardPriceLists';
import DashboardCosts from '../components/dashboard/DashboardCosts';

const System: React.FC = () => {
  const { data, loading, error, refetch } = useDashboardStats();

  return (
    <Layout>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: '#1e293b', margin: 0 }}>Система</h1>
            <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
              Оперативная картина работы сервиса · обновление каждые 30 сек
            </p>
          </div>
          <button
            onClick={refetch}
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

        {loading && !data && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8', fontSize: 14 }}>
            Загрузка...
          </div>
        )}

        {error && (
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

        {data && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
            {/* Блок 1 — Пульс */}
            <Section>
              <DashboardPulse pulse={data.pulse} />
            </Section>

            {/* Блок 2 — Активная очередь */}
            <Section>
              <DashboardQueue tasks={data.active_queue} onCancel={refetch} />
            </Section>

            {/* Блок 3 — Журнал ошибок */}
            <Section>
              <DashboardErrors groups={data.errors} onResume={refetch} />
            </Section>

            {/* Блок 4 + Блок 6 — Воронка + График в ряд */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
              <Section>
                <DashboardFunnel funnel={data.quality_funnel} />
              </Section>
              <Section>
                <DashboardChart data={data.task_chart} />
              </Section>
            </div>

            {/* Блок 5 — Проекты */}
            <Section>
              <DashboardProjects projects={data.projects} orphanCount={data.orphan_tasks_count} />
            </Section>

            {/* Блок 7 — Прайс-листы */}
            <Section>
              <DashboardPriceLists priceLists={data.price_lists} />
            </Section>

            {/* Блок 8 — Стоимость Claude API */}
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
