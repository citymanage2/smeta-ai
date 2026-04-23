import React, { useState, useEffect } from 'react';
import { Expenses } from '../../api/estimateVersions';

interface AdditionalExpensesProps {
  overhead_pct: number;
  transport_pct: number;
  contingency_pct: number;
  baseTotal: number;
  onSave: (expenses: Expenses) => Promise<void>;
}

const AdditionalExpenses: React.FC<AdditionalExpensesProps> = ({
  overhead_pct,
  transport_pct,
  contingency_pct,
  baseTotal,
  onSave,
}) => {
  const [overhead, setOverhead] = useState(String(overhead_pct));
  const [transport, setTransport] = useState(String(transport_pct));
  const [contingency, setContingency] = useState(String(contingency_pct));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setOverhead(String(overhead_pct));
    setTransport(String(transport_pct));
    setContingency(String(contingency_pct));
  }, [overhead_pct, transport_pct, contingency_pct]);

  const overheadVal = parseFloat(overhead) || 0;
  const transportVal = parseFloat(transport) || 0;
  const contingencyVal = parseFloat(contingency) || 0;

  const overheadRub = Math.round((baseTotal * overheadVal) / 100);
  const transportRub = Math.round((baseTotal * transportVal) / 100);
  const contingencyRub = Math.round((baseTotal * contingencyVal) / 100);

  const fmt = (n: number) => n.toLocaleString('ru-RU');

  const isDirty =
    parseFloat(overhead) !== overhead_pct ||
    parseFloat(transport) !== transport_pct ||
    parseFloat(contingency) !== contingency_pct;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        overhead_pct: overheadVal,
        transport_pct: transportVal,
        contingency_pct: contingencyVal,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        border: '1px solid #e2e8f0',
        borderRadius: '8px',
        padding: '16px 20px',
        background: '#fff',
        marginTop: '12px',
      }}
    >
      <div
        style={{
          fontSize: '13px',
          fontWeight: 600,
          color: '#475569',
          marginBottom: '12px',
          textTransform: 'uppercase',
          letterSpacing: '0.4px',
        }}
      >
        Дополнительные расходы
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <ExpenseRow
          label="Накладные расходы"
          value={overhead}
          rub={overheadRub}
          onChange={setOverhead}
          fmt={fmt}
        />
        <ExpenseRow
          label="Транспортные расходы"
          value={transport}
          rub={transportRub}
          onChange={setTransport}
          fmt={fmt}
        />
        <ExpenseRow
          label="Непредвиденные расходы"
          value={contingency}
          rub={contingencyRub}
          onChange={setContingency}
          fmt={fmt}
        />
      </div>

      <div style={{ marginTop: '14px' }}>
        <button
          onClick={handleSave}
          disabled={!isDirty || saving}
          style={{
            padding: '7px 18px',
            fontSize: '13px',
            fontWeight: 600,
            borderRadius: '6px',
            border: 'none',
            cursor: isDirty && !saving ? 'pointer' : 'default',
            background: isDirty && !saving ? '#2563eb' : '#e2e8f0',
            color: isDirty && !saving ? '#fff' : '#94a3b8',
            transition: 'background 0.15s',
          }}
        >
          {saving ? 'Сохранение...' : 'Сохранить'}
        </button>
      </div>
    </div>
  );
};

interface ExpenseRowProps {
  label: string;
  value: string;
  rub: number;
  onChange: (v: string) => void;
  fmt: (n: number) => string;
}

const ExpenseRow: React.FC<ExpenseRowProps> = ({ label, value, rub, onChange, fmt }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
    <span style={{ fontSize: '13px', color: '#374151', width: 210, flexShrink: 0 }}>{label}</span>
    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
      <input
        type="number"
        min="0"
        max="100"
        step="0.1"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '70px',
          padding: '5px 8px',
          fontSize: '13px',
          border: '1px solid #d1d5db',
          borderRadius: '5px',
          textAlign: 'right',
          outline: 'none',
          fontFamily: 'inherit',
        }}
      />
      <span style={{ fontSize: '13px', color: '#6b7280' }}>%</span>
    </div>
    <span style={{ fontSize: '13px', color: '#374151', marginLeft: 4 }}>
      = {rub > 0 ? fmt(rub) : '0'} руб
    </span>
  </div>
);

export default AdditionalExpenses;
