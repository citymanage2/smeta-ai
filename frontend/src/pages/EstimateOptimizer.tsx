import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import EstimateGrid from '../components/estimate/EstimateGrid';
import AdditionalExpenses from '../components/estimate/AdditionalExpenses';
import EstimateSummary from '../components/estimate/EstimateSummary';
import { useEstimateEditorStore } from '../stores/estimateEditor';
import { saveExpenses } from '../api/estimateVersions';
import { EstimateRow } from '../types';

const EstimateOptimizer: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();

  const {
    versions,
    activeVersionId,
    activeVersionMeta,
    activeRows,
    selectedRowIds,
    activeTab,
    optimizationStatus,
    isDirty,
    loadVersions,
    setActiveVersion,
    updateRows,
    saveRows,
    setSelectedRowIds,
    setActiveTab,
    reset,
  } = useEstimateEditorStore();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!taskId) return;
    reset();
    setLoading(true);
    loadVersions(taskId)
      .catch(() => setError('Не удалось загрузить версии сметы'))
      .finally(() => setLoading(false));
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRowsChange = useCallback(
    (rows: EstimateRow[]) => {
      updateRows(rows);
    },
    [updateRows],
  );

  const handleSave = useCallback(async () => {
    await saveRows();
  }, [saveRows]);

  const handleExpensesSave = useCallback(
    async (expenses: { overhead_pct: number; transport_pct: number; contingency_pct: number }) => {
      if (!taskId || !activeVersionId) return;
      await saveExpenses(taskId, activeVersionId, expenses);
      // Reload version to get updated meta
      await setActiveVersion(activeVersionId);
    },
    [taskId, activeVersionId, setActiveVersion],
  );

  const isReadonly = optimizationStatus === 'running';

  const overhead = activeVersionMeta?.overhead_pct ?? 0;
  const transport = activeVersionMeta?.transport_pct ?? 0;
  const contingency = activeVersionMeta?.contingency_pct ?? 0;

  const baseTotal = activeRows
    .filter((r) => r.type === 'work' || r.type === 'material')
    .reduce((acc, r) => acc + (r.qty ?? 0) * ((r.price_work ?? 0) + (r.price_material ?? 0)), 0);

  const visibleVersions = versions.filter((v) => !v.is_rolled_back);

  return (
    <Layout>
      <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
        {/* Page header */}
        <div style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: '#0f172a' }}>
              Оптимизация сметы
            </h2>
            <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '13px' }}>
              Задача: {taskId}
              {isDirty && (
                <span style={{ marginLeft: 10, color: '#f59e0b', fontWeight: 500 }}>
                  • Несохранённые изменения
                </span>
              )}
            </p>
          </div>

          {/* OptimizationToolbar placeholder — фаза 6 */}
          <div
            style={{
              padding: '8px 14px',
              background: '#f1f5f9',
              borderRadius: '8px',
              fontSize: '12px',
              color: '#94a3b8',
            }}
          >
            Инструменты оптимизации — Фаза 6
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ color: '#64748b', fontSize: '15px', padding: '24px 0' }}>
            Загрузка сметы...
          </div>
        )}

        {/* Error */}
        {error && (
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: '8px',
              color: '#dc2626',
              fontSize: '14px',
            }}
          >
            {error}
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && versions.length === 0 && (
          <div
            style={{
              padding: '20px',
              background: '#fef9c3',
              border: '1px solid #fde047',
              borderRadius: '8px',
              color: '#854d0e',
              fontSize: '14px',
            }}
          >
            Смета ещё обрабатывается. Обновите страницу через несколько секунд.
          </div>
        )}

        {!loading && visibleVersions.length > 0 && (
          <div style={{ display: 'flex', gap: '24px', alignItems: 'flex-start' }}>
            {/* Main column */}
            <div style={{ flex: 1, minWidth: 0 }}>
              {/* VersionTabs placeholder — фаза 5 */}
              <div
                style={{
                  display: 'flex',
                  gap: '4px',
                  marginBottom: '16px',
                  flexWrap: 'wrap',
                }}
              >
                {visibleVersions.map((v) => (
                  <button
                    key={v.id}
                    onClick={() => setActiveVersion(v.id)}
                    style={{
                      padding: '6px 14px',
                      fontSize: '13px',
                      fontWeight: activeVersionId === v.id ? 600 : 400,
                      borderRadius: '6px',
                      border: activeVersionId === v.id ? '2px solid #2563eb' : '1px solid #e2e8f0',
                      background: activeVersionId === v.id ? '#eff6ff' : '#fff',
                      color: activeVersionId === v.id ? '#2563eb' : '#374151',
                      cursor: 'pointer',
                      transition: 'all 0.1s',
                    }}
                  >
                    {v.version_display_name}
                  </button>
                ))}
              </div>

              {/* Grid */}
              {activeVersionId && (
                <EstimateGrid
                  rows={activeRows}
                  selectedRowIds={selectedRowIds}
                  activeTab={activeTab}
                  isReadonly={isReadonly}
                  onRowsChange={handleRowsChange}
                  onSelectedRowIdsChange={setSelectedRowIds}
                  onTabChange={setActiveTab}
                  onSave={handleSave}
                />
              )}

              {/* Expenses & summary */}
              {activeVersionId && activeVersionMeta && (
                <>
                  <AdditionalExpenses
                    overhead_pct={overhead}
                    transport_pct={transport}
                    contingency_pct={contingency}
                    baseTotal={baseTotal}
                    onSave={handleExpensesSave}
                  />
                  <EstimateSummary
                    rows={activeRows}
                    overhead_pct={overhead}
                    transport_pct={transport}
                    contingency_pct={contingency}
                  />
                </>
              )}
            </div>

            {/* Right panel: selected rows action */}
            {selectedRowIds.size > 0 && (
              <div
                style={{
                  width: '220px',
                  flexShrink: 0,
                  padding: '16px',
                  background: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              >
                <div style={{ fontWeight: 600, color: '#1e293b', marginBottom: '10px' }}>
                  Выбрано строк: {selectedRowIds.size}
                </div>
                <button
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: '#f0fdf4',
                    border: '1px solid #bbf7d0',
                    borderRadius: '6px',
                    color: '#166534',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                  onClick={() => {
                    /* Phase 6.6 — custom optimization */
                  }}
                >
                  Предложить варианты оптимизации ({selectedRowIds.size})
                </button>
                <p style={{ color: '#94a3b8', fontSize: '11px', marginTop: 8 }}>
                  Ручная оптимизация — Фаза 6
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default EstimateOptimizer;
