import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../components/Layout';
import { getCorrections, getCorrectionsStats } from '../api/corrections';
import { Correction, CorrectionsStats } from '../types/corrections';

// План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 3.
//
// Экран показывает, где система врёт: что человек правит после неё чаще всего.
// Ничего не применяет — применение выученного идёт отдельным шагом и только с
// подтверждения человека (решение пользователя 07.08.2026).

const KIND_LABELS: Record<string, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
  'summary-section': 'Раздел сводной',
};

// Машинные ключи строк сметы человеку ничего не говорят. У перечня и полноты
// поле — это заголовок колонки исходного файла, его показываем как есть.
const FIELD_LABELS: Record<string, string> = {
  __row: 'Строка целиком',
  name: 'Наименование',
  unit: 'Единица',
  qty: 'Объём',
  price_work: 'Цена работ',
  price_material: 'Цена материалов',
  notes: 'Примечание',
  num: 'Номер',
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] || kind;
}

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field;
}

function formatDate(iso: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/** «система посчитала 3000 — вы поставили 2500» одной строкой. */
function verdict(item: Correction): string {
  if (item.new_value === 'добавлена') return 'система пропустила позицию — её добавили';
  if (item.new_value === 'удалена') return 'система добавила лишнюю позицию — её убрали';
  const before = item.previous_value ?? '—';
  const after = item.new_value ?? '—';
  return `система посчитала ${before} — поставили ${after}`;
}

const cardStyle: React.CSSProperties = {
  backgroundColor: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: '8px',
  padding: '20px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#94a3b8',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  marginBottom: '4px',
};

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 12px',
  fontSize: '11px',
  fontWeight: 700,
  color: '#94a3b8',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  borderBottom: '1px solid #e2e8f0',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  fontSize: '13px',
  color: '#1e293b',
  borderBottom: '1px solid #f1f5f9',
  verticalAlign: 'top',
};

const Metric: React.FC<{ label: string; value: number; color?: string; hint?: string }> = ({
  label, value, color = '#0f172a', hint,
}) => (
  <div>
    <div style={labelStyle}>{label}</div>
    <div style={{ fontSize: '24px', fontWeight: 700, color }}>{value}</div>
    {hint && <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>{hint}</div>}
  </div>
);

