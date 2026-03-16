import React, { useState, useEffect, useCallback, useRef } from 'react';
import Layout from '../components/Layout';
import { AdminTask, TaskStatus, TaskType, TASK_TYPE_LABELS, STATUS_LABELS, AdminTasksParams } from '../types';
import { getAdminTasks, deleteTask, uploadPrices } from '../api/admin';
import { downloadResult } from '../api/tasks';

const STATUS_COLORS: Record<TaskStatus, { bg: string; text: string; border: string }> = {
  pending: { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  processing: { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  completed: { bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  failed: { bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
};

const TASK_TYPES: TaskType[] = [
  'LIST_FROM_TZ', 'LIST_FROM_TZ_PROJECT', 'SMETA_FROM_GRAND_PROJECT',
  'SMETA_FROM_PROJECT', 'SMETA_FROM_EDC_PROJECT', 'SMETA_FROM_LIST',
  'SCAN_TO_EXCEL', 'COMPARE_PROJECT_SMETA',
];

const STATUSES: TaskStatus[] = ['pending', 'processing', 'completed', 'failed'];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

const PAGE_SIZE = 20;

const AdminPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'tasks' | 'prices'>('tasks');

  // Tasks state
  const [tasks, setTasks] = useState<AdminTask[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [taskError, setTaskError] = useState('');

  // Filters
  const [filterStatus, setFilterStatus] = useState<TaskStatus | ''>('');
  const [filterType, setFilterType] = useState<TaskType | ''>('');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');

  // Prices state
  const priceInputRef = useRef<HTMLInputElement>(null);
  const [priceFile, setPriceFile] = useState<File | null>(null);
  const [priceUploading, setPriceUploading] = useState(false);
  const [priceMessage, setPriceMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [priceDragging, setPriceDragging] = useState(false);

  const [downloadingFile, setDownloadingFile] = useState<number | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setTaskError('');
    try {
      const params: AdminTasksParams = {
        page,
        page_size: PAGE_SIZE,
      };
      if (filterStatus) params.status = filterStatus;
      if (filterType) params.task_type = filterType;
      if (filterDateFrom) params.date_from = filterDateFrom;
      if (filterDateTo) params.date_to = filterDateTo;

      const data = await getAdminTasks(params);
      setTasks(data.items);
      setTotal(data.total);
    } catch {
      setTaskError('Не удалось загрузить задачи.');
    } finally {
      setLoading(false);
    }
  }, [page, filterStatus, filterType, filterDateFrom, filterDateTo]);

  useEffect(() => {
    if (activeTab === 'tasks') fetchTasks();
  }, [activeTab, fetchTasks]);

  const handleDeleteTask = async (taskId: string) => {
    setDeleteLoading(true);
    try {
      await deleteTask(taskId);
      setDeleteConfirm(null);
      fetchTasks();
    } catch {
      setTaskError('Не удалось удалить задачу.');
    } finally {
      setDeleteLoading(false);
    }
  };

  const handlePriceUpload = async () => {
    if (!priceFile) return;
    setPriceUploading(true);
    setPriceMessage(null);
    try {
      const result = await uploadPrices(priceFile);
      setPriceMessage({ type: 'success', text: result.message || 'Прайс-лист успешно загружен.' });
      setPriceFile(null);
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { detail?: string } } };
      setPriceMessage({ type: 'error', text: axiosError.response?.data?.detail ?? 'Ошибка при загрузке прайс-листа.' });
    } finally {
      setPriceUploading(false);
    }
  };

  const handlePriceDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setPriceDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
      setPriceFile(file);
    }
  };

  const handleDownload = async (fileId: number, fileName: string) => {
    setDownloadingFile(fileId);
    try {
      await downloadResult(fileId, fileName);
    } catch {
      setTaskError('Ошибка при скачивании файла.');
    } finally {
      setDownloadingFile(null);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px',
    fontSize: '13px',
    border: '1.5px solid #e2e8f0',
    borderRadius: '7px',
    outline: 'none',
    color: '#1e293b',
    backgroundColor: '#ffffff',
  };

  return (
    <Layout>
      <div>
        {/* Page title */}
        <div style={{ marginBottom: '24px' }}>
          <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
            Панель администратора
          </h2>
        </div>

        {/* Tabs */}
        <div
          style={{
            display: 'flex',
            gap: '4px',
            borderBottom: '2px solid #e2e8f0',
            marginBottom: '28px',
          }}
        >
          {(['tasks', 'prices'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: '10px 20px',
                fontSize: '15px',
                fontWeight: 600,
                backgroundColor: 'transparent',
                color: activeTab === tab ? '#2563eb' : '#64748b',
                border: 'none',
                borderBottom: activeTab === tab ? '2px solid #2563eb' : '2px solid transparent',
                cursor: 'pointer',
                marginBottom: '-2px',
                transition: 'all 0.15s',
              }}
            >
              {tab === 'tasks' ? 'Задачи' : 'Прайс-листы'}
            </button>
          ))}
        </div>

        {/* ---- TASKS TAB ---- */}
        {activeTab === 'tasks' && (
          <div>
            {/* Filters */}
            <div
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '10px',
                padding: '16px 20px',
                marginBottom: '16px',
                display: 'flex',
                gap: '12px',
                flexWrap: 'wrap',
                alignItems: 'flex-end',
              }}
            >
              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '4px' }}>Статус</div>
                <select
                  value={filterStatus}
                  onChange={(e) => { setFilterStatus(e.target.value as TaskStatus | ''); setPage(1); }}
                  style={inputStyle}
                >
                  <option value="">Все статусы</option>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                  ))}
                </select>
              </div>

              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '4px' }}>Тип задачи</div>
                <select
                  value={filterType}
                  onChange={(e) => { setFilterType(e.target.value as TaskType | ''); setPage(1); }}
                  style={inputStyle}
                >
                  <option value="">Все типы</option>
                  {TASK_TYPES.map((t) => (
                    <option key={t} value={t}>{TASK_TYPE_LABELS[t]}</option>
                  ))}
                </select>
              </div>

              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '4px' }}>Дата с</div>
                <input
                  type="date"
                  value={filterDateFrom}
                  onChange={(e) => { setFilterDateFrom(e.target.value); setPage(1); }}
                  style={inputStyle}
                />
              </div>

              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '4px' }}>Дата по</div>
                <input
                  type="date"
                  value={filterDateTo}
                  onChange={(e) => { setFilterDateTo(e.target.value); setPage(1); }}
                  style={inputStyle}
                />
              </div>

              <button
                onClick={() => {
                  setFilterStatus('');
                  setFilterType('');
                  setFilterDateFrom('');
                  setFilterDateTo('');
                  setPage(1);
                }}
                style={{
                  padding: '8px 14px',
                  backgroundColor: '#f1f5f9',
                  color: '#475569',
                  border: '1px solid #e2e8f0',
                  borderRadius: '7px',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: 500,
                }}
              >
                Сбросить
              </button>
            </div>

            {/* Error */}
            {taskError && (
              <div style={{ padding: '10px 14px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', marginBottom: '12px', fontSize: '14px', color: '#dc2626' }}>
                {taskError}
              </div>
            )}

            {/* Table */}
            <div style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px', overflow: 'hidden' }}>
              {loading ? (
                <div style={{ padding: '48px', textAlign: 'center', color: '#94a3b8' }}>Загрузка...</div>
              ) : tasks.length === 0 ? (
                <div style={{ padding: '48px', textAlign: 'center', color: '#94a3b8' }}>Задачи не найдены</div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                    <thead>
                      <tr style={{ backgroundColor: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                        {['ID', 'Тип', 'Статус', 'Дата создания', 'Действия'].map((col) => (
                          <th
                            key={col}
                            style={{
                              padding: '12px 16px',
                              textAlign: 'left',
                              fontSize: '12px',
                              fontWeight: 700,
                              color: '#64748b',
                              textTransform: 'uppercase',
                              letterSpacing: '0.5px',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tasks.map((task) => {
                        const isExpanded = expandedTask === task.id;
                        const s = STATUS_COLORS[task.status];
                        return (
                          <React.Fragment key={task.id}>
                            <tr
                              style={{
                                borderBottom: '1px solid #e2e8f0',
                                backgroundColor: isExpanded ? '#f8fafc' : '#ffffff',
                                cursor: 'pointer',
                                transition: 'background-color 0.1s',
                              }}
                              onClick={() => setExpandedTask(isExpanded ? null : task.id)}
                            >
                              <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontSize: '12px', color: '#475569', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {task.id}
                              </td>
                              <td style={{ padding: '12px 16px', color: '#1e293b' }}>
                                {TASK_TYPE_LABELS[task.task_type]}
                              </td>
                              <td style={{ padding: '12px 16px' }}>
                                <span style={{
                                  display: 'inline-block',
                                  padding: '3px 10px',
                                  backgroundColor: s.bg,
                                  color: s.text,
                                  border: `1px solid ${s.border}`,
                                  borderRadius: '12px',
                                  fontSize: '12px',
                                  fontWeight: 600,
                                }}>
                                  {STATUS_LABELS[task.status]}
                                </span>
                              </td>
                              <td style={{ padding: '12px 16px', color: '#475569', whiteSpace: 'nowrap' }}>
                                {formatDate(task.created_at)}
                              </td>
                              <td style={{ padding: '12px 16px' }}>
                                <div style={{ display: 'flex', gap: '8px' }} onClick={(e) => e.stopPropagation()}>
                                  <button
                                    onClick={() => setDeleteConfirm(task.id)}
                                    style={{
                                      padding: '5px 12px',
                                      backgroundColor: '#fee2e2',
                                      color: '#dc2626',
                                      border: 'none',
                                      borderRadius: '6px',
                                      cursor: 'pointer',
                                      fontSize: '13px',
                                      fontWeight: 600,
                                    }}
                                  >
                                    Удалить
                                  </button>
                                </div>
                              </td>
                            </tr>

                            {/* Expanded row */}
                            {isExpanded && (
                              <tr style={{ backgroundColor: '#f8fafc' }}>
                                <td colSpan={5} style={{ padding: '0 16px 20px' }}>
                                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '12px' }}>
                                    {/* Input files */}
                                    <div>
                                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#374151', marginBottom: '8px' }}>
                                        Входные файлы ({task.input_files?.length || 0})
                                      </div>
                                      {task.input_files?.length > 0 ? (
                                        <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                          {task.input_files.map((f, i) => (
                                            <li key={i} style={{ fontSize: '13px', color: '#475569', padding: '5px 10px', backgroundColor: '#ffffff', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                                              {f.name} <span style={{ color: '#94a3b8' }}>({formatSize(f.size_bytes)})</span>
                                            </li>
                                          ))}
                                        </ul>
                                      ) : (
                                        <p style={{ fontSize: '13px', color: '#94a3b8', margin: 0 }}>Нет файлов</p>
                                      )}
                                    </div>

                                    {/* Result files */}
                                    <div>
                                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#374151', marginBottom: '8px' }}>
                                        Результаты ({task.results?.length || 0})
                                      </div>
                                      {task.results && task.results.length > 0 ? (
                                        <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                          {task.results.map((r) => (
                                            <li key={r.file_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 10px', backgroundColor: '#f0fdf4', borderRadius: '6px', border: '1px solid #86efac' }}>
                                              <span style={{ fontSize: '13px', color: '#15803d' }}>{r.file_name}</span>
                                              <button
                                                onClick={() => handleDownload(r.file_id, r.file_name)}
                                                disabled={downloadingFile === r.file_id}
                                                style={{ padding: '3px 10px', backgroundColor: '#16a34a', color: '#fff', border: 'none', borderRadius: '5px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                                              >
                                                {downloadingFile === r.file_id ? '...' : 'Скачать'}
                                              </button>
                                            </li>
                                          ))}
                                        </ul>
                                      ) : (
                                        <p style={{ fontSize: '13px', color: '#94a3b8', margin: 0 }}>Нет результатов</p>
                                      )}
                                    </div>
                                  </div>

                                  {/* Chat history */}
                                  {task.chat_history?.length > 0 && (
                                    <div style={{ marginTop: '16px' }}>
                                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#374151', marginBottom: '8px' }}>
                                        История чата ({task.chat_history.length})
                                      </div>
                                      <div style={{ maxHeight: '240px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                        {task.chat_history.map((msg, i) => (
                                          <div
                                            key={i}
                                            style={{
                                              padding: '8px 12px',
                                              backgroundColor: msg.role === 'user' ? '#eff6ff' : '#ffffff',
                                              border: `1px solid ${msg.role === 'user' ? '#bfdbfe' : '#e2e8f0'}`,
                                              borderRadius: '8px',
                                            }}
                                          >
                                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                              <span style={{ fontSize: '12px', fontWeight: 700, color: msg.role === 'user' ? '#1d4ed8' : '#374151' }}>
                                                {msg.role === 'user' ? 'Пользователь' : 'Ассистент'}
                                              </span>
                                              <span style={{ fontSize: '11px', color: '#94a3b8' }}>{formatDate(msg.timestamp)}</span>
                                            </div>
                                            <p style={{ margin: 0, fontSize: '13px', color: '#1e293b', lineHeight: '1.5' }}>{msg.content}</p>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', marginTop: '20px' }}>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{
                    padding: '7px 14px',
                    backgroundColor: page === 1 ? '#f1f5f9' : '#ffffff',
                    color: page === 1 ? '#94a3b8' : '#374151',
                    border: '1px solid #e2e8f0',
                    borderRadius: '7px',
                    cursor: page === 1 ? 'not-allowed' : 'pointer',
                    fontSize: '14px',
                  }}
                >
                  ← Назад
                </button>
                <span style={{ fontSize: '14px', color: '#475569' }}>
                  Страница {page} из {totalPages} · Всего: {total}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  style={{
                    padding: '7px 14px',
                    backgroundColor: page === totalPages ? '#f1f5f9' : '#ffffff',
                    color: page === totalPages ? '#94a3b8' : '#374151',
                    border: '1px solid #e2e8f0',
                    borderRadius: '7px',
                    cursor: page === totalPages ? 'not-allowed' : 'pointer',
                    fontSize: '14px',
                  }}
                >
                  Вперёд →
                </button>
              </div>
            )}
          </div>
        )}

        {/* ---- PRICES TAB ---- */}
        {activeTab === 'prices' && (
          <div style={{ maxWidth: '560px' }}>
            <div
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '12px',
                padding: '32px',
                boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
              }}
            >
              <h3 style={{ margin: '0 0 8px', fontSize: '18px', fontWeight: 700, color: '#0f172a' }}>
                Загрузка прайс-листа
              </h3>
              <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#64748b' }}>
                Загрузите файл Excel (.xlsx) с актуальными ценами
              </p>

              {/* Drop zone */}
              <div
                onDrop={handlePriceDrop}
                onDragOver={(e) => { e.preventDefault(); setPriceDragging(true); }}
                onDragLeave={() => setPriceDragging(false)}
                onClick={() => priceInputRef.current?.click()}
                style={{
                  border: `2px dashed ${priceDragging ? '#2563eb' : '#cbd5e1'}`,
                  borderRadius: '10px',
                  padding: '32px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  backgroundColor: priceDragging ? '#eff6ff' : '#f8fafc',
                  marginBottom: '16px',
                  transition: 'all 0.15s',
                }}
              >
                <input
                  ref={priceInputRef}
                  type="file"
                  accept=".xlsx,.xls"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) setPriceFile(f);
                    e.target.value = '';
                  }}
                />
                <div style={{ fontSize: '32px', marginBottom: '8px' }}>📋</div>
                {priceFile ? (
                  <div>
                    <p style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#334155' }}>
                      {priceFile.name}
                    </p>
                    <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#94a3b8' }}>
                      Нажмите для замены файла
                    </p>
                  </div>
                ) : (
                  <div>
                    <p style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#334155' }}>
                      Перетащите файл или нажмите для выбора
                    </p>
                    <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#94a3b8' }}>
                      Поддерживаемые форматы: .xlsx, .xls
                    </p>
                  </div>
                )}
              </div>

              {/* Status messages */}
              {priceMessage && (
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: priceMessage.type === 'success' ? '#f0fdf4' : '#fef2f2',
                    border: `1px solid ${priceMessage.type === 'success' ? '#86efac' : '#fca5a5'}`,
                    borderRadius: '8px',
                    marginBottom: '16px',
                    fontSize: '14px',
                    color: priceMessage.type === 'success' ? '#15803d' : '#dc2626',
                  }}
                >
                  {priceMessage.text}
                </div>
              )}

              <button
                onClick={handlePriceUpload}
                disabled={!priceFile || priceUploading}
                style={{
                  width: '100%',
                  padding: '12px',
                  fontSize: '15px',
                  fontWeight: 600,
                  backgroundColor: !priceFile || priceUploading ? '#93c5fd' : '#2563eb',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: !priceFile || priceUploading ? 'not-allowed' : 'pointer',
                  transition: 'background-color 0.15s',
                }}
              >
                {priceUploading ? 'Загрузка...' : 'Загрузить прайс-лист'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setDeleteConfirm(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '12px',
              padding: '28px 32px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
              maxWidth: '400px',
              width: '90%',
            }}
          >
            <h3 style={{ margin: '0 0 12px', fontSize: '18px', fontWeight: 700, color: '#0f172a' }}>
              Удалить задачу?
            </h3>
            <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#64748b' }}>
              Это действие нельзя отменить. Задача и все связанные файлы будут удалены.
            </p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setDeleteConfirm(null)}
                style={{
                  padding: '9px 20px',
                  backgroundColor: '#f1f5f9',
                  color: '#475569',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontWeight: 600,
                }}
              >
                Отмена
              </button>
              <button
                onClick={() => handleDeleteTask(deleteConfirm)}
                disabled={deleteLoading}
                style={{
                  padding: '9px 20px',
                  backgroundColor: deleteLoading ? '#fca5a5' : '#dc2626',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: deleteLoading ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 600,
                }}
              >
                {deleteLoading ? 'Удаление...' : 'Удалить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

export default AdminPage;
