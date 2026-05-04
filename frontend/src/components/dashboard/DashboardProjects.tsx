import React from 'react';
import { useNavigate } from 'react-router-dom';
import { DashboardProjectCard } from '../../api/dashboard';

interface Props {
  projects: DashboardProjectCard[];
  orphanCount: number;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
}

function formatCost(cost: number | null): string {
  if (cost === null || cost === 0) return '—';
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(cost);
}

const DashboardProjects: React.FC<Props> = ({ projects, orphanCount }) => {
  const navigate = useNavigate();

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: 0 }}>
          Проекты
          <span
            style={{
              marginLeft: 8,
              fontSize: 12,
              fontWeight: 500,
              color: '#64748b',
              backgroundColor: '#f1f5f9',
              borderRadius: 20,
              padding: '2px 8px',
            }}
          >
            {projects.length}
          </span>
        </h2>
        {orphanCount > 0 && (
          <button
            onClick={() => navigate('/projects/unassigned')}
            style={{
              fontSize: 12,
              color: '#d97706',
              backgroundColor: '#fef3c7',
              border: '1px solid #fde68a',
              borderRadius: 6,
              padding: '3px 10px',
              cursor: 'pointer',
            }}
          >
            {orphanCount} задач без проекта →
          </button>
        )}
      </div>

      {projects.length === 0 ? (
        <div
          style={{
            padding: '24px',
            textAlign: 'center',
            color: '#94a3b8',
            fontSize: 14,
            backgroundColor: '#f8fafc',
            borderRadius: 8,
            border: '1px solid #e2e8f0',
          }}
        >
          Нет проектов
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 10,
          }}
        >
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} onClick={() => navigate(`/projects/${p.id}`)} />
          ))}
        </div>
      )}
    </div>
  );
};

const ProjectCard: React.FC<{ project: DashboardProjectCard; onClick: () => void }> = ({ project: p, onClick }) => {
  const bd = p.task_breakdown;
  const taskRows = [
    { label: 'Перечни из Гранд', count: bd.list_from_grand },
    { label: 'Перечни из проекта', count: bd.list_from_project },
    { label: 'Проверки полноты', count: bd.check_completeness },
    { label: 'Сметы из перечня', count: bd.estimate_from_list },
    { label: 'Оптимизации', count: bd.optimization },
  ].filter((r) => r.count > 0);

  return (
    <div
      onClick={onClick}
      style={{
        backgroundColor: '#fff',
        border: `1px solid ${p.has_errors ? '#fecaca' : p.has_active ? '#bfdbfe' : '#e2e8f0'}`,
        borderRadius: 10,
        padding: '14px 16px',
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)')}
      onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'none')}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: '#1e293b', flex: 1, marginRight: 8 }}>
          {p.name}
        </div>
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          {p.has_active && (
            <span
              title="Есть активные задачи"
              style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#3b82f6', display: 'inline-block', marginTop: 3 }}
            />
          )}
          {p.has_errors && (
            <span
              title="Есть задачи с ошибкой"
              style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#ef4444', display: 'inline-block', marginTop: 3 }}
            />
          )}
        </div>
      </div>

      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8, display: 'flex', gap: 12 }}>
        <span>Создан {formatDate(p.created_at)}</span>
        {p.last_task_at && <span>Задача {formatDate(p.last_task_at)}</span>}
      </div>

      {p.total_cost !== null && p.total_cost > 0 && (
        <div style={{ fontSize: 13, fontWeight: 600, color: '#16a34a', marginBottom: 8 }}>
          {formatCost(p.total_cost)}
        </div>
      )}

      {taskRows.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {taskRows.map((r) => (
            <span
              key={r.label}
              style={{
                fontSize: 11,
                padding: '2px 7px',
                borderRadius: 20,
                backgroundColor: '#f1f5f9',
                color: '#475569',
              }}
            >
              {r.label}: {r.count}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

export default DashboardProjects;
