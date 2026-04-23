import React, { useMemo } from 'react';
import { EstimateRow } from '../../types';

const VAT_RATE = 0.22;

interface EstimateSummaryProps {
  rows: EstimateRow[];
  overhead_pct: number;
  transport_pct: number;
  contingency_pct: number;
}

const EstimateSummary: React.FC<EstimateSummaryProps> = ({
  rows,
  overhead_pct,
  transport_pct,
  contingency_pct,
}) => {
  const {
    worksTotal,
    materialsTotal,
    basis,
    overheadRub,
    transportRub,
    contingencyRub,
    total,
    vat,
    totalWithVat,
  } = useMemo(() => {
    const worksTotal = rows
      .filter((r) => r.type === 'work')
      .reduce((acc, r) => acc + (r.qty ?? 0) * ((r.price_work ?? 0) + (r.price_material ?? 0)), 0);

    const materialsTotal = rows
      .filter((r) => r.type === 'material')
      .reduce((acc, r) => acc + (r.qty ?? 0) * ((r.price_work ?? 0) + (r.price_material ?? 0)), 0);

    const basis = worksTotal + materialsTotal;
    const overheadRub = (basis * overhead_pct) / 100;
    const transportRub = (basis * transport_pct) / 100;
    const contingencyRub = (basis * contingency_pct) / 100;
    const total = basis + overheadRub + transportRub + contingencyRub;
    const vat = total * VAT_RATE;
    const totalWithVat = total + vat;

    return {
      worksTotal,
      materialsTotal,
      basis,
      overheadRub,
      transportRub,
      contingencyRub,
      total,
      vat,
      totalWithVat,
    };
  }, [rows, overhead_pct, transport_pct, contingency_pct]);

  const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

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
        Итоги сметы
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '13px' }}>
        <SummaryRow label="Работы" value={`${fmt(worksTotal)} руб`} />
        <SummaryRow label="Материалы" value={`${fmt(materialsTotal)} руб`} />
        <Divider />
        <SummaryRow label="Итого (базис)" value={`${fmt(basis)} руб`} />
        {overhead_pct > 0 && (
          <SummaryRow
            label={`Накладные расходы (${overhead_pct}%)`}
            value={`${fmt(overheadRub)} руб`}
          />
        )}
        {transport_pct > 0 && (
          <SummaryRow
            label={`Транспортные расходы (${transport_pct}%)`}
            value={`${fmt(transportRub)} руб`}
          />
        )}
        {contingency_pct > 0 && (
          <SummaryRow
            label={`Непредвиденные расходы (${contingency_pct}%)`}
            value={`${fmt(contingencyRub)} руб`}
          />
        )}
        <Divider />
        <SummaryRow label="Итого" value={`${fmt(total)} руб`} bold />
        <SummaryRow
          label={`НДС ${(VAT_RATE * 100).toFixed(0)}%`}
          value={`${fmt(vat)} руб`}
        />
        <Divider thick />
        <SummaryRow
          label="ИТОГО с НДС"
          value={`${fmt(totalWithVat)} руб`}
          bold
          large
        />
      </div>
    </div>
  );
};

interface SummaryRowProps {
  label: string;
  value: string;
  bold?: boolean;
  large?: boolean;
}

const SummaryRow: React.FC<SummaryRowProps> = ({ label, value, bold, large }) => (
  <div
    style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      gap: '16px',
      fontWeight: bold ? 700 : 400,
      fontSize: large ? '15px' : '13px',
      color: large ? '#1e293b' : '#374151',
    }}
  >
    <span style={{ color: '#6b7280', fontWeight: bold ? 600 : 400 }}>{label}:</span>
    <span>{value}</span>
  </div>
);

const Divider: React.FC<{ thick?: boolean }> = ({ thick }) => (
  <div
    style={{
      borderTop: thick ? '2px solid #334155' : '1px solid #e2e8f0',
      margin: '4px 0',
    }}
  />
);

export default EstimateSummary;
