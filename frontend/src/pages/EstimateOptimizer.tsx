import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import EstimateGrid from '../components/estimate/EstimateGrid';
import AdditionalExpenses from '../components/estimate/AdditionalExpenses';
import EstimateSummary from '../components/estimate/EstimateSummary';
import VersionTabs from '../components/estimate/VersionTabs';
import EstimateComparison from '../components/estimate/EstimateComparison';
import OptimizationToolbar, { AbcBreakdown } from '../components/estimate/OptimizationToolbar';
import OptimizationProposalsPanel from '../components/estimate/OptimizationProposalsPanel';
import { useEstimateEditorStore } from '../stores/estimateEditor';
import { saveExpenses, getVersions, getVersion, runCustomOptimization } from '../api/estimateVersions';
import { getTaskStatus } from '../api/tasks';
import { EstimateRow, EstimateVersionFull, OptimizationProposal, OptimizationStep } from '../types';

interface PanelState {
  proposals: OptimizationProposal[];
  step: OptimizationStep;
  versionId: string;
  abcBreakdown?: AbcBreakdown;
}

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
    setActiveVersion,
    updateRows,
    saveRows,
    setSelectedRowIds,
    setActiveTab,
    setOptimizationStatus,
    reset,
  } = useEstimateEditorStore();

  const [error, setError] = useState('');
  const [activeView, setActiveView] = useState<'version' | 'comparison'>('version');
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [customRunning, setCustomRunning] = useState(false);
  const [processingMsg, setProcessingMsg] = useState<string | null>('Загрузка сметы...');
  const pollingRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!taskId) return;
    reset();
    setProcessingMsg('Загрузка сметы...');

    const tryLoad = async () => {
      try {
        // Fetch task status for progress message
        const taskData = await getTaskStatus(taskId);
        if (taskData.status === 'failed') {
          setProcessingMsg(null);
          setError(taskData.error_message ?? 'Ошибка обработки задачи');
          if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
          return;
        }
        if (taskData.progress_message) setProcessingMsg(taskData.progress_message);

        // Try to load versions — use direct API calls + single setState to avoid double-set crash
        const versionList = await getVersions(taskId);
        if (versionList.length === 0) return;

        const active = versionList.find((v) => !v.is_rolled_back) ?? versionList[0];
        const full = await getVersion(taskId, active.id);

        // Single atomic state update — no double render
        useEstimateEditorStore.setState({
          taskId,
          versions: versionList,
          activeVersionId: active.id,
          activeVersionMeta: active,
          activeRows: full.rows,
          isDirty: false,
          selectedRowIds: new Set<string>(),
        });

        setProcessingMsg(null);
        if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
      } catch {
        // Keep polling — transient errors shouldn't stop us
      }
    };

    tryLoad();
    pollingRef.current = setInterval(tryLoad, 2000);

    return () => {
      if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
    };
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  const reloadVersions = useCallback(async () => {
    if (!taskId) return;
    const updated = await getVersions(taskId);
    useEstimateEditorStore.setState({ versions: updated });
    const still = updated.find((v) => v.id === activeVersionId && !v.is_rolled_back);
    if (!still) {
      const notRolled = updated.filter((v) => !v.is_rolled_back);
      const latest = notRolled[notRolled.length - 1];
      if (latest) await setActiveVersion(latest.id);
    }
  }, [taskId, activeVersionId, setActiveVersion]);

  const handleStepComplete = useCallback(
    async (
      newVersionId: string,
      proposals: OptimizationProposal[],
      step: OptimizationStep,
      abcBreakdown?: AbcBreakdown,
    ) => {
      setOptimizationStatus('idle');
      if (!taskId) return;

      // Reload versions so toolbar can update unlock state
      const updated = await getVersions(taskId);
      useEstimateEditorStore.setState({ versions: updated });

      // Switch to the new analysis version
      await setActiveVersion(newVersionId);

      // Show proposals panel
      if (proposals.length > 0) {
        setPanel({ proposals, step, versionId: newVersionId, abcBreakdown });
      }
    },
    [taskId, setActiveVersion, setOptimizationStatus],
  );

  const handleProposalsApplied = useCallback(
    async (newVersion: EstimateVersionFull) => {
      setPanel(null);
      if (!taskId) return;
      const updated = await getVersions(taskId);
      useEstimateEditorStore.setState({ versions: updated });
      await setActiveVersion(newVersion.id);
    },
    [taskId, setActiveVersion],
  );

  const handleVersionsChange = useCallback(async () => {
    await reloadVersions();
  }, [reloadVersions]);

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
      await setActiveVersion(activeVersionId);
    },
    [taskId, activeVersionId, setActiveVersion],
  );

  const handleCustomOptimize = useCallback(async () => {
    if (!taskId || !activeVersionId || selectedRowIds.size === 0) return;
    setCustomRunning(true);
    try {
      // Save any pending changes first
      if (isDirty) await saveRows();
      const result = await runCustomOptimization(taskId, activeVersionId, [...selectedRowIds]);
      if (result.proposals.length > 0) {
        setPanel({
          proposals: result.proposals,
          step: 'completeness', // custom — reuse panel component, step label not critical
          versionId: activeVersionId,
        });
      }
    } catch {
      // silently ignore
    } finally {
      setCustomRunning(false);
    }
  }, [taskId, activeVersionId, selectedRowIds, isDirty, saveRows]);

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
        <div style={{ marginBottom: '16px' }}>
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

        {/* Processing banner — floats above editor while task is running */}
        {processingMsg && !error && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            padding: '12px 18px', marginBottom: '16px',
            backgroundColor: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: '10px', fontSize: '14px', color: '#1e40af',
          }}>
            <div style={{
              flexShrink: 0, width: '18px', height: '18px',
              border: '2px solid #bfdbfe', borderTopColor: '#3b82f6',
              borderRadius: '50%', animation: 'spin 0.8s linear infinite',
            }} />
            {processingMsg}
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{
            padding: '12px 16px', marginBottom: '16px',
            backgroundColor: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: '8px', color: '#dc2626', fontSize: '14px',
          }}>
            {error}
          </div>
        )}

        {visibleVersions.length > 0 && taskId && (
          <>
            {/* Optimization Toolbar */}
            <OptimizationToolbar
              taskId={taskId}
              versions={visibleVersions}
              onStepComplete={handleStepComplete}
            />

            {/* Proposals Panel */}
            {panel && (
              <OptimizationProposalsPanel
                proposals={panel.proposals}
                step={panel.step}
                taskId={taskId}
                versionId={panel.versionId}
                abcBreakdown={panel.abcBreakdown}
                onProposalsApplied={handleProposalsApplied}
                onDismiss={() => setPanel(null)}
              />
            )}

            {/* VersionTabs */}
            <VersionTabs
              taskId={taskId}
              versions={visibleVersions}
              activeVersionId={activeVersionId}
              activeView={activeView}
              isOptimizationRunning={isReadonly}
              onSelectVersion={(id) => {
                setActiveView('version');
                setActiveVersion(id);
              }}
              onSelectComparison={() => setActiveView('comparison')}
              onVersionsChange={handleVersionsChange}
            />

            {/* Comparison view */}
            {activeView === 'comparison' && (
              <div
                style={{
                  background: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '10px',
                  padding: '20px',
                }}
              >
                <h3 style={{ margin: '0 0 16px', fontSize: '16px', color: '#0f172a' }}>
                  Сравнение версий сметы
                </h3>
                <EstimateComparison taskId={taskId} versions={visibleVersions} />
              </div>
            )}

            {/* Version editor view */}
            {activeView === 'version' && (
              <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start' }}>
                {/* Main column */}
                <div style={{ flex: 1, minWidth: 0 }}>
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

                {/* Right panel: custom optimization */}
                {selectedRowIds.size > 0 && (
                  <div
                    style={{
                      width: '230px',
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
                      disabled={customRunning}
                      style={{
                        width: '100%',
                        padding: '9px 12px',
                        background: customRunning ? '#f0fdf4' : '#f0fdf4',
                        border: '1px solid #bbf7d0',
                        borderRadius: '6px',
                        color: '#166534',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: customRunning ? 'wait' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                      }}
                      onClick={handleCustomOptimize}
                    >
                      {customRunning ? (
                        <>
                          <span
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: '50%',
                              border: '2px solid #86efac',
                              borderTopColor: '#166534',
                              animation: 'opt-spin 0.8s linear infinite',
                              display: 'inline-block',
                            }}
                          />
                          Анализ...
                        </>
                      ) : (
                        `☑ Предложить варианты (${selectedRowIds.size})`
                      )}
                    </button>
                    <p style={{ color: '#94a3b8', fontSize: '11px', marginTop: 8, lineHeight: 1.4 }}>
                      Claude предложит замену технологии, материала и найдёт актуальные цены.
                    </p>
                  </div>
                )}
              </div>
            )}
          </>
        )}

        <style>{`@keyframes opt-spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    </Layout>
  );
};

export default EstimateOptimizer;
