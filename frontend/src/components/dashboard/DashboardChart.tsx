import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { ChartDay } from '../../api/dashboard';

interface Props {
  data: ChartDay[];
}

const SERIES = [
  { key: 'LIST_FROM_GRAND', label: 'Перечень из Гранд', color: '#2563eb' },
  { key: 'LIST_FROM_PROJECT', label: 'Перечень из проекта', color: '#7c3aed' },
  { key: 'CHECK_COMPLETENESS', label: 'Проверка полноты', color: '#0891b2' },
  { key: 'ESTIMATE_FROM_LIST', label: 'Смета из перечня', color: '#16a34a' },
  { key: 'ESTIMATE_OPTIMIZATION', label: 'Оптимизация', color: '#d97706' },
] as const;

function formatDay(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
}

const DashboardChart: React.FC<Props> = ({ data }) => {
  const chartData = data.map((d) => ({ ...d, _label: formatDay(d.date) }));

  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>
        График задач за 10 дней
      </h2>
      {data.length === 0 ? (
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
          Нет данных
        </div>
      ) : (
        <div style={{ width: '100%', height: 240 }}>
          <ResponsiveContainer>
            <BarChart data={chartData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="_label" tick={{ fontSize: 11, fill: '#94a3b8' }} />
              <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} allowDecimals={false} />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
                labelStyle={{ fontWeight: 600, color: '#374151' }}
              />
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              />
              {SERIES.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} stackId="a" fill={s.color} radius={[0, 0, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};

export default DashboardChart;
