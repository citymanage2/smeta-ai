import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import StatusBadge from '../components/StatusBadge';
import VersionHistoryDrawer from '../components/VersionHistoryDrawer';
import OptimizationChecklist from '../components/OptimizationChecklist';
import AnaloguePanel from '../components/AnaloguePanel';
import { listEstimateItems, EstimateItem } from '../api/projects';
import apiClient from '../api/client';

interface TaskStatus {
  id: string;
  task_type: string;
  status: string;
  estimate_status: 'uploaded' | 'calculated' | 'optimized';
  estimate_status_updated_by: 'manual' | 'auto';
}

const TASK_TYPE_LABEL: Record<string, string> = {
  SMETA_FROM_LIST: 'Смета из перечня',
  SMETA_FROM_TZ: 'Смета из ТЗ',
  SMETA_FROM_TZ_PROJECT: 'Смета ТЗ+проект',
  SMETA_FROM_PROJECT: 'Смета из проекта',
  SMETA_FROM_EDC_PROJECT: 'Смета из ЭДЦ+проект',
  SMETA_FROM_GRAND_PROJECT: 'Смета из Гранд+проект',
};

const EstimateView: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();

  const [task, setTask] = useState<TaskStatus | null>(null);
  const [items, setItems] = useState<EstimateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [optimizationOpen, setOptimizationOpen] = useState(false);
  const [expandedAnalogue, setExpandedAnalogue] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!taskId) return;
    try {
      const [statusRes, itemsData] = await Promise.all([
        apiClient.get<TaskStatus>(`/tasks/${taskId}/status`),
        listEstimateItems(taskId),
      ]);
      setTask(statusRes.data);
      setItems(itemsData);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => { loadData(); }, [loadData]);

  const totalWorks = items.reduce((s, i) => {
    if (i.type === 'Работа' && i.work_price && i.quantity) return s + i.work_price * i.quantity;
    return s;
  }, 0);
  const totalMats = items.reduce((s, i) => {
    if (i.type === 'Материал' && i.mat_price && i.quantity) return s + i.mat_price * i.quantity;
    return s;
  }, 0);
  const grandTotal = totalWorks + totalMats;
  const vat = grandTotal * 0.22;

  const sections = Array.from(new Set(items.map(i => i.section || ''))).filter(Boolean);

  const renderItem = (item: EstimateItem) => {
    const price = (item.work_price || 0) + (item.mat_price || 0);
    const total = price * (item.quantity || 0);
    const isOptimized = item.notes?.startsWith('[ОПТИМИЗИРОВАНО]');
    const showAnalogue = expandedAnalogue === item.id;

    return (
      <React.Fragment key={item.id}>
        <tr style={{
          background: isOptimized ? '#f0fdf4' : item.is_analogue ? '#eff6ff' : 'transparent',
          borderBottom: '1px solid #f3f4f6',
        }}>
          <td style={{ padding: '7px 10px', color: '#6b7280', fontSize: 12 }}>
            {item.position + 1}
          </td>
          <td style={{ padding: '7px 10px', fontSize: 13, color: '#111827' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{
                display: 'inline-block',
                fontSize: 10, fontWeight: 700, padding: '1px 6px',
                borderRadius: 4,
                background: item.type === 'Работа' ? '#fef3c7' : '#e0e7ff',
                color: item.type === 'Работа' ? '#92400e' : '#3730a3',
              }}>
                {item.type}
              </span>
              {item.name}
              {item.is_analogue && (
                <span
                  title={`Оригинал: ${(item.extra as Record<string, unknown>)?.original_name}`}
                  style={{
                    fontSize: 10, background: '#dbeafe', color: '#1d4ed8',
                    borderRadius: 6, padding: '1px 7px', cursor: 'help',
                  }}
                >
                  Аналог
                </span>
              )}
              {isOptimized && (
                <span style={{
                  fontSize: 10, background: '#dcfce7', color: '#166534',
                  borderRadius: 6, padding: '1px 7px',
                }}>
                  Оптимизировано
                </span>
              )}
            </div>
            {item.notes && !isOptimized && (
              <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>{item.notes}</div>
            )}
            {isOptimized && (
              <div style={{ fontSize: 11, color: '#059669', marginTop: 2 }}>
                {item.notes?.replace('[ОПТИМИЗИРОВАНО] ', '')}
              </div>
            )}
          </td>
          <td style={{ padding: '7px 10px', fontSize: 12, color: '#6b7280', whiteSpace: 'nowrap' }}>
            {item.unit}
          </td>
          <td style={{ padding: '7px 10px', fontSize: 12, textAlign: 'right', color: '#374151' }}>
            {item.quantity?.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}
          </td>
          <td style={{ padding: '7px 10px', fontSize: 12, textAlign: 'right', color: '#374151' }}>
            {price > 0 ? price.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : '—'}
          </td>
          <td style={{ padding: '7px 10px', fontSize: 12, textAlign: 'right', fontWeight: 600, color: '#111827' }}>
            {total > 0 ? total.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) : '—'}
          </td>
          <td style={{ padding: '7px 10px', textAlign: 'center' }}>
            {item.type === 'Материал' && (
              item.is_analogue ? (
                <button
                  onClick={() => setExpandedAnalogue(showAnalogue ? null : item.id)}
                  style={{
                    border: '1px solid #fca5a5', background: '#fff',
                    borderRadius: 6, padding: '3px 8px', cursor: 'pointer',
                    fontSize: 11, color: '#dc2626',
                  }}
                >
                  ↩ Откатить
                </button>
              ) : (
                <button
                  onClick={() => setExpandedAnalogue(showAnalogue ? null : item.id)}
                  style={{
                    border: '1px solid #c7d2fe', background: '#fff',
                    borderRadius: 6, padding: '3px 8px', cursor: 'pointer',
                    fontSize: 11, color: '#4f46e5',
                  }}
                >
                  ⇄ Аналоги
                </button>
              )
            )}
          </td>
        </tr>

        {/* Analogue panel */}
        {showAnalogue && (
          <tr>
            <td colSpan={7} style={{ padding: '0 10px 10px 40px' }}>
              <AnaloguePanel
                taskId={taskId!}
                item={item}
                onChanged={() => { setExpandedAnalogue(null); loadData(); }}
              />
            </td>
          </tr>
        )}
      </React.Fragment>
    );
  };

  if (loading) {
    return (
      <Layout>
        <div style={{ padding: 32, color: '#6b7280' }}>Загрузка сметы...</div>
      </Layout>
    );
  }

  if (!task) {
    return (
      <Layout>
        <div style={{ padding: 32, color: '#dc2626' }}>Смета не найдена</div>
      </Layout>
    );
  }

  const isSmeta = TASK_TYPE_LABEL[task.task_type.toUpperCase()];

  return (
    <Layout>
      {/* Header */}
      <div style={{
        padding: '16px 24px', borderBottom: '1px solid #e5e7eb',
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#6b7280', fontSize: 20 }}
        >
          ←
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 16, color: '#111827' }}>
            {TASK_TYPE_LABEL[task.task_type.toUpperCase()] || task.task_type}
          </div>
          <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>{task.id}</div>
        </div>

        <StatusBadge
          taskId={task.id}
          status={task.estimate_status}
          updatedBy={task.estimate_status_updated_by}
          onChange={s => setTask(prev => prev ? { ...prev, estimate_status: s } : prev)}
        />

        <button
          onClick={() => setHistoryOpen(true)}
          style={{
            border: '1px solid #d1d5db', background: '#fff',
            borderRadius: 8, padding: '6px 14px', cursor: 'pointer',
            fontSize: 13, color: '#374151', display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          🕐 История изменений
        </button>

        {isSmeta && items.length > 0 && (
          <button
            onClick={() => setOptimizationOpen(true)}
            style={{
              border: 'none', background: '#2563eb', color: '#fff',
              borderRadius: 8, padding: '7px 16px', cursor: 'pointer',
              fontSize: 13, fontWeight: 600,
            }}
          >
            ✨ Оптимизировать
          </button>
        )}
      </div>

      {/* Items table */}
      {items.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
          <p>Позиции сметы не найдены.</p>
          <p style={{ fontSize: 13 }}>
            Позиции появятся после успешного расчёта сметы (задача должна завершиться со статусом «done»).
          </p>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', padding: '0 16px 24px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                {['№', 'Наименование', 'Ед.', 'Кол-во', 'Цена, ₽', 'Сумма, ₽', ''].map(h => (
                  <th key={h} style={{
                    padding: '10px 10px', textAlign: h === 'Наименование' ? 'left' : 'right',
                    color: '#6b7280', fontWeight: 600, fontSize: 12,
                    whiteSpace: 'nowrap',
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sections.length > 0
                ? sections.map(section => (
                    <React.Fragment key={section}>
                      <tr>
                        <td colSpan={7} style={{
                          padding: '10px 10px 4px',
                          fontWeight: 700, fontSize: 12,
                          color: '#4b5563',
                          background: '#f9fafb',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}>
                          {section}
                        </td>
                      </tr>
                      {items.filter(i => i.section === section).map(renderItem)}
                    </React.Fragment>
                  ))
                : items.map(renderItem)
              }
            </tbody>
          </table>

          {/* Totals */}
          <div style={{
            marginTop: 16, borderTop: '2px solid #e5e7eb',
            display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
            gap: 4, padding: '12px 10px',
          }}>
            {[
              ['Итого работы', totalWorks],
              ['Итого материалы', totalMats],
              ['Итого без НДС', grandTotal],
              ['НДС 22%', vat],
            ].map(([label, val]) => (
              <div key={String(label)} style={{ display: 'flex', gap: 24, fontSize: 13, color: '#374151' }}>
                <span style={{ color: '#6b7280' }}>{label}:</span>
                <span style={{ fontWeight: 600, minWidth: 120, textAlign: 'right' }}>
                  {(val as number).toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
                </span>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 24, fontSize: 15, fontWeight: 700, color: '#111827', marginTop: 4 }}>
              <span>Итого с НДС:</span>
              <span style={{ minWidth: 120, textAlign: 'right' }}>
                {(grandTotal + vat).toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Drawers & modals */}
      <VersionHistoryDrawer
        taskId={task.id}
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onRestored={loadData}
      />
      <OptimizationChecklist
        taskId={task.id}
        open={optimizationOpen}
        onClose={() => setOptimizationOpen(false)}
        onOptimized={() => {
          setOptimizationOpen(false);
          setTimeout(loadData, 3000); // poll after delay
        }}
      />
    </Layout>
  );
};

export default EstimateView;
