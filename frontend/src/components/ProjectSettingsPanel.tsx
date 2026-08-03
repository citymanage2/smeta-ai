import React, { useState } from 'react';
import { Percent } from 'lucide-react';

import { updateProject } from '../api/projects';

/**
 * Настройки проекта: проценты накладных и транспортных расходов.
 *
 * Раньше 3% были зашиты в коде — в генераторе файла сметы и в двух местах
 * интерфейса. Теперь это одна настройка проекта: по ней считаются итоги всех
 * его документов, скачиваемые файлы и стоимость задач.
 */

interface Props {
  projectId: string;
  overheadPct: number;
  transportPct: number;
  onSaved: (overheadPct: number, transportPct: number) => void;
}

function parsePct(value: string): number | null {
  const normalized = value.trim().replace(',', '.');
  if (normalized === '') return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) return null;
  return parsed;
}

export const ProjectSettingsPanel: React.FC<Props> = ({
  projectId, overheadPct, transportPct, onSaved,
}) => {
  const [open, setOpen] = useState(false);
  const [overhead, setOverhead] = useState(String(overheadPct).replace('.', ','));
  const [transport, setTransport] = useState(String(transportPct).replace('.', ','));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleSave = async () => {
    const overheadValue = parsePct(overhead);
    const transportValue = parsePct(transport);
    if (overheadValue === null || transportValue === null) {
      setError('Процент — число от 0 до 100, например 3 или 7,5');
      return;
    }
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const updated = await updateProject(projectId, {
        overhead_pct: overheadValue,
        transport_pct: transportValue,
      });
      onSaved(updated.overhead_pct ?? overheadValue, updated.transport_pct ?? transportValue);
      setMessage('Ставки сохранены, сметы проекта пересчитаны');
    } catch {
      setError('Не удалось сохранить ставки');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: '12px' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '6px',
          background: 'none', border: '1px solid #e2e8f0', borderRadius: '8px',
          padding: '6px 12px', fontSize: '13px', color: '#475569', cursor: 'pointer',
        }}
      >
        <Percent size={14} />
        Настройки проекта: накладные {overheadPct}%, транспортные {transportPct}%
      </button>

      {open && (
        <div style={{
          marginTop: '10px', padding: '12px 14px', background: '#f8fafc',
          border: '1px solid #e2e8f0', borderRadius: '10px',
          display: 'flex', gap: '16px', alignItems: 'flex-end', flexWrap: 'wrap',
        }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px', color: '#475569' }}>
            Накладные расходы, %
            <input
              aria-label="Накладные расходы, %"
              value={overhead}
              onChange={(e) => setOverhead(e.target.value)}
              inputMode="decimal"
              style={{ width: 90, padding: '5px 8px', fontSize: '13px', border: '1px solid #d1d5db', borderRadius: '6px', textAlign: 'right' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px', color: '#475569' }}>
            Транспортные расходы, %
            <input
              aria-label="Транспортные расходы, %"
              value={transport}
              onChange={(e) => setTransport(e.target.value)}
              inputMode="decimal"
              style={{ width: 90, padding: '5px 8px', fontSize: '13px', border: '1px solid #d1d5db', borderRadius: '6px', textAlign: 'right' }}
            />
          </label>

          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              padding: '7px 16px', fontSize: '13px', fontWeight: 600, border: 'none',
              borderRadius: '8px', background: saving ? '#e2e8f0' : '#2563eb',
              color: saving ? '#94a3b8' : '#fff', cursor: saving ? 'default' : 'pointer',
            }}
          >
            {saving ? 'Сохранение…' : 'Сохранить'}
          </button>

          {error && <span style={{ fontSize: '12px', color: '#dc2626' }}>{error}</span>}
          {message && <span style={{ fontSize: '12px', color: '#16a34a' }}>{message}</span>}
          <span style={{ fontSize: '12px', color: '#94a3b8', flexBasis: '100%' }}>
            Ставки применяются ко всем документам проекта: к итогам на экране,
            к скачиваемым файлам и к стоимости смет.
          </span>
        </div>
      )}
    </div>
  );
};

export default ProjectSettingsPanel;
