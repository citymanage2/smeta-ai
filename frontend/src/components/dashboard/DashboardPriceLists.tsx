import React from 'react';
import { useNavigate } from 'react-router-dom';
import { PriceListInfo } from '../../api/dashboard';

interface Props {
  priceLists: PriceListInfo[];
}

const LABELS: Record<string, string> = {
  works: 'Работы',
  materials: 'Материалы',
};

function formatDate(iso: string | null): string {
  if (!iso) return 'Не загружен';
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function daysAgo(iso: string | null): number {
  if (!iso) return Infinity;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

const DashboardPriceLists: React.FC<Props> = ({ priceLists }) => {
  const navigate = useNavigate();
  const sorted = [...priceLists].sort((a, b) => (a.type < b.type ? -1 : 1));

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: 0 }}>Прайс-листы</h2>
        <button
          onClick={() => navigate('/admin')}
          style={{
            fontSize: 12,
            padding: '3px 10px',
            border: '1px solid #e2e8f0',
            borderRadius: 6,
            backgroundColor: '#f8fafc',
            color: '#64748b',
            cursor: 'pointer',
          }}
        >
          Перейти в настройки →
        </button>
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        {sorted.map((pl) => (
          <PriceCard key={pl.type} pl={pl} />
        ))}
      </div>
    </div>
  );
};

const PriceCard: React.FC<{ pl: PriceListInfo }> = ({ pl }) => {
  const days = daysAgo(pl.updated_at);
  const isFailed = pl.embedding_status === 'failed';
  const isStale = days > 30;

  let borderColor = '#e2e8f0';
  let headerBg = '#f8fafc';
  let alertMsg: string | null = null;

  if (isFailed) {
    borderColor = '#fca5a5';
    headerBg = '#fef2f2';
    alertMsg = 'Ошибка создания эмбеддингов';
  } else if (isStale) {
    borderColor = '#fde68a';
    headerBg = '#fffbeb';
    alertMsg = `Не обновлялся ${days} дней`;
  }

  return (
    <div
      style={{
        flex: 1,
        border: `1px solid ${borderColor}`,
        borderRadius: 10,
        overflow: 'hidden',
      }}
    >
      <div style={{ backgroundColor: headerBg, padding: '10px 14px', borderBottom: `1px solid ${borderColor}` }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: '#1e293b' }}>
          {LABELS[pl.type] ?? pl.type}
        </div>
        {alertMsg && (
          <div style={{ fontSize: 11, color: isFailed ? '#dc2626' : '#d97706', marginTop: 2 }}>
            ⚠ {alertMsg}
          </div>
        )}
      </div>
      <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Row label="Обновлён" value={formatDate(pl.updated_at)} />
        <Row label="Позиций" value={pl.items_count.toLocaleString('ru-RU')} />
        <Row label="Эмбеддинги" value={embeddingLabel(pl.embedding_status)} />
      </div>
    </div>
  );
};

function embeddingLabel(status: string | null): string {
  if (!status) return 'Не создавались';
  const map: Record<string, string> = {
    done: 'Готовы',
    processing: 'Создаются...',
    failed: 'Ошибка',
    pending: 'Ожидают',
  };
  return map[status] ?? status;
}

const Row: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
    <span style={{ color: '#64748b' }}>{label}</span>
    <span style={{ color: '#1e293b', fontWeight: 500 }}>{value}</span>
  </div>
);

export default DashboardPriceLists;
