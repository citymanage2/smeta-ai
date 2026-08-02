import React, { useCallback, useEffect, useState } from 'react';
import { formatTaskError } from '../utils/formatError';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Layout from '../components/Layout';
import { LumaSpin } from '../components/ui/LumaSpin';
import EstimateGrid from '../components/estimate/EstimateGrid';
import DocumentEditor from '../components/editor/DocumentEditor';
import { DocumentKind, locateDocumentByTask } from '../api/documents';
import AdditionalExpenses from '../components/estimate/AdditionalExpenses';
import EstimateSummary from '../components/estimate/EstimateSummary';
import VersionTabs from '../components/estimate/VersionTabs';
import EstimateComparison from '../components/estimate/EstimateComparison';
import OptimizationToolbar, { AbcBreakdown } from '../components/estimate/OptimizationToolbar';
import OptimizationProposalsPanel from '../components/estimate/OptimizationProposalsPanel';
import { useEstimateEditorStore } from '../stores/estimateEditor';
import {
  saveExpenses,
  getVersions,
  getVersion,
  runCustomOptimization,
  initEstimateVersionFromResult,
} from '../api/estimateVersions';
import { getTaskStatus } from '../api/tasks';
import {
  EstimateRow,
  EstimateVersionFull,
  GENERIC_EDITOR_TASK_TYPES,
  OptimizationProposal,
  OptimizationStep,
} from '../types';

interface PanelState {
  proposals: OptimizationProposal[];
  step: OptimizationStep;
  versionId: string;
  abcBreakdown?: AbcBreakdown;
  autoApplied?: boolean;
}

interface StepResultBanner {
  step: OptimizationStep;
  count: number;
}

interface OrphanedGroup {
  work: EstimateRow;
  materials: EstimateRow[];
}

interface DeleteDialog {
  orphanedGroups: OrphanedGroup[];
  rowIdsToDelete: string[];
}

/** Find material rows that immediately follow a work row (until next work/section). */
function getMaterialsForWork(workId: string, allRows: EstimateRow[]): EstimateRow[] {
  const idx = allRows.findIndex((r) => r.id === workId);
  if (idx === -1) return [];
  const result: EstimateRow[] = [];
  for (let i = idx + 1; i < allRows.length; i++) {
    const r = allRows[i];
    if (r.type === 'section' || r.type === 'work') break;
    if (r.type === 'material') result.push(r);
  }
  return result;
}

