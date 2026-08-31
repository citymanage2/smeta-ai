import React from 'react';
import { PulseBucket, PulseStats } from '../../api/dashboard';
import PulseTasksModal from './PulseTasksModal';

interface Props {
  pulse: PulseStats;
}

interface CardDef {
  bucket: PulseBucket;
  label: string;
  value: number;
  color?: string;
  bg?: string;
}

interface KpiCardProps extends CardDef {
  onOpen: () => void;
}

const KpiCard: React.FC<KpiCardProps> = ({ label, value, color = '#1e293b', bg = '#f8fafc', onOpen }) => (
  <button
    type="button"
    onClick={onOpen}
    title="Показать задачи"
    style={{
      flex: 1,
      minWidth: 0,
      backgroundColor: bg,
      border: '1px solid #e2e8f0',
      borderRadius: 12,
      padding: '20px 24px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'flex-start',
      gap: 6,
      cursor: 'pointer',
      font: 'inherit',
      textAlign: 'left',
    }}
  >
    <span style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>{label}</span>
    <span style={{ fontSize: 32, fontWeight: 700, color, lineHeight: 1 }}>{value}</span>
  </button>
);

const DashboardPulse: React.FC<Props> = ({ pulse }) => {
  const [open, setOpen] = React.useState<CardDef | null>(null);

  const cards: CardDef[] = [
    { bucket: 'created', label: 'Создано сегодня', value: pulse.created_today },
    { bucket: 'processing', label: 'В обработке', value: pulse.processing_now, color: '#2563eb', bg: '#eff6ff' },
    { bucket: 'pending', label: 'В ожидании', value: pulse.pending_now, color: '#b45309', bg: '#fffbeb' },
    { bucket: 'completed', label: 'Завершено сегодня', value: pulse.completed_today, color: '#16a34a', bg: '#f0fdf4' },
    {
      bucket: 'failed',
      label: 'С ошибкой сегодня',
      value: pulse.failed_today,
      // Красным — только когда есть о чём тревожиться: ноль ошибок не должен
      // выглядеть как проблема.
      color: pulse.failed_today > 0 ? '#dc2626' : '#1e293b',
      bg: pulse.failed_today > 0 ? '#fef2f2' : '#f8fafc',
    },
  ];

  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>Пульс сегодня</h2>
      <div style={{ display: 'flex', gap: 12 }}>
        {cards.map((card) => (
          <KpiCard key={card.bucket} {...card} onOpen={() => setOpen(card)} />
        ))}
      </div>
      {open && (
        <PulseTasksModal bucket={open.bucket} title={open.label} onClose={() => setOpen(null)} />
      )}
    </div>
  );
};

export default DashboardPulse;
