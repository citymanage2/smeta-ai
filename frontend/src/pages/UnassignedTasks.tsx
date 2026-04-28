import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Pencil, Check, X } from 'lucide-react';
import Layout from '../components/Layout';
import { TaskBrief, TASK_TYPE_LABELS, ESTIMATE_TASK_TYPES } from '../types';
import { getUnassignedTasks, downloadSlotFile, uploadFileToSlot } from '../api/projects';
import { updateTask, renameSlotFile } from '../api/tasks';
import OptimizeModal from '../components/OptimizeModal';
import HistoryModal from '../components/HistoryModal';

const ESTIMATION_LABELS: Record<string, string> = {
  unestimated: 'Не рассчитана',
  estimated: 'Рассчитана',
  optimizing: 'Оптимизируется',
  optimized: 'Оптимизирована',
  not_applicable: '—',
};

const ESTIMATION_COLORS: Record<string, { bg: string; text: string }> = {
  unestimated: { bg: '#fef2f2', text: '#dc2626' },
  estimated: { bg: '#fef9c3', text: '#854d0e' },
  optimizing: { bg: '#eff6ff', text: '#2563eb' },
  optimized: { bg: '#f0fdf4', text: '#15803d' },
  not_applicable: { bg: '#f8fafc', text: '#94a3b8' },
};

const HIDDEN_TASK_TYPES = new Set(['CHECK_LIST_COMPLETENESS', 'CHECK_PROJECT_COMPLETENESS']);

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

const UnassignedTasks: React.FC = () => {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);
  const [historyTaskId, setHistoryTaskId] = useState<string | null>(null);

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const data = await getUnassignedTasks();
      setTasks(data.filter(t => !HIDDEN_TASK_TYPES.has(t.task_type)));
    } catch {
      setError('Не удалось загрузить задачи');
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveTaskName(taskId: string, name: string) {
    await updateTask(taskId, { name });
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, name } : t));
  }

  async function handleRenameSlotFile(taskId: string, slot: string, name: string) {
    await renameSlotFile(taskId, slot, name);
    setTasks(prev => prev.map(t => t.id === taskId
      ? { ...t, slot_files: { ...(t.slot_files ?? {}), [slot]: name } }
      : t));
  }

  if (loading) {
    return <Layout><div style={{ textAlign: 'center', padding: 48, color: '#94a3b8' }}>Загрузка...</div></Layout>;
  }

  return (
    <Layout>
      <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <button
          onClick={() => navigate('/projects')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#2563eb', fontSize: 14, marginBottom: 16, padding: 0 }}
        >
          ← Все проекты
        </button>

        <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 24, marginBottom: 24 }}>
          <h1 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 700, color: '#1e293b' }}>Без проекта</h1>
          <p style={{ margin: 0, fontSize: 13, color: '#94a3b8' }}>Задачи, не привязанные ни к одному проекту</p>
        </div>

        {error && (
          <div style={{ padding: 12, backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: 8, marginBottom: 16 }}>
            {error}
          </div>
        )}

        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#1e293b', marginBottom: 12 }}>
          Задачи ({tasks.length})
        </h2>

        {tasks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 32, backgroundColor: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: 14 }}>
            Задач без проекта нет
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {tasks.map(task => {
              const estColors = ESTIMATION_COLORS[task.estimation_status] ?? ESTIMATION_COLORS.not_applicable;
              const isEstimateType = ESTIMATE_TASK_TYPES.has(task.task_type);
              const slots = task.slot_files ?? {};
              const taskLabel = TASK_TYPE_LABELS[task.task_type] ?? task.task_type;
              const taskDisplayName = task.name || taskLabel;
              const showCost = !!task.cost && ['estimated', 'optimized'].includes(task.estimation_status);

              return (
                <div
                  key={task.id}
                  style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}
                  onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)')}
                  onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                >
                  <div style={{ padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
                        <InlineEditName
                          value={taskDisplayName}
                          onSave={name => handleSaveTaskName(task.id, name)}
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
                          onClick={e => { e.stopPropagation(); setOptimizingTaskId(task.id); }}
                          style={{ padding: '4px 12px', backgroundColor: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                        >
                          Оптимизировать
                        </button>
                      )}
                      {['estimated', 'optimized'].includes(task.estimation_status) && (
                        <button
                          onClick={e => { e.stopPropagation(); setHistoryTaskId(task.id); }}
                          style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                        >
                          История
                        </button>
                      )}
                      {task.estimation_status !== 'not_applicable' && (
                        <span style={{ padding: '3px 10px', backgroundColor: estColors.bg, color: estColors.text, borderRadius: 12, fontSize: 12, fontWeight: 500 }}>
                          {ESTIMATION_LABELS[task.estimation_status]}
                        </span>
                      )}
                    </div>
                  </div>

                  {isEstimateType && (
                    <div style={{ borderTop: '1px solid #f1f5f9', padding: '10px 18px', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                      <SlotRow label="Исходный" fileName={task.source_file_name ?? null} slot="source"
                        onDownload={() => downloadSlotFile(task.id, 'source')} />
                      <SlotRow label="Смета" fileName={slots['estimate'] ?? null} slot="estimate"
                        onDownload={() => downloadSlotFile(task.id, 'estimate')}
                        onRename={name => handleRenameSlotFile(task.id, 'estimate', name)} />
                      <SlotRow label="Оптимизированная" fileName={slots['optimized'] ?? null} slot="optimized"
                        onDownload={() => downloadSlotFile(task.id, 'optimized')}
                        allowUpload
                        onUpload={async file => { await uploadFileToSlot(task.id, 'optimized', file); load(); }}
                        onRename={name => handleRenameSlotFile(task.id, 'optimized', name)} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {optimizingTaskId && (
        <OptimizeModal taskId={optimizingTaskId} onClose={() => { setOptimizingTaskId(null); load(); }} />
      )}
      {historyTaskId && (
        <HistoryModal taskId={historyTaskId} onClose={() => { setHistoryTaskId(null); load(); }} />
      )}
    </Layout>
  );
};

export default UnassignedTasks;
