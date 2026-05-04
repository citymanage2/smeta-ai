import React from 'react';
import { QualityFunnel } from '../../api/dashboard';

interface Props {
  funnel: QualityFunnel;
}

function rateColor(rate: number): string {
  if (rate < 20) return '#16a34a';
  if (rate < 40) return '#d97706';
  return '#dc2626';
}

function rateBg(rate: number): string {
  if (rate < 20) return '#f0fdf4';
  if (rate < 40) return '#fffbeb';
  return '#fef2f2';
}

const DashboardFunnel: React.FC<Props> = ({ funnel }) => {
  const steps = [
    { label: 'Создано задач', value: funnel.completed_count + funnel.estimated_count },
    { label: 'Завершено', value: funnel.completed_count },
    { label: 'Смета рассчитана', value: funnel.estimated_count },
    { label: 'Правили вручную', value: funnel.manually_edited_count },
  ];

  const maxVal = Math.max(...steps.map((s) => s.value), 1);
  const color = rateColor(funnel.human_edit_rate);
  const bg = rateBg(funnel.human_edit_rate);

  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>
        Воронка качества
        <span style={{ marginLeft: 8, fontSize: 12, color: '#94a3b8', fontWeight: 400 }}>последние 30 дней</span>
      </h2>

      <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
        <div style={{ flex: 1 }}>
          {steps.map((step, i) => {
            const pct = maxVal > 0 ? (step.value / maxVal) * 100 : 0;
            return (
              <div key={i} style={{ marginBottom: i < steps.length - 1 ? 10 : 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#64748b', marginBottom: 4 }}>
                  <span>{step.label}</span>
                  <span style={{ fontWeight: 600, color: '#1e293b' }}>{step.value}</span>
                </div>
                <div style={{ height: 10, backgroundColor: '#e2e8f0', borderRadius: 5, overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${pct}%`,
                      backgroundColor: i === steps.length - 1 ? '#f59e0b' : '#2563eb',
                      borderRadius: 5,
                      transition: 'width 0.4s ease',
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            width: 140,
            backgroundColor: bg,
            border: `1px solid ${color}33`,
            borderRadius: 12,
            padding: '16px 20px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500, marginBottom: 4, textAlign: 'center' }}>
            Human Edit Rate
          </span>
          <span style={{ fontSize: 36, fontWeight: 800, color, lineHeight: 1 }}>
            {funnel.human_edit_rate}%
          </span>
          <span style={{ fontSize: 11, color, marginTop: 6, fontWeight: 500 }}>
            {funnel.human_edit_rate < 20 ? 'Отлично' : funnel.human_edit_rate < 40 ? 'Норма' : 'Высокий'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default DashboardFunnel;
