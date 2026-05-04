import React from 'react';
import { ApiCosts } from '../../api/dashboard';

interface Props {
  costs: ApiCosts;
}

const TASK_TYPE_LABELS: Record<string, string> = {
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
  LIST_FROM_PROJECT: 'Перечень из проекта',
  CHECK_LIST_COMPLETENESS: 'Проверка полноты (Гранд)',
  CHECK_PROJECT_COMPLETENESS: 'Проверка полноты (проект)',
  ESTIMATE_FROM_LIST: 'Смета из перечня',
  ESTIMATE_OPTIMIZATION: 'Оптимизация сметы',
};

function formatUsd(value: number): string {
  return `$${value.toFixed(4)}`;
}

function getRemainingDaysInMonth(): number {
  const now = new Date();
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return lastDay - now.getDate();
}

function getCacheColor(rate: number): string {
  if (rate >= 50) return '#16a34a';
  if (rate >= 20) return '#d97706';
  return '#dc2626';
}

function getCacheBg(rate: number): string {
  if (rate >= 50) return '#f0fdf4';
  if (rate >= 20) return '#fffbeb';
  return '#fef2f2';
}

interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
}

const KpiCard: React.FC<KpiCardProps> = ({ label, value, sub }) => (
  <div
    style={{
      flex: 1,
      minWidth: 0,
      backgroundColor: '#f8fafc',
      border: '1px solid #e2e8f0',
      borderRadius: 12,
      padding: '20px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    }}
  >
    <span style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>{label}</span>
    <span style={{ fontSize: 26, fontWeight: 700, color: '#1e293b', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
      {value}
    </span>
    {sub && <span style={{ fontSize: 12, color: '#94a3b8' }}>{sub}</span>}
  </div>
);

const DashboardCosts: React.FC<Props> = ({ costs }) => {
  const { today_usd, week_usd, month_usd, cache_hit_rate, by_task_type } = costs;

  const dailyRate = week_usd / 7;
  const remainingDays = getRemainingDaysInMonth();
  const forecastAdditional = dailyRate * remainingDays;

  const cacheColor = getCacheColor(cache_hit_rate);
  const cacheBg = getCacheBg(cache_hit_rate);

  const sortedBreakdown = [...by_task_type].sort((a, b) => b.cost_usd - a.cost_usd);

  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: '0 0 16px' }}>
        Стоимость Claude API
      </h2>

      {/* KPI-карточки */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <KpiCard label="Сегодня" value={formatUsd(today_usd)} />
        <KpiCard label="За неделю" value={formatUsd(week_usd)} sub={`≈ ${formatUsd(dailyRate)}/день`} />
        <KpiCard label="За месяц (30 дней)" value={formatUsd(month_usd)} />
        <div
          style={{
            flex: 1,
            minWidth: 0,
            backgroundColor: cacheBg,
            border: '1px solid #e2e8f0',
            borderRadius: 12,
            padding: '20px 24px',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          <span style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>Cache hit rate</span>
          <span
            style={{
              fontSize: 26,
              fontWeight: 700,
              color: cacheColor,
              lineHeight: 1,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {cache_hit_rate.toFixed(1)}%
          </span>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            {cache_hit_rate >= 50 ? 'Хорошо' : cache_hit_rate >= 20 ? 'Среднее' : 'Низкое'}
          </span>
        </div>
      </div>

      {/* Прогноз */}
      <div
        style={{
          padding: '12px 16px',
          backgroundColor: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          marginBottom: 16,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span style={{ fontSize: 13, color: '#64748b' }}>Прогноз до конца месяца</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1e293b' }}>
          +{formatUsd(forecastAdditional)}
        </span>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>
          (осталось {remainingDays} дн. × {formatUsd(dailyRate)}/день)
        </span>
      </div>

      {/* Breakdown по типам задач */}
      {sortedBreakdown.length > 0 && (
        <div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr auto auto',
              gap: '6px 16px',
              alignItems: 'center',
              paddingBottom: 8,
              marginBottom: 4,
              borderBottom: '1px solid #f1f5f9',
            }}
          >
            <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500 }}>Тип задачи</span>
            <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500, textAlign: 'right' }}>Вызовов</span>
            <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500, textAlign: 'right' }}>Стоимость</span>
          </div>
          {sortedBreakdown.map((row, idx) => {
            const label = row.task_type ? (TASK_TYPE_LABELS[row.task_type] ?? row.task_type) : 'Служебные';
            return (
              <div
                key={idx}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto auto',
                  gap: '4px 16px',
                  alignItems: 'center',
                  padding: '6px 0',
                  borderBottom: idx < sortedBreakdown.length - 1 ? '1px solid #f8fafc' : 'none',
                }}
              >
                <span style={{ fontSize: 13, color: '#374151' }}>{label}</span>
                <span style={{ fontSize: 13, color: '#64748b', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {row.calls_count}
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: '#1e293b',
                    textAlign: 'right',
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {formatUsd(row.cost_usd)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {sortedBreakdown.length === 0 && (
        <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>Данных о вызовах API пока нет.</p>
      )}
    </div>
  );
};

export default DashboardCosts;
