import React from 'react';
import { PulseStats } from '../../api/dashboard';

interface Props {
  pulse: PulseStats;
}

interface KpiCardProps {
  label: string;
  value: number;
  color?: string;
  bg?: string;
}

const KpiCard: React.FC<KpiCardProps> = ({ label, value, color = '#1e293b', bg = '#f8fafc' }) => (
  <div
    style={{
      flex: 1,
      minWidth: 0,
      backgroundColor: bg,
      border: '1px solid #e2e8f0',
      borderRadius: 12,
      padding: '20px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    }}
  >
    <span style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>{label}</span>
    <span style={{ fontSize: 32, fontWeight: 700, color, lineHeight: 1 }}>{value}</span>
  </div>
);

const DashboardPulse: React.FC<Props> = ({ pulse }) => (
  <div>
    <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>Пульс сегодня</h2>
    <div style={{ display: 'flex', gap: 12 }}>
      <KpiCard label="Создано сегодня" value={pulse.created_today} />
      <KpiCard label="В обработке" value={pulse.processing_now} color="#2563eb" bg="#eff6ff" />
      <KpiCard label="Завершено сегодня" value={pulse.completed_today} color="#16a34a" bg="#f0fdf4" />
      <KpiCard
        label="С ошибкой сегодня"
        value={pulse.failed_today}
        color={pulse.failed_today > 0 ? '#dc2626' : '#1e293b'}
        bg={pulse.failed_today > 0 ? '#fef2f2' : '#f8fafc'}
      />
    </div>
  </div>
);

export default DashboardPulse;