const EstimateOptimizer: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const embed = searchParams.get('embed') === '1';
  const urlReadOnly = searchParams.get('read_only') === '1';
  const fileSlot = searchParams.get('file_slot') ?? 'result';
  const fileIndex = parseInt(searchParams.get('file_index') ?? '0', 10);

  const {
    versions,
    activeVersionId,
    activeVersionMeta,
    activeRows,
    selectedRowIds,
    activeTab,
    optimizationStatus,
    isDirty,
    undoStack,
    redoStack,
    setActiveVersion,
    updateRows,
    saveRows,
    setSelectedRowIds,
    setActiveTab,
    setOptimizationStatus,
    undo,
    redo,
    deleteRows,
    reset,
  } = useEstimateEditorStore();

  const [error, setError] = useState('');
  const [taskName, setTaskName] = useState<string | null>(null);
  const [taskType, setTaskType] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'version' | 'comparison'>('version');
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [stepResultBanner, setStepResultBanner] = useState<StepResultBanner | null>(null);
  const [customRunning, setCustomRunning] = useState(false);
  const [processingMsg, setProcessingMsg] = useState<string | null>('Загрузка...');
  const [processingTooLong, setProcessingTooLong] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialog | null>(null);
  const pollingRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const processingStartRef = React.useRef<number | null>(null);
  const stuckTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  // Плоские документы (перечень, полнота) живут в едином редакторе: здесь
  // остаётся только найти карточку, которой принадлежит задача.
  const [documentRef, setDocumentRef] = useState<{ cardId: string; kind: DocumentKind } | null>(null);

  const isGenericMode = taskType !== null && GENERIC_EDITOR_TASK_TYPES.has(taskType);

  useEffect(() => {
    if (!taskId) return;
    reset();
    setProcessingMsg('Загрузка...');
    setProcessingTooLong(false);
    processingStartRef.current = Date.now();
    setTaskType(null);
    setDocumentRef(null);

    // Show "stuck" warning after 3 minutes of processing
    stuckTimerRef.current = setTimeout(() => setProcessingTooLong(true), 3 * 60 * 1000);

    const tryLoad = async () => {
      try {
        const taskData = await getTaskStatus(taskId);
        if (taskData.name) setTaskName(taskData.name);
        if (taskData.project_id) setProjectId(taskData.project_id);
        if (taskData.status === 'failed') {
          setProcessingMsg(null);
          setError(formatTaskError(taskData.error_message));
          if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
          return;
        }
        if (taskData.progress_message) setProcessingMsg(taskData.progress_message);

        const currentTaskType: string = taskData.task_type;
        setTaskType(currentTaskType);

        if (GENERIC_EDITOR_TASK_TYPES.has(currentTaskType)) {
          // Единый редактор работает с документом карточки, а не с задачей:
          // всю загрузку, черновики и историю он берёт на себя сам.
          if (taskData.status !== 'completed') return;
          try {
            const located = await locateDocumentByTask(taskId);
            setDocumentRef({ cardId: located.card_id, kind: located.kind });
          } catch {
            setError('Не удалось открыть документ. Возможно, задача не привязана к смете.');
          }
          setProcessingMsg(null);
          setProcessingTooLong(false);
          if (stuckTimerRef.current) { clearTimeout(stuckTimerRef.current); stuckTimerRef.current = null; }
          if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
        } else {
          // Estimate mode: existing logic
          // ESTIMATE_FROM_LIST stores its estimate version in file_slot='estimate' — filter
          // explicitly so generic versions (file_slot='result') don't shadow it.
          const estimateSlot = currentTaskType === 'ESTIMATE_FROM_LIST' ? 'estimate' : undefined;
          let versionList = await getVersions(taskId, estimateSlot);
          if (versionList.length === 0) {
            if (taskData.status === 'completed') {
              if (currentTaskType === 'ESTIMATE_FROM_LIST') {
                // Auto-init structured EstimateVersion from the task result
                try { await initEstimateVersionFromResult(taskId); } catch { /* idempotent */ }
                versionList = await getVersions(taskId, estimateSlot);
              }
              if (versionList.length === 0) {
                setProcessingMsg(null);
                setError('Не удалось загрузить версии сметы. Попробуйте закрыть и открыть снова.');
                if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
                if (stuckTimerRef.current) { clearTimeout(stuckTimerRef.current); stuckTimerRef.current = null; }
              }
            }
            return;
          }

          const active = versionList.find((v) => !v.is_rolled_back) ?? versionList[0];
          const full = await getVersion(taskId, active.id);

          useEstimateEditorStore.setState({
            taskId,
            versions: versionList,
            activeVersionId: active.id,
            activeVersionMeta: active,
            activeRows: full.rows,
            isDirty: false,
            selectedRowIds: new Set<string>(),
            undoStack: [],
            redoStack: [],
          });

          setProcessingMsg(null);
          setProcessingTooLong(false);
          if (stuckTimerRef.current) { clearTimeout(stuckTimerRef.current); stuckTimerRef.current = null; }
          if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
        }
      } catch {
        // Keep polling on transient errors
      }
    };

    tryLoad();
    pollingRef.current = setInterval(tryLoad, 2000);

    return () => {
      if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
      if (stuckTimerRef.current) { clearTimeout(stuckTimerRef.current); stuckTimerRef.current = null; }
    };
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Estimate mode callbacks ───────────────────────────────────────────────

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
      _abcBreakdown?: AbcBreakdown,
    ) => {
      setOptimizationStatus('idle');
      if (!taskId) return;

      const updated = await getVersions(taskId);
      useEstimateEditorStore.setState({ versions: updated });

      await setActiveVersion(newVersionId);

      setStepResultBanner({ step, count: proposals.length });
      setPanel(null);
    },
    [taskId, setActiveVersion, setOptimizationStatus],
  );

  const handleViewStep = useCallback(
    async (versionId: string, step: OptimizationStep) => {
      if (!taskId) return;
      setActiveView('version');
      try {
        await setActiveVersion(versionId);
        if (step !== 'fill_prices') {
          const full = await getVersion(taskId, versionId);
          setPanel({ proposals: full.optimization_proposals ?? [], step, versionId, autoApplied: true });
        }
      } catch {
        // silently ignore
      }
    },
    [taskId, setActiveVersion],
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
      if (isDirty) await saveRows();
      const result = await runCustomOptimization(taskId, activeVersionId, [...selectedRowIds]);
      if (result.proposals.length > 0) {
        setPanel({
          proposals: result.proposals,
          step: 'completeness',
          versionId: activeVersionId,
        });
      }
    } catch {
      // silently ignore
    } finally {
      setCustomRunning(false);
    }
  }, [taskId, activeVersionId, selectedRowIds, isDirty, saveRows]);

  const executeDeleteRows = useCallback(
    async (rowIds: string[]) => {
      deleteRows(rowIds);
      setDeleteDialog(null);
      await saveRows();
    },
    [deleteRows, saveRows],
  );

  const handleDeleteRows = useCallback(() => {
    if (selectedRowIds.size === 0) return;
    const idsToDelete = [...selectedRowIds];
    const selectedWorks = activeRows.filter(
      (r) => idsToDelete.includes(r.id) && r.type === 'work',
    );

    const orphanedGroups: OrphanedGroup[] = [];
    for (const work of selectedWorks) {
      const associated = getMaterialsForWork(work.id, activeRows);
      const unselected = associated.filter((m) => !idsToDelete.includes(m.id));
      if (unselected.length > 0) {
        orphanedGroups.push({ work, materials: unselected });
      }
    }

    if (orphanedGroups.length > 0) {
      setDeleteDialog({ orphanedGroups, rowIdsToDelete: idsToDelete });
    } else {
      executeDeleteRows(idsToDelete);
    }
  }, [selectedRowIds, activeRows, executeDeleteRows]);

  const handleDeletePosition = useCallback(() => {
    if (selectedRowIds.size === 0) return;
    const idsToDelete = new Set([...selectedRowIds]);
    const selectedWorks = activeRows.filter((r) => idsToDelete.has(r.id) && r.type === 'work');
    for (const work of selectedWorks) {
      const associated = getMaterialsForWork(work.id, activeRows);
      associated.forEach((m) => idsToDelete.add(m.id));
    }
    executeDeleteRows([...idsToDelete]);
  }, [selectedRowIds, activeRows, executeDeleteRows]);

  const isReadonly = optimizationStatus === 'running' || urlReadOnly;
  const canUndo = undoStack.length > 0;
  const canRedo = redoStack.length > 0;

  const overhead = activeVersionMeta?.overhead_pct ?? 0;
  const transport = activeVersionMeta?.transport_pct ?? 0;
  const contingency = activeVersionMeta?.contingency_pct ?? 0;

  const baseTotal = activeRows
    .filter((r) => (r.type === 'work' || r.type === 'material') && !r.is_excluded)
    .reduce((acc, r) => acc + (r.qty ?? 0) * ((r.price_work ?? 0) + (r.price_material ?? 0)), 0);

  const visibleVersions = versions.filter((v) => !v.is_rolled_back);

  const btnBase: React.CSSProperties = {
    width: '100%',
    padding: '8px 12px',
    borderRadius: '6px',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    border: '1px solid',
  };

  // ─── Generic mode title label ──────────────────────────────────────────────
  const genericTitle = taskType === 'CHECK_LIST_COMPLETENESS' || taskType === 'CHECK_PROJECT_COMPLETENESS'
    ? 'Просмотр результата проверки полноты'
    : 'Просмотр и редактирование перечня';

  // ─── Content ──────────────────────────────────────────────────────────────
  const content = (
    <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
      {/* Page header */}
      <div style={{ marginBottom: '16px' }}>
        {projectId && !embed && (
          <button
            onClick={() => navigate(`/projects/${projectId}`)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              background: 'none', border: '1px solid #e2e8f0', borderRadius: '8px',
              padding: '6px 12px', cursor: 'pointer', color: '#64748b', fontSize: '13px',
              marginBottom: '10px', transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd'; (e.currentTarget as HTMLElement).style.color = '#3b82f6'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#e2e8f0'; (e.currentTarget as HTMLElement).style.color = '#64748b'; }}
          >
            <ArrowLeft size={14} />
            К проекту
          </button>
        )}
        <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: '#0f172a' }}>
          {taskName || (isGenericMode ? genericTitle : taskType === 'ESTIMATE_FROM_LIST' ? 'Смета из перечня' : 'Оптимизация сметы')}
        </h2>
        {isGenericMode ? (
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '13px' }}>
            {genericTitle}
          </p>
        ) : (
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '13px' }}>
            {taskName && (taskType === 'ESTIMATE_FROM_LIST' ? 'Просмотр и редактирование сметы' : 'Оптимизация сметы')}
            {isDirty && (
              <span style={{ marginLeft: taskName ? 10 : 0, color: '#f59e0b', fontWeight: 500 }}>
                {taskName ? '• Несохранённые изменения' : 'Несохранённые изменения'}
              </span>
            )}
          </p>
        )}
      </div>

      {/* Processing banner */}
      {processingMsg && !error && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '12px',
          padding: '12px 18px', marginBottom: '16px',
          backgroundColor: '#eff6ff', border: '1px solid #bfdbfe',
          borderRadius: '10px', fontSize: '14px', color: '#1e40af',
        }}>
          <LumaSpin size="sm" color="#3b82f6" />
          {processingMsg}
        </div>
      )}

      {/* Stuck task warning */}
      {processingTooLong && processingMsg && !error && (
        <div style={{
          padding: '12px 16px', marginBottom: '16px',
          backgroundColor: '#fffbeb', border: '1px solid #fde68a',
          borderRadius: '8px', color: '#92400e', fontSize: '13px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
        }}>
          <span>
            ⚠ Задача выполняется дольше обычного. Возможно, сервер был перезапущен в процессе.
            Попробуйте обновить страницу или запустить задачу заново.
          </span>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '5px 12px', borderRadius: '6px', fontSize: '12px',
              fontWeight: 600, border: '1px solid #fcd34d',
              background: '#fef3c7', color: '#92400e', cursor: 'pointer',
              whiteSpace: 'nowrap', flexShrink: 0,
            }}
          >
            Обновить
          </button>
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

      {/* ── Плоские документы: перечень и полнота ───────────────────────── */}
      {isGenericMode && documentRef && (
        <DocumentEditor
          cardId={documentRef.cardId}
          kind={documentRef.kind}
          fileSlot={fileSlot === 'input' ? 'input' : undefined}
          fileIndex={fileSlot === 'input' ? fileIndex : undefined}
          onApplied={() => {
            // Страница может быть открыта из карточки — сообщаем ей об изменении.
            try { window.parent.postMessage({ type: 'estimate-saved', taskId }, '*'); } catch { /* нет родителя */ }
          }}
        />
      )}

      {/* ── Estimate mode ───────────────────────────────────────────────── */}
      {!isGenericMode && visibleVersions.length > 0 && taskId && (
        <>
          {taskType === 'ESTIMATE_OPTIMIZATION' && (
            <OptimizationToolbar
              taskId={taskId}
              versions={visibleVersions}
              onStepComplete={handleStepComplete}
              onViewStep={handleViewStep}
            />
          )}

          {taskType === 'ESTIMATE_OPTIMIZATION' && stepResultBanner && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 16px', marginBottom: '12px',
              background: '#f0fdf4', border: '1px solid #86efac', borderRadius: '8px',
              fontSize: '13px', color: '#166534',
            }}>
              <span>
                <strong>✓ Шаг завершён</strong> — {stepResultBanner.step === 'fill_prices'
                  ? (stepResultBanner.count > 0
                    ? `Цены проставлены для ${stepResultBanner.count} позиций.`
                    : 'По всем позициям цены проставлены. Дополнительного поиска не требуется.')
                  : (stepResultBanner.count > 0
                    ? `${stepResultBanner.count} предложений применено автоматически. Добавленные позиции выделены цветом в смете.`
                    : 'Смета соответствует нормативам, предложений нет.')}
              </span>
              <button
                onClick={() => setStepResultBanner(null)}
                style={{ background: 'none', border: 'none', color: '#166534', cursor: 'pointer', fontSize: '16px', padding: '0 4px', marginLeft: 12 }}
              >
                ✕
              </button>
            </div>
          )}

          {taskType === 'ESTIMATE_OPTIMIZATION' && panel && (
            <OptimizationProposalsPanel
              proposals={panel.proposals}
              step={panel.step}
              taskId={taskId}
              versionId={panel.versionId}
              abcBreakdown={panel.abcBreakdown}
              autoApplied={panel.autoApplied}
              onProposalsApplied={handleProposalsApplied}
              onDismiss={() => setPanel(null)}
            />
          )}

          {!embed && (
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
          )}

          {activeView === 'comparison' && (
            <div style={{
              background: '#fff', border: '1px solid #e2e8f0',
              borderRadius: '10px', padding: '20px',
            }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '16px', color: '#0f172a' }}>
                Сравнение версий сметы
              </h3>
              <EstimateComparison taskId={taskId} versions={visibleVersions} />
            </div>
          )}

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
                    canUndo={canUndo}
                    canRedo={canRedo}
                    onRowsChange={handleRowsChange}
                    onSelectedRowIdsChange={setSelectedRowIds}
                    onTabChange={setActiveTab}
                    onSave={handleSave}
                    onUndo={undo}
                    onRedo={redo}
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

              {/* Right panel: actions for selected rows */}
              {selectedRowIds.size > 0 && (
                <div style={{
                  width: '230px',
                  flexShrink: 0,
                  padding: '16px',
                  background: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  fontSize: '13px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}>
                  <div style={{ fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
                    Выбрано строк: {selectedRowIds.size}
                  </div>

                  <button
                    disabled={customRunning || isReadonly}
                    style={{
                      ...btnBase,
                      background: customRunning ? '#f0fdf4' : '#f0fdf4',
                      borderColor: '#bbf7d0',
                      color: '#166534',
                      cursor: customRunning || isReadonly ? 'wait' : 'pointer',
                    }}
                    onClick={handleCustomOptimize}
                  >
                    {customRunning ? (
                      <>
                        <LumaSpin size="sm" color="#166534" />
                        Анализ...
                      </>
                    ) : (
                      `☑ Предложить варианты (${selectedRowIds.size})`
                    )}
                  </button>

                  <div style={{ borderTop: '1px solid #f1f5f9', marginTop: 2 }} />

                  <button
                    disabled={isReadonly}
                    style={{
                      ...btnBase,
                      background: '#fff',
                      borderColor: '#fca5a5',
                      color: '#dc2626',
                      opacity: isReadonly ? 0.5 : 1,
                    }}
                    onClick={handleDeleteRows}
                    title="Удалить только выбранные строки"
                  >
                    🗑 Удалить строку
                  </button>

                  <button
                    disabled={isReadonly}
                    style={{
                      ...btnBase,
                      background: '#fff',
                      borderColor: '#fca5a5',
                      color: '#b91c1c',
                      opacity: isReadonly ? 0.5 : 1,
                    }}
                    onClick={handleDeletePosition}
                    title="Удалить выбранные работы вместе со всеми их материалами"
                  >
                    🗑 Удалить позицию
                  </button>

                  <p style={{ color: '#94a3b8', fontSize: '11px', marginTop: 4, lineHeight: 1.4 }}>
                    «Строку» — только выбранные. «Позицию» — работу вместе со всеми её материалами.
                  </p>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Delete dialog — orphaned materials warning */}
      {deleteDialog && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setDeleteDialog(null)}
        >
          <div
            style={{
              background: '#fff', borderRadius: '12px',
              padding: '24px', maxWidth: '520px', width: '90%',
              boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
              maxHeight: '80vh', overflowY: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 700, fontSize: '16px', color: '#0f172a', marginBottom: 8 }}>
              Обнаружены связанные материалы
            </div>
            <p style={{ color: '#475569', fontSize: '13px', margin: '0 0 16px' }}>
              Вы удаляете работы, к которым в смете относятся материалы. Что сделать с ними?
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              {deleteDialog.orphanedGroups.map(({ work, materials }) => (
                <div
                  key={work.id}
                  style={{
                    padding: '10px 14px',
                    background: '#fef2f2',
                    border: '1px solid #fecaca',
                    borderRadius: '8px',
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: '13px', color: '#991b1b' }}>
                    Работа: {work.name}
                  </div>
                  <div style={{ fontSize: '12px', color: '#64748b', marginTop: 6 }}>
                    Материалы ({materials.length}):
                    <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
                      {materials.slice(0, 4).map((m) => (
                        <li key={m.id}>{m.name}</li>
                      ))}
                      {materials.length > 4 && (
                        <li style={{ color: '#94a3b8' }}>...ещё {materials.length - 4}</li>
                      )}
                    </ul>
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button
                onClick={() => setDeleteDialog(null)}
                style={{
                  padding: '8px 16px', borderRadius: '6px', fontSize: '13px',
                  fontWeight: 500, border: '1px solid #e2e8f0', background: '#fff',
                  cursor: 'pointer', color: '#475569',
                }}
              >
                Отмена
              </button>
              <button
                onClick={() => executeDeleteRows(deleteDialog.rowIdsToDelete)}
                style={{
                  padding: '8px 16px', borderRadius: '6px', fontSize: '13px',
                  fontWeight: 600, border: '1px solid #fca5a5', background: '#fff',
                  cursor: 'pointer', color: '#dc2626',
                }}
              >
                Удалить только работы
              </button>
              <button
                onClick={() => {
                  const allIds = [
                    ...deleteDialog.rowIdsToDelete,
                    ...deleteDialog.orphanedGroups.flatMap((g) => g.materials.map((m) => m.id)),
                  ];
                  executeDeleteRows(allIds);
                }}
                style={{
                  padding: '8px 16px', borderRadius: '6px', fontSize: '13px',
                  fontWeight: 600, border: 'none', background: '#dc2626',
                  cursor: 'pointer', color: '#fff',
                }}
              >
                Удалить и материалы тоже
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  if (embed) {
    return (
      <div
        style={{
          height: '100vh',
          overflowY: 'auto',
          backgroundColor: '#f8fafc',
          padding: '16px 20px',
          boxSizing: 'border-box',
        }}
      >
        {content}
      </div>
    );
  }

  return <Layout>{content}</Layout>;
};

export default EstimateOptimizer;
