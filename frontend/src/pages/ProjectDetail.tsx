import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { ProjectDetail as IProjectDetail, TaskBrief, TASK_TYPE_LABELS, ESTIMATE_TASK_TYPES } from '../types';
import { getProject, updateProject, deleteProject, exportProject, downloadSlotFile, uploadFileToSlot } from '../api/projects';
import { useAuthStore } from '../stores/auth';
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

function formatCost(cost: number | null): string {
  if (cost === null || cost === undefined) return '—';
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(cost);
}

function SlotRow({
  label,
  fileName,
  onDownload,
  allowUpload = false,
  onUpload,
}: {
  label: string;
  fileName: string | null;
  onDownload: () => void;
  allowUpload?: boolean;
  onUpload?: (file: File) => Promise<void>;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#64748b' }}>
      <span style={{ fontWeight: 500, color: '#94a3b8', minWidth: '100px' }}>{label}:</span>
      {fileName ? (
        <>
          <span style={{ color: '#475569' }}>{fileName}</span>
          <button
            onClick={(e) => { e.stopPropagation(); onDownload(); }}
            style={{ padding: '2px 8px', backgroundColor: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}
          >
            ↓
          </button>
        </>
      ) : (
        <>
          <span style={{ color: '#cbd5e1' }}>—</span>
          {allowUpload && onUpload && (
            <label onClick={(e) => e.stopPropagation()} style={{ cursor: 'pointer' }}>
              <input
                type="file"
                accept=".xlsx,.xls"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f);
                  e.target.value = '';
                }}
              />
              <span style={{ padding: '2px 8px', backgroundColor: '#f0fdf4', color: '#15803d', border: '1px solid #86efac', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}>
                Загрузить
              </span>
            </label>
          )}
        </>
      )}
    </div>
  );
}

const ProjectDetailPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { isAdmin } = useAuthStore();

  const [project, setProject] = useState<IProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState<'xlsx' | 'pdf' | null>(null);
  const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);
  const [historyTaskId, setHistoryTaskId] = useState<string | null>(null);

  useEffect(() => {
    if (projectId) loadProject();
  }, [projectId]);

  async function loadProject() {
    setLoading(true);
    try {
      const data = await getProject(projectId!);
      setProject(data);
      setEditName(data.name);
      setEditDesc(data.description ?? '');
    } catch {
      setError('Проект не найден');
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editName.trim() || !projectId) return;
    setSaving(true);
    try {
      const updated = await updateProject(projectId, {
        name: editName.trim(),
        description: editDesc.trim() || undefined,
      });
      setProject((prev) => prev ? { ...prev, name: updated.name, description: updated.description } : prev);
      setEditing(false);
    } catch {
      setError('Ошибка при сохранении');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!projectId) return;
    if (!window.confirm('Удалить проект? Задачи останутся, но будут откреплены.')) return;
    try {
      await deleteProject(projectId);
      navigate('/projects');
    } catch {
      setError('Ошибка при удалении проекта');
    }
  }

  async function handleExport(format: 'xlsx' | 'pdf') {
    if (!projectId) return;
    setExporting(format);
    try {
      await exportProject(projectId, format);
    } catch {
      setError('Ошибка при экспорте проекта');
    } finally {
      setExporting(null);
    }
  }

  if (loading) {
    return <Layout><div style={{ textAlign: 'center', padding: '48px', color: '#94a3b8' }}>Загрузка...</div></Layout>;
  }

  if (error || !project) {
    return (
      <Layout>
        <div style={{ textAlign: 'center', padding: '48px', color: '#dc2626' }}>{error || 'Проект не найден'}</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div style={{ maxWidth: '900px', margin: '0 auto' }}>
        <button
          onClick={() => navigate('/projects')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#2563eb', fontSize: '14px', marginBottom: '16px', padding: 0 }}
        >
          ← Все проекты
        </button>

        <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '24px', marginBottom: '24px' }}>
          {editing ? (
            <form onSubmit={handleSave}>
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                required
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '18px', fontWeight: 600, marginBottom: '12px', boxSizing: 'border-box' }}
              />
              <textarea
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                rows={3}
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', marginBottom: '12px', resize: 'vertical', boxSizing: 'border-box' }}
              />
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" disabled={saving} style={{ padding: '8px 18px', backgroundColor: '#2563eb', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600, fontSize: '14px' }}>
                  {saving ? 'Сохранение...' : 'Сохранить'}
                </button>
                <button type="button" onClick={() => setEditing(false)} style={{ padding: '8px 18px', backgroundColor: 'transparent', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px' }}>
                  Отмена
                </button>
              </div>
            </form>
          ) : (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h1 style={{ margin: '0 0 8px', fontSize: '22px', fontWeight: 700, color: '#1e293b' }}>{project.name}</h1>
                  {project.description && <p style={{ margin: 0, fontSize: '14px', color: '#64748b' }}>{project.description}</p>}
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <button
                    onClick={() => handleExport('xlsx')}
                    disabled={exporting !== null}
                    style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: exporting !== null ? 'not-allowed' : 'pointer', fontSize: '13px', color: '#15803d', fontWeight: 500 }}
                  >
                    {exporting === 'xlsx' ? '...' : '↓ xlsx'}
                  </button>
                  <button
                    onClick={() => handleExport('pdf')}
                    disabled={exporting !== null}
                    style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: exporting !== null ? 'not-allowed' : 'pointer', fontSize: '13px', color: '#dc2626', fontWeight: 500 }}
                  >
                    {exporting === 'pdf' ? '...' : '↓ PDF'}
                  </button>
                  <button onClick={() => setEditing(true)} style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#64748b' }}>
                    Изменить
                  </button>
                  {isAdmin && (
                    <button onClick={handleDelete} style={{ padding: '7px 14px', backgroundColor: '#fee2e2', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#dc2626', fontWeight: 500 }}>
                      Удалить
                    </button>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '16px' }}>
                {project.unestimated > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.unestimated} не рассчитано
                  </span>
                )}
                {project.estimated > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.estimated} рассчитано · {formatCost(project.total_cost)}
                  </span>
                )}
                {project.optimized > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#f0fdf4', color: '#15803d', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.optimized} оптимизировано
                  </span>
                )}
                {project.other > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#64748b', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.other} прочих задач
                  </span>
                )}
              </div>
            </>
          )}
        </div>

        <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
          Задачи ({project.tasks.length})
        </h2>

        {project.tasks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
            Задач в проекте пока нет
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {project.tasks.map((task: TaskBrief) => {
              const estColors = ESTIMATION_COLORS[task.estimation_status] ?? ESTIMATION_COLORS.not_applicable;
              const isEstimateType = ESTIMATE_TASK_TYPES.has(task.task_type as any);
              const slots = task.slot_files ?? {};
              return (
                <div
                  key={task.id}
                  style={{
                    backgroundColor: '#fff',
                    border: '1px solid #e2e8f0',
                    borderRadius: '10px',
                    overflow: 'hidden',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)')}
                  onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'none')}
                >
                  {/* Main task row */}
                  <div
                    onClick={() => { if (task.id) navigate(`/tasks/${task.id}/status`); }}
                    style={{ padding: '14px 18px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                  >
                    <div>
                      <div style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>
                        {TASK_TYPE_LABELS[task.task_type as keyof typeof TASK_TYPE_LABELS] ?? task.task_type}
                      </div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                        {new Date(task.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {isEstimateType && task.estimation_status === 'estimated' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setOptimizingTaskId(task.id); }}
                          style={{ padding: '4px 12px', backgroundColor: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                        >
                          Оптимизировать
                        </button>
                      )}
                      {['estimated', 'optimized'].includes(task.estimation_status) && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setHistoryTaskId(task.id); }}
                          style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#475569', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                        >
                          История
                        </button>
                      )}
                      {task.cost !== null && (
                        <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>{formatCost(task.cost)}</span>
                      )}
                      {task.estimation_status !== 'not_applicable' && (
                        <span style={{ padding: '3px 10px', backgroundColor: estColors.bg, color: estColors.text, borderRadius: '12px', fontSize: '12px', fontWeight: 500 }}>
                          {ESTIMATION_LABELS[task.estimation_status]}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Slot files (only for ESTIMATE_TASK_TYPES) */}
                  {isEstimateType && (
                    <div style={{ borderTop: '1px solid #f1f5f9', padding: '10px 18px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                      {/* Source */}
                      <SlotRow
                        label="Исходный"
                        fileName={task.source_file_name ?? null}
                        onDownload={() => downloadSlotFile(task.id, 'source')}
                      />
                      {/* Estimate */}
                      <SlotRow
                        label="Смета"
                        fileName={slots['estimate'] ?? null}
                        onDownload={() => downloadSlotFile(task.id, 'estimate')}
                      />
                      {/* Optimized */}
                      <SlotRow
                        label="Оптимизированная"
                        fileName={slots['optimized'] ?? null}
                        onDownload={() => downloadSlotFile(task.id, 'optimized')}
                        allowUpload
                        onUpload={async (file) => {
                          await uploadFileToSlot(task.id, 'optimized', file);
                          loadProject();
                        }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      {optimizingTaskId && (
        <OptimizeModal
          taskId={optimizingTaskId}
          onClose={() => {
            setOptimizingTaskId(null);
            loadProject();
          }}
        />
      )}
      {historyTaskId && (
        <HistoryModal
          taskId={historyTaskId}
          onClose={() => {
            setHistoryTaskId(null);
            loadProject();
          }}
        />
      )}
    </Layout>
  );
};

export default ProjectDetailPage;
