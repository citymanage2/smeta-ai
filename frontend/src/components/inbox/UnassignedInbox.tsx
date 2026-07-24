import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Pencil, Check, X } from 'lucide-react';
import { TaskBrief, TASK_TYPE_LABELS, ESTIMATE_TASK_TYPES } from '../../types';
import { getUnassignedTasks, downloadSlotFile, uploadFileToSlot } from '../../api/projects';
import { updateTask, renameSlotFile } from '../../api/tasks';
import OptimizeModal from '../OptimizeModal';
import HistoryModal from '../HistoryModal';
import { StageStateBadge } from '../StageStateBadge';

// ---------------------------------------------------------------------------
// «Ничейные» задачи (без project_id) как источник строк «Входящего».
// Логика/действия (SlotRow, переименование слотов, скачивание, загрузка,
// оптимизация, история) перенесены сюда из бывшей страницы UnassignedTasks,
// чтобы поглотить её без потери функциональности.
// ---------------------------------------------------------------------------

const HIDDEN_TASK_TYPES = new Set(['CHECK_LIST_COMPLETENESS', 'CHECK_PROJECT_COMPLETENESS']);
// pending/processing показываются в активной очереди дашборда (active_queue), поэтому
// исключаются из группы «Без проекта». paused НЕ входит в active_queue на бэке —
// оставляем его в «Без проекта», иначе задача на паузе исчезает из «Входящего».
const ACTIVE_STATUSES = new Set(['pending', 'processing']);

function formatCost(cost: number): string {
  return cost.toLocaleString('ru-RU') + ' ₽';
}

const iconBtnStyle: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer', padding: '2px',
  display: 'inline-flex', alignItems: 'center', color: '#94a3b8',
};

function InlineEditName({ value, onSave }: { value: string; onSave: (name: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) { inputRef.current.focus(); inputRef.current.select(); }
  }, [editing]);

  async function save() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) { await onSave(trimmed); }
    setEditing(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') { setDraft(value); setEditing(false); }
  }

  if (editing) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <input
          ref={inputRef}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          style={{ border: '1px solid #93c5fd', borderRadius: 6, padding: '4px 8px', outline: 'none', fontSize: 13, fontWeight: 600, width: 220 }}
        />
        <button style={{ ...iconBtnStyle, color: '#16a34a' }} onClick={save}><Check size={14} /></button>
        <button style={{ ...iconBtnStyle, color: '#dc2626' }} onClick={() => { setDraft(value); setEditing(false); }}><X size={14} /></button>
      </span>
    );
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span>{value}</span>
      <button style={iconBtnStyle} onClick={() => { setDraft(value); setEditing(true); }}><Pencil size={14} /></button>
    </span>
  );
}

function SlotRow({ label, fileName, slot, onDownload, allowUpload, onUpload, onRename }: {
  label: string; fileName: string | null; slot: string;
  onDownload: () => void; allowUpload?: boolean;
  onUpload?: (file: File) => Promise<void>;
  onRename?: (name: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fileName ?? '');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) { inputRef.current.focus(); inputRef.current.select(); }
  }, [editing]);

  async function saveRename() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== fileName && onRename) await onRename(trimmed);
    setEditing(false);
  }

  return (
    <div style={{ fontSize: 12, color: '#64748b' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontWeight: 500, color: '#94a3b8', minWidth: 100 }}>{label}:</span>
        {fileName ? (
          editing ? (
            <>
              <input ref={inputRef} value={draft} onChange={e => setDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); saveRename(); } if (e.key === 'Escape') setEditing(false); }}
                style={{ border: '1px solid #93c5fd', borderRadius: 4, padding: '2px 6px', outline: 'none', fontSize: 12, flex: 1, minWidth: 0 }}
              />
              <button style={{ ...iconBtnStyle, color: '#16a34a' }} onClick={saveRename}><Check size={13} /></button>
              <button style={{ ...iconBtnStyle, color: '#dc2626' }} onClick={() => setEditing(false)}><X size={13} /></button>
            </>
          ) : (
            <>
              <span style={{ color: '#475569' }}>{fileName}</span>
              {onRename && slot !== 'source' && (
                <button style={iconBtnStyle} onClick={() => { setDraft(fileName); setEditing(true); }}><Pencil size={11} /></button>
              )}
              <button onClick={e => { e.stopPropagation(); onDownload(); }}
                style={{ padding: '2px 8px', backgroundColor: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: 4, cursor: 'pointer', fontSize: 11 }}>
                ↓
              </button>
            </>
          )
        ) : (
          <>
            <span style={{ color: '#cbd5e1' }}>—</span>
            {allowUpload && onUpload && (
              <label onClick={e => e.stopPropagation()} style={{ cursor: 'pointer' }}>
                <input type="file" accept=".xlsx,.xls" style={{ display: 'none' }}
                  onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ''; }}
                />
                <span style={{ padding: '2px 8px', backgroundColor: '#f0fdf4', color: '#15803d', border: '1px solid #86efac', borderRadius: 4, cursor: 'pointer', fontSize: 11 }}>
                  Загрузить
                </span>
              </label>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Хук: загрузка и группировка ничейных задач ─────────────────────────────

export interface UnassignedInbox {
  ready: TaskBrief[];
  gate: TaskBrief[];
  other: TaskBrief[];
  loading: boolean;
  reload: () => void;
  onRenameTask: (taskId: string, name: string) => Promise<void>;
  onRenameSlot: (taskId: string, slot: string, name: string) => Promise<void>;
  optimizingTaskId: string | null;
  setOptimizingTaskId: (id: string | null) => void;
  historyTaskId: string | null;
  setHistoryTaskId: (id: string | null) => void;
}

const isReady = (t: TaskBrief) =>
  t.status === 'completed' && ['estimated', 'optimized'].includes(t.estimation_status);
const isGate = (t: TaskBrief) =>
  t.status === 'completed' && t.estimation_status === 'unestimated' && ESTIMATE_TASK_TYPES.has(t.task_type as never);

export function useUnassignedInbox(reloadToken = 0): UnassignedInbox {
  const [tasks, setTasks] = useState<TaskBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);
  const [historyTaskId, setHistoryTaskId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const data = await getUnassignedTasks();
      setTasks(data.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)));
    } catch {
      /* оставляем прежний список; ошибки дашборда показывает сам System */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload, reloadToken]);

  const onRenameTask = useCallback(async (taskId: string, name: string) => {
    await updateTask(taskId, { name });
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, name } : t));
  }, []);

  const onRenameSlot = useCallback(async (taskId: string, slot: string, name: string) => {
    await renameSlotFile(taskId, slot, name);
    setTasks(prev => prev.map(t => t.id === taskId
      ? { ...t, slot_files: { ...(t.slot_files ?? {}), [slot]: name } }
      : t));
  }, []);

  const ready = tasks.filter(isReady);
  const gate = tasks.filter(isGate);
  const other = tasks.filter(t => !isReady(t) && !isGate(t) && !ACTIVE_STATUSES.has(t.status));

  return {
    ready, gate, other, loading, reload,
    onRenameTask, onRenameSlot,
    optimizingTaskId, setOptimizingTaskId,
    historyTaskId, setHistoryTaskId,
  };
}

