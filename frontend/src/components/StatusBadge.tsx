import React, { useState } from 'react';
import { updateEstimateStatus } from '../api/projects';

type EstimateStatus = 'uploaded' | 'calculated' | 'optimized';

interface Props {
  taskId: string;
  status: EstimateStatus;
  updatedBy: 'manual' | 'auto';
  onChange?: (newStatus: EstimateStatus) => void;
  readonly?: boolean;
}

const STATUS_CONFIG: Record<EstimateStatus, { label: string; bg: string; text: string }> = {
  uploaded:   { label: 'Загружена',         bg: '#e5e7eb', text: '#374151' },
  calculated: { label: 'Расчёт выполнен',   bg: '#fef3c7', text: '#92400e' },
  optimized:  { label: 'Оптимизирована',    bg: '#d1fae5', text: '#065f46' },
};

const STATUSES: EstimateStatus[] = ['uploaded', 'calculated', 'optimized'];

const StatusBadge: React.FC<Props> = ({ taskId, status, updatedBy, onChange, readonly }) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.uploaded;

  const handleSelect = async (s: EstimateStatus) => {
    if (s === status) { setOpen(false); return; }
    setLoading(true);
    try {
      await updateEstimateStatus(taskId, s, 'manual');
      onChange?.(s);
    } finally {
      setLoading(false);
      setOpen(false);
    }
  };

  const icon = updatedBy === 'auto' ? '⚡' : '✏️';

  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 10px',
          borderRadius: 12,
          fontSize: 12,
          fontWeight: 600,
          background: cfg.bg,
          color: cfg.text,
          cursor: readonly ? 'default' : 'pointer',
          userSelect: 'none',
          whiteSpace: 'nowrap',
        }}
        title={`Изменено: ${updatedBy === 'auto' ? 'автоматически' : 'вручную'}`}
        onClick={() => !readonly && !loading && setOpen(v => !v)}
      >
        <span style={{ fontSize: 11 }}>{icon}</span>
        {cfg.label}
        {!readonly && <span style={{ fontSize: 10, opacity: 0.7 }}>▾</span>}
      </span>

      {open && (
        <span
          style={{
            position: 'absolute',
            top: '110%',
            left: 0,
            zIndex: 50,
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            minWidth: 180,
            overflow: 'hidden',
          }}
        >
          {STATUSES.map(s => {
            const c = STATUS_CONFIG[s];
            return (
              <span
                key={s}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 14px',
                  cursor: 'pointer',
                  fontSize: 13,
                  background: s === status ? '#f3f4f6' : '#fff',
                  color: '#111827',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = '#f9fafb')}
                onMouseLeave={e => (e.currentTarget.style.background = s === status ? '#f3f4f6' : '#fff')}
                onClick={() => handleSelect(s)}
              >
                <span
                  style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: c.bg, border: `2px solid ${c.text}`, flexShrink: 0,
                  }}
                />
                {c.label}
              </span>
            );
          })}
        </span>
      )}
    </span>
  );
};

export default StatusBadge;