const CorrectionsPage: React.FC = () => {
  const [stats, setStats] = useState<CorrectionsStats | null>(null);
  const [items, setItems] = useState<Correction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [firstTouchOnly, setFirstTouchOnly] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [statsData, feed] = await Promise.all([
        getCorrectionsStats(),
        getCorrections({ limit: 100, firstTouchOnly }),
      ]);
      setStats(statsData);
      setItems(feed);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Не удалось загрузить журнал правок');
    } finally {
      setLoading(false);
    }
  }, [firstTouchOnly]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Layout>
      <div style={{ maxWidth: '1000px' }}>
        <div style={{ marginBottom: '24px' }}>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
            Правки после расчёта
          </h1>
          <p style={{ fontSize: '13px', color: '#64748b', margin: '6px 0 0' }}>
            Что люди исправляют за системой. Ничего из этого пока не применяется
            автоматически — журнал копится, чтобы было видно, где система ошибается.
          </p>
        </div>

        {error && (
          <div style={{
            ...cardStyle, backgroundColor: '#fef2f2', borderColor: '#fecaca',
            color: '#dc2626', fontSize: '13px', marginBottom: '16px',
          }}>
            {error}
          </div>
        )}

        <div style={{ ...cardStyle, marginBottom: '16px' }}>
          {loading && !stats ? (
            <div style={{ color: '#94a3b8', fontSize: '14px' }}>Загрузка…</div>
          ) : stats ? (
            <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
              <Metric label="Всего правок" value={stats.total} />
              <Metric
                label="Ошибок системы"
                value={stats.first_touch}
                color="#dc2626"
                hint="первая правка ячейки"
              />
              <Metric label="Из них по цене" value={stats.price_edits} color="#1d4ed8" />
              <Metric
                label="Пропущено позиций"
                value={stats.rows_added}
                hint="строку добавили руками"
              />
              <Metric
                label="Лишних позиций"
                value={stats.rows_removed}
                hint="строку удалили"
              />
            </div>
          ) : null}
        </div>

        {stats && (stats.top_fields.length > 0 || stats.top_positions.length > 0) && (
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '16px' }}>
            <div style={{ ...cardStyle, flex: '1 1 340px' }}>
              <div style={{ ...labelStyle, marginBottom: '12px' }}>Чаще всего правят поле</div>
              {stats.top_fields.length === 0 ? (
                <div style={{ color: '#94a3b8', fontSize: '13px' }}>Пока пусто</div>
              ) : (
                stats.top_fields.map((f) => (
                  <div
                    key={`${f.document_kind}:${f.field}`}
                    style={{
                      display: 'flex', justifyContent: 'space-between',
                      padding: '6px 0', fontSize: '13px', color: '#334155',
                    }}
                  >
                    <span>
                      {fieldLabel(f.field)}
                      <span style={{ color: '#94a3b8' }}> · {kindLabel(f.document_kind)}</span>
                    </span>
                    <strong>{f.count}</strong>
                  </div>
                ))
              )}
            </div>

            <div style={{ ...cardStyle, flex: '1 1 340px' }}>
              <div style={{ ...labelStyle, marginBottom: '12px' }}>Чаще всего правят позицию</div>
              {stats.top_positions.length === 0 ? (
                <div style={{ color: '#94a3b8', fontSize: '13px' }}>Пока пусто</div>
              ) : (
                stats.top_positions.map((p) => (
                  <div
                    key={`${p.document_kind}:${p.row_name}`}
                    style={{
                      display: 'flex', justifyContent: 'space-between', gap: '12px',
                      padding: '6px 0', fontSize: '13px', color: '#334155',
                    }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.row_name}
                      <span style={{ color: '#94a3b8' }}> · {kindLabel(p.document_kind)}</span>
                    </span>
                    <strong>{p.count}</strong>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        <div style={cardStyle}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: '12px', gap: '12px', flexWrap: 'wrap',
          }}>
            <div style={{ ...labelStyle, marginBottom: 0 }}>Последние расхождения</div>
            <label style={{ fontSize: '13px', color: '#64748b', display: 'flex', gap: '6px', alignItems: 'center' }}>
              <input
                type="checkbox"
                checked={firstTouchOnly}
                onChange={(e) => setFirstTouchOnly(e.target.checked)}
              />
              только ошибки системы
            </label>
          </div>

          {loading ? (
            <div style={{ color: '#94a3b8', fontSize: '13px' }}>Загрузка…</div>
          ) : items.length === 0 ? (
            <div style={{ color: '#94a3b8', fontSize: '13px' }}>
              Правок пока нет. Журнал начнёт заполняться, как только кто-то нажмёт
              «Применить» в редакторе.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={thStyle}>Позиция</th>
                    <th style={thStyle}>Поле</th>
                    <th style={thStyle}>Что случилось</th>
                    <th style={thStyle}>Источник цены</th>
                    <th style={thStyle}>Кто и когда</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td style={tdStyle}>
                        <div style={{ fontWeight: 500 }}>{item.row_name || '—'}</div>
                        <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                          {kindLabel(item.document_kind)}
                          {item.unit ? ` · ${item.unit}` : ''}
                        </div>
                      </td>
                      <td style={tdStyle}>{fieldLabel(item.field)}</td>
                      <td style={{ ...tdStyle, color: '#334155' }}>{verdict(item)}</td>
                      <td style={{ ...tdStyle, color: '#64748b', fontSize: '12px' }}>
                        {item.price_source || '—'}
                      </td>
                      <td style={{ ...tdStyle, color: '#64748b', fontSize: '12px', whiteSpace: 'nowrap' }}>
                        {item.user_name || '—'}
                        <div>{formatDate(item.created_at)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
};

export default CorrectionsPage;