// ── Карточка одной ничейной задачи ─────────────────────────────────────────

function UnassignedCard({ task, inbox }: { task: TaskBrief; inbox: UnassignedInbox }) {
  const navigate = useNavigate();
  const isEstimateType = ESTIMATE_TASK_TYPES.has(task.task_type as never);
  const slots = task.slot_files ?? {};
  const taskLabel = TASK_TYPE_LABELS[task.task_type] ?? task.task_type;
  const taskDisplayName = task.name || taskLabel;
  const showCost = !!task.cost && ['estimated', 'optimized'].includes(task.estimation_status);

  return (
    <div
      style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}
      onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)')}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
    >
      <div style={{ padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Контекст: у ничейной задачи проекта нет */}
          <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500, marginBottom: 3 }}>
            Без проекта · {taskLabel}
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
            <InlineEditName
              value={taskDisplayName}
              onSave={name => inbox.onRenameTask(task.id, name)}
            />
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
            {new Date(task.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </div>
          {showCost && (
            <div style={{ marginTop: 6 }}>
              <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>Сумма по смете: </span>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#1e293b' }}>{formatCost(task.cost as number)}</span>
            </div>
          )}
        </div>

        <div
          onClick={() => navigate(`/tasks/${task.id}/status`)}
          style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', flexShrink: 0, marginLeft: 12 }}
        >
          {isEstimateType && task.estimation_status === 'estimated' && (
            <button
              onClick={e => { e.stopPropagation(); inbox.setOptimizingTaskId(task.id); }}
              style={{ padding: '4px 12px', backgroundColor: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
            >
              Оптимизировать
            </button>
          )}
          {['estimated', 'optimized'].includes(task.estimation_status) && (
            <button
              onClick={e => { e.stopPropagation(); inbox.setHistoryTaskId(task.id); }}
              style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
            >
              История
            </button>
          )}
          {/* Единый статус: состояние стадии + тонкая бизнес-пометка (Фаза 6). */}
          <StageStateBadge status={task.status} estimation={task.estimation_status} />
        </div>
      </div>

      {isEstimateType && (
        <div style={{ borderTop: '1px solid #f1f5f9', padding: '10px 18px', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <SlotRow label="Исходный" fileName={task.source_file_name ?? null} slot="source"
            onDownload={() => downloadSlotFile(task.id, 'source')} />
          <SlotRow label="Смета" fileName={slots['estimate'] ?? null} slot="estimate"
            onDownload={() => downloadSlotFile(task.id, 'estimate')}
            onRename={name => inbox.onRenameSlot(task.id, 'estimate', name)} />
          <SlotRow label="Оптимизированная" fileName={slots['optimized'] ?? null} slot="optimized"
            onDownload={() => downloadSlotFile(task.id, 'optimized')}
            allowUpload
            onUpload={async file => { await uploadFileToSlot(task.id, 'optimized', file); inbox.reload(); }}
            onRename={name => inbox.onRenameSlot(task.id, 'optimized', name)} />
        </div>
      )}
    </div>
  );
}

// ── Группа входящего (список ничейных задач одного смысла) ──────────────────

export function UnassignedGroup({ tasks, inbox }: { tasks: TaskBrief[]; inbox: UnassignedInbox }) {
  if (tasks.length === 0) return null;
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {tasks.map(task => <UnassignedCard key={task.id} task={task} inbox={inbox} />)}
    </div>
  );
}

// ── Модалки оптимизации/истории (рендерятся один раз на странице) ───────────

export function UnassignedModals({ inbox }: { inbox: UnassignedInbox }) {
  return (
    <>
      {inbox.optimizingTaskId && (
        <OptimizeModal
          taskId={inbox.optimizingTaskId}
          onClose={() => { inbox.setOptimizingTaskId(null); inbox.reload(); }}
        />
      )}
      {inbox.historyTaskId && (
        <HistoryModal
          taskId={inbox.historyTaskId}
          onClose={() => { inbox.setHistoryTaskId(null); inbox.reload(); }}
        />
      )}
    </>
  );
}
