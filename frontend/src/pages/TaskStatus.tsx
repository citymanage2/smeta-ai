import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Check, X } from 'lucide-react';
import Layout from '../components/Layout';
import { BatchProgressBar } from '../components/BatchProgressBar';
import { TaskStatus as TStatus, TaskResult, TASK_TYPE_LABELS, STATUS_LABELS, ProjectCard } from '../types';
import {
  getTaskStatus,
  getTaskResults,
  sendMessage,
  cancelTask,
  downloadResult,
  updateTask,
  resumeTask,
  checkCompleteness,
  checkProjectCompleteness,
  getRelatedChecks,
  TaskStatusResponse,
  ChatMessage,
} from '../api/tasks';
import {
  linkTaskToProject,
  listProjects,
} from '../api/projects';

const STATUS_COLORS: Record<TStatus, { bg: string; text: string; border: string }> = {
  pending: { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  processing: { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  completed: { bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  failed: { bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
  cancelled: { bg: '#f8fafc', text: '#64748b', border: '#cbd5e1' },
};

function Spinner() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: '16px',
        height: '16px',
        border: '2px solid #93c5fd',
        borderTopColor: '#2563eb',
        borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
        verticalAlign: 'middle',
        marginRight: '8px',
      }}
    />
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

const TaskStatusPage: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();

  const [task, setTask] = useState<TaskStatusResponse | null>(null);
  const [results, setResults] = useState<TaskResult[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [downloading, setDownloading] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [progressLog, setProgressLog] = useState<string[]>([]);
  const [estimationStatus, setEstimationStatus] = useState<string>('not_applicable');
  const [taskCost, setTaskCost] = useState<number | null>(null);
  const [taskProjectId, setTaskProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [attachingProject, setAttachingProject] = useState(false);
  const [selectedAttachProjectId, setSelectedAttachProjectId] = useState('');
  const [taskName, setTaskName] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [editNameDraft, setEditNameDraft] = useState('');
  const [editNameError, setEditNameError] = useState('');
  const nameInputRef = useRef<HTMLInputElement>(null);

  // Resume state
  const [resuming, setResuming] = useState(false);

  // Check completeness state (LIST_FROM_GRAND)
  const [checkTaskId, setCheckTaskId] = useState<string | null>(null);
  const [checkTask, setCheckTask] = useState<TaskStatusResponse | null>(null);
  const [checkResults, setCheckResults] = useState<TaskResult[]>([]);
  const [checkStarting, setCheckStarting] = useState(false);
  const [checkCancelling, setCheckCancelling] = useState(false);
  const [checkResuming, setCheckResuming] = useState(false);
  const [checkProgressLog, setCheckProgressLog] = useState<string[]>([]);
  const [checkElapsed, setCheckElapsed] = useState(0);
  const checkPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkStartTimeRef = useRef<number | null>(null);
  const checkFetchErrorCount = useRef(0);

  // Check project completeness state (LIST_FROM_PROJECT)
  const [checkProjectTaskId, setCheckProjectTaskId] = useState<string | null>(null);
  const [checkProjectTask, setCheckProjectTask] = useState<TaskStatusResponse | null>(null);
  const [checkProjectResults, setCheckProjectResults] = useState<TaskResult[]>([]);
  const [checkProjectStarting, setCheckProjectStarting] = useState(false);
  const [checkProjectCancelling, setCheckProjectCancelling] = useState(false);
  const [checkProjectResuming, setCheckProjectResuming] = useState(false);
  const [checkProjectProgressLog, setCheckProjectProgressLog] = useState<string[]>([]);
  const [checkProjectElapsed, setCheckProjectElapsed] = useState(0);
  const checkProjectPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkProjectTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkProjectStartTimeRef = useRef<number | null>(null);
  const checkProjectFetchErrorCount = useRef(0);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number | null>(null);

  useEffect(() => {
    if (!taskId || taskId === 'undefined') {
      navigate('/task/create');
    }
  }, [taskId, navigate]);

  const stopTimers = useCallback(() => {
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const stopCheckPolling = useCallback(() => {
    if (checkPollingRef.current) { clearInterval(checkPollingRef.current); checkPollingRef.current = null; }
    if (checkTimerRef.current) { clearInterval(checkTimerRef.current); checkTimerRef.current = null; }
  }, []);

  const startCheckTimer = useCallback(() => {
    if (checkTimerRef.current) return;
    checkStartTimeRef.current = Date.now();
    checkTimerRef.current = setInterval(() => {
      if (checkStartTimeRef.current) {
        setCheckElapsed(Math.floor((Date.now() - checkStartTimeRef.current) / 1000));
      }
    }, 1000);
  }, []);

  const fetchCheckStatus = useCallback(async (cid: string) => {
    try {
      const data = await getTaskStatus(cid);
      checkFetchErrorCount.current = 0;
      setCheckTask(data);
      if (data.status === 'pending' || data.status === 'processing') startCheckTimer();
      if (data.progress_message) {
        setCheckProgressLog((prev) => {
          const last = prev[prev.length - 1];
          return last === data.progress_message ? prev : [...prev, data.progress_message!];
        });
      }
      if (data.status === 'completed') {
        const res = await getTaskResults(cid);
        setCheckResults(res);
        stopCheckPolling();
      } else if (data.status === 'failed' || data.status === 'cancelled') {
        const res = await getTaskResults(cid);
        setCheckResults(res);
        stopCheckPolling();
      }
    } catch {
      checkFetchErrorCount.current += 1;
      // Stop polling only after 5 consecutive failures (~15 seconds of no response)
      if (checkFetchErrorCount.current >= 5) {
        stopCheckPolling();
        setError('Проверка прервана: потеряно соединение с сервером. Попробуйте ещё раз.');
      }
    }
  }, [stopCheckPolling, startCheckTimer]);

  const handleCheckCompleteness = async () => {
    if (!taskId || checkStarting) return;
    setCheckStarting(true);
    try {
      const res = await checkCompleteness(taskId);
      const cid = res.task_id;
      setCheckTaskId(cid);
      setCheckTask(null);
      setCheckResults([]);
      fetchCheckStatus(cid);
      checkPollingRef.current = setInterval(() => fetchCheckStatus(cid), 3000);
    } catch {
      setError('Не удалось запустить проверку полноты.');
    } finally {
      setCheckStarting(false);
    }
  };

  const stopCheckProjectPolling = useCallback(() => {
    if (checkProjectPollingRef.current) { clearInterval(checkProjectPollingRef.current); checkProjectPollingRef.current = null; }
    if (checkProjectTimerRef.current) { clearInterval(checkProjectTimerRef.current); checkProjectTimerRef.current = null; }
  }, []);

  const startCheckProjectTimer = useCallback(() => {
    if (checkProjectTimerRef.current) return;
    checkProjectStartTimeRef.current = Date.now();
    checkProjectTimerRef.current = setInterval(() => {
      if (checkProjectStartTimeRef.current) {
        setCheckProjectElapsed(Math.floor((Date.now() - checkProjectStartTimeRef.current) / 1000));
      }
    }, 1000);
  }, []);

  const fetchCheckProjectStatus = useCallback(async (cid: string) => {
    try {
      const data = await getTaskStatus(cid);
      checkProjectFetchErrorCount.current = 0;
      setCheckProjectTask(data);
      if (data.status === 'pending' || data.status === 'processing') startCheckProjectTimer();
      if (data.progress_message) {
        setCheckProjectProgressLog((prev) => {
          const last = prev[prev.length - 1];
          return last === data.progress_message ? prev : [...prev, data.progress_message!];
        });
      }
      if (data.status === 'completed') {
        const res = await getTaskResults(cid);
        setCheckProjectResults(res);
        stopCheckProjectPolling();
      } else if (data.status === 'failed' || data.status === 'cancelled') {
        const res = await getTaskResults(cid);
        setCheckProjectResults(res);
        stopCheckProjectPolling();
      }
    } catch {
      checkProjectFetchErrorCount.current += 1;
      // Stop polling only after 5 consecutive failures (~15 seconds of no response)
      if (checkProjectFetchErrorCount.current >= 5) {
        stopCheckProjectPolling();
        setError('Проверка прервана: потеряно соединение с сервером. Попробуйте ещё раз.');
      }
    }
  }, [stopCheckProjectPolling, startCheckProjectTimer]);

  const handleCheckProjectCompleteness = async () => {
    if (!taskId || checkProjectStarting) return;
    setCheckProjectStarting(true);
    try {
      const res = await checkProjectCompleteness(taskId);
      const cid = res.task_id;
      setCheckProjectTaskId(cid);
      setCheckProjectTask(null);
      setCheckProjectResults([]);
      fetchCheckProjectStatus(cid);
      checkProjectPollingRef.current = setInterval(() => fetchCheckProjectStatus(cid), 3000);
    } catch {
      setError('Не удалось запустить проверку полноты.');
    } finally {
      setCheckProjectStarting(false);
    }
  };

  const handleCheckCancel = async () => {
    if (!checkTaskId || checkCancelling) return;
    setCheckCancelling(true);
    try {
      await cancelTask(checkTaskId);
      setCheckTask((prev) => prev ? { ...prev, status: 'cancelled' } : prev);
      stopCheckPolling();
    } catch {
      setError('Не удалось остановить проверку.');
    } finally {
      setCheckCancelling(false);
    }
  };

  const handleCheckResume = async () => {
    if (!checkTaskId || checkResuming) return;
    setCheckResuming(true);
    try {
      await resumeTask(checkTaskId);
      setCheckTask((prev) => prev ? { ...prev, status: 'pending', error_message: undefined } : prev);
      setCheckProgressLog([]);
      setCheckElapsed(0);
      checkStartTimeRef.current = null;
      checkFetchErrorCount.current = 0;
      fetchCheckStatus(checkTaskId);
      checkPollingRef.current = setInterval(() => fetchCheckStatus(checkTaskId), 3000);
    } catch {
      setError('Не удалось возобновить проверку.');
    } finally {
      setCheckResuming(false);
    }
  };

  const handleCheckProjectCancel = async () => {
    if (!checkProjectTaskId || checkProjectCancelling) return;
    setCheckProjectCancelling(true);
    try {
      await cancelTask(checkProjectTaskId);
      setCheckProjectTask((prev) => prev ? { ...prev, status: 'cancelled' } : prev);
      stopCheckProjectPolling();
    } catch {
      setError('Не удалось остановить проверку.');
    } finally {
      setCheckProjectCancelling(false);
    }
  };

  const handleCheckProjectResume = async () => {
    if (!checkProjectTaskId || checkProjectResuming) return;
    setCheckProjectResuming(true);
    try {
      await resumeTask(checkProjectTaskId);
      setCheckProjectTask((prev) => prev ? { ...prev, status: 'pending', error_message: undefined } : prev);
      setCheckProjectProgressLog([]);
      setCheckProjectElapsed(0);
      checkProjectStartTimeRef.current = null;
      checkProjectFetchErrorCount.current = 0;
      fetchCheckProjectStatus(checkProjectTaskId);
      checkProjectPollingRef.current = setInterval(() => fetchCheckProjectStatus(checkProjectTaskId), 3000);
    } catch {
      setError('Не удалось возобновить проверку.');
    } finally {
      setCheckProjectResuming(false);
    }
  };

  const handleResume = async () => {
    if (!taskId || resuming) return;
    setResuming(true);
    try {
      await resumeTask(taskId);
      setTask((prev) => prev ? { ...prev, status: 'pending', error_message: undefined } : prev);
      setProgressLog([]);
      setElapsedSeconds(0);
      startTimeRef.current = null;
      if (!pollingRef.current) {
        pollingRef.current = setInterval(fetchStatus, 3000);
      }
      fetchStatus();
    } catch {
      setError('Не удалось возобновить задачу.');
    } finally {
      setResuming(false);
    }
  };

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);

  async function handleAttachProject() {
    if (!taskId || !selectedAttachProjectId) return;
    try {
      await linkTaskToProject(taskId, selectedAttachProjectId);
      setTaskProjectId(selectedAttachProjectId);
      setAttachingProject(false);
    } catch {
      setError('Ошибка при прикреплении к проекту');
    }
  }

  const fetchStatus = useCallback(async () => {
    if (!taskId || taskId === 'undefined') return;
    try {
      const data = await getTaskStatus(taskId);
      setError('');
      setTask(data);
      setEstimationStatus(data.estimation_status ?? 'not_applicable');
      setTaskCost(data.cost ?? null);
      setTaskProjectId(data.project_id ?? null);
      setTaskName(prev => prev === null ? (data.name ?? null) : prev);

      if (data.progress_message) {
        setProgressLog((prev) => {
          const last = prev[prev.length - 1];
          if (last === data.progress_message) return prev;
          return [...prev, data.progress_message!];
        });
      }

      if (data.status === 'processing' || data.status === 'pending') {
        if (!startTimeRef.current) {
          startTimeRef.current = Date.now();
        }
        if (!timerRef.current) {
          timerRef.current = setInterval(() => {
            setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current!) / 1000));
          }, 1000);
        }
      }

      if (data.status === 'completed') {
        const res = await getTaskResults(taskId);
        setResults(res);
        stopTimers();
      } else if (data.status === 'failed' || data.status === 'cancelled') {
        stopTimers();
        if (data.task_type === 'LIST_FROM_GRAND') {
          try { const res = await getTaskResults(taskId); setResults(res); } catch { /* нет результатов */ }
        }
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number }; request?: unknown };
      if (axiosErr.response?.status === 404) {
        setError('Задача не найдена. Возможно, она была удалена.');
        stopTimers();
      } else {
        setError('Не удалось обновить статус. Попробуйте обновить страницу.');
      }
    }
  }, [taskId, stopTimers]);

  useEffect(() => {
    if (!taskId || taskId === 'undefined') {
      navigate('/task/create');
      return;
    }

    fetchStatus();

    const style = document.createElement('style');
    style.textContent = `
      @keyframes spin { to { transform: rotate(360deg); } }
      @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
    `;
    document.head.appendChild(style);

    pollingRef.current = setInterval(fetchStatus, 3000);

    return () => {
      stopTimers();
      stopCheckPolling();
      stopCheckProjectPolling();
      document.head.removeChild(style);
    };
  }, [fetchStatus, taskId, navigate, stopTimers, stopCheckPolling, stopCheckProjectPolling]);

  // Restore check task state after page refresh
  useEffect(() => {
    if (!taskId || taskId === 'undefined') return;
    getRelatedChecks(taskId).then((checks) => {
      for (const check of checks) {
        if (check.task_type === 'CHECK_LIST_COMPLETENESS') {
          setCheckTaskId(check.task_id);
          fetchCheckStatus(check.task_id);
          if (check.status === 'pending' || check.status === 'processing') {
            if (!checkPollingRef.current) {
              checkPollingRef.current = setInterval(() => fetchCheckStatus(check.task_id), 3000);
            }
          }
        } else if (check.task_type === 'CHECK_PROJECT_COMPLETENESS') {
          setCheckProjectTaskId(check.task_id);
          fetchCheckProjectStatus(check.task_id);
          if (check.status === 'pending' || check.status === 'processing') {
            if (!checkProjectPollingRef.current) {
              checkProjectPollingRef.current = setInterval(() => fetchCheckProjectStatus(check.task_id), 3000);
            }
          }
        }
      }
    }).catch(() => {});
  }, [taskId, fetchCheckStatus, fetchCheckProjectStatus]);

  const handleSendMessage = async () => {
    if (!taskId || !message.trim()) return;
    setSending(true);
    const trimmed = message.trim();
    try {
      await sendMessage(taskId, trimmed);

      // Append message locally — backend response does not include chat_history
      const newMsg: ChatMessage = { role: 'user', content: trimmed, timestamp: new Date().toISOString() };
      setChatHistory((prev) => [...prev, newMsg]);
      setMessage('');

      // Reset state for re-processing
      setResults([]);
      setProgressLog(['Обработка уточнения...']);
      setElapsedSeconds(0);
      startTimeRef.current = null;

      // Optimistically flip status so spinner shows immediately
      setTask((prev) => prev ? { ...prev, status: 'processing', progress_message: 'Обработка уточнения...' } : prev);

      // Restart polling (was stopped on completion)
      if (!pollingRef.current) {
        pollingRef.current = setInterval(fetchStatus, 3000);
      }
      // Fetch immediately so UI reflects new backend state without waiting 3 s
      fetchStatus();
    } catch {
      setError('Не удалось отправить сообщение.');
    } finally {
      setSending(false);
    }
  };

  const handleCancel = async () => {
    if (!taskId || cancelling) return;
    setCancelling(true);
    try {
      await cancelTask(taskId);
      setTask((prev) => prev ? { ...prev, status: 'cancelled', error_message: 'Задача остановлена пользователем' } : prev);
      stopTimers();
    } catch {
      setError('Не удалось остановить задачу.');
    } finally {
      setCancelling(false);
    }
  };

  const handleDownload = async (fileId: number, fileName: string) => {
    setDownloading(fileId);
    try {
      await downloadResult(fileId, fileName);
    } catch {
      setError('Ошибка при скачивании файла.');
    } finally {
      setDownloading(null);
    }
  };

  const statusStyle = task ? STATUS_COLORS[task.status] : STATUS_COLORS.pending;

  return (
    <Layout>
      <div style={{ maxWidth: '760px', margin: '0 auto' }}>
        {/* Page title */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
          <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
            Статус задачи
          </h2>
          <button
            onClick={() => navigate('/task/create')}
            style={{
              padding: '9px 18px',
              backgroundColor: '#2563eb',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 600,
            }}
          >
            + Новая задача
          </button>
        </div>

        {error && (
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: '8px',
              marginBottom: '16px',
              fontSize: '14px',
              color: '#dc2626',
            }}
          >
            {error}
          </div>
        )}

        {/* Task info card */}
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: '12px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
            padding: '28px',
            border: '1px solid #e2e8f0',
            marginBottom: '20px',
          }}
        >
          {task ? (
            <>
              {/* Task name with inline edit */}
              <div style={{ marginBottom: '20px' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
                  Название задачи
                </div>
                {editingName ? (
                  <>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                    <input
                      ref={nameInputRef}
                      value={editNameDraft}
                      onChange={e => setEditNameDraft(e.target.value)}
                      onKeyDown={async e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          const trimmed = editNameDraft.trim();
                          if (trimmed && taskId) {
                            try {
                              await updateTask(taskId, { name: trimmed });
                              setTaskName(trimmed);
                              setEditNameError('');
                              setEditingName(false);
                            } catch {
                              setEditNameError('Не удалось сохранить имя. Попробуйте ещё раз.');
                            }
                          } else {
                            setEditingName(false);
                          }
                        }
                        if (e.key === 'Escape') { setEditingName(false); setEditNameError(''); }
                      }}
                      autoFocus
                      style={{ border: '1px solid #93c5fd', borderRadius: '6px', padding: '5px 10px', outline: 'none', fontSize: '16px', fontWeight: 600, width: '280px' }}
                    />
                    <button
                      onClick={async () => {
                        const trimmed = editNameDraft.trim();
                        if (trimmed && taskId) {
                          try {
                            await updateTask(taskId, { name: trimmed });
                            setTaskName(trimmed);
                            setEditNameError('');
                            setEditingName(false);
                          } catch {
                            setEditNameError('Не удалось сохранить имя. Попробуйте ещё раз.');
                          }
                        } else {
                          setEditingName(false);
                        }
                      }}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#16a34a', padding: '2px', display: 'inline-flex' }}
                    >
                      <Check size={18} />
                    </button>
                    <button
                      onClick={() => { setEditingName(false); setEditNameError(''); }}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', padding: '2px', display: 'inline-flex' }}
                    >
                      <X size={18} />
                    </button>
                  </div>
                  {editNameError && (
                    <div style={{ fontSize: '12px', color: '#dc2626', marginTop: '4px' }}>{editNameError}</div>
                  )}
                  </>
                ) : (
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '18px', fontWeight: 700, color: '#1e293b' }}>
                      {taskName || TASK_TYPE_LABELS[task.task_type]}
                    </span>
                    <button
                      onClick={() => { setEditNameDraft(taskName || TASK_TYPE_LABELS[task.task_type] || ''); setEditingName(true); }}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '2px', display: 'inline-flex' }}
                    >
                      <Pencil size={16} />
                    </button>
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                    ID задачи
                  </div>
                  <div style={{ fontSize: '14px', color: '#1e293b', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                    {task.id}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                    Тип задачи
                  </div>
                  <div style={{ fontSize: '14px', color: '#1e293b' }}>
                    {TASK_TYPE_LABELS[task.task_type]}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                    Создана
                  </div>
                  <div style={{ fontSize: '14px', color: '#1e293b' }}>
                    {formatDate(task.created_at)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                    Обновлена
                  </div>
                  <div style={{ fontSize: '14px', color: '#1e293b' }}>
                    {formatDate(task.updated_at)}
                  </div>
                </div>
              </div>

              {/* Status badge + elapsed + STOP button */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    padding: '6px 14px',
                    backgroundColor: statusStyle.bg,
                    color: statusStyle.text,
                    border: `1.5px solid ${statusStyle.border}`,
                    borderRadius: '20px',
                    fontSize: '14px',
                    fontWeight: 600,
                  }}
                >
                  {(task.status === 'pending' || task.status === 'processing') && <Spinner />}
                  {STATUS_LABELS[task.status]}
                </span>
                {(task.status === 'pending' || task.status === 'processing') && elapsedSeconds > 0 && (
                  <span style={{ fontSize: '13px', color: '#94a3b8' }}>
                    {elapsedSeconds < 60
                      ? `${elapsedSeconds} сек.`
                      : `${Math.floor(elapsedSeconds / 60)} мин. ${elapsedSeconds % 60} сек.`}
                  </span>
                )}
                {(task.status === 'pending' || task.status === 'processing') && (
                  <button
                    onClick={handleCancel}
                    disabled={cancelling}
                    style={{
                      padding: '6px 16px',
                      backgroundColor: cancelling ? '#fca5a5' : '#dc2626',
                      color: '#ffffff',
                      border: 'none',
                      borderRadius: '20px',
                      cursor: cancelling ? 'not-allowed' : 'pointer',
                      fontSize: '13px',
                      fontWeight: 700,
                      letterSpacing: '0.3px',
                    }}
                  >
                    {cancelling ? 'Остановка...' : '⏹ Стоп'}
                  </button>
                )}
              </div>

              {/* Current progress message — shown directly, independent of progressLog */}
              {(task.status === 'pending' || task.status === 'processing') && task.progress_message && (
                <div
                  data-testid="progress-message"
                  style={{
                    marginTop: '12px',
                    fontSize: '14px',
                    color: '#0c4a6e',
                    fontWeight: 500,
                  }}
                >
                  {task.progress_message}
                </div>
              )}

              {/* Progress log */}
              {(task.status === 'pending' || task.status === 'processing') && progressLog.length > 0 && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '14px 16px',
                    backgroundColor: '#f0f9ff',
                    border: '1px solid #bae6fd',
                    borderRadius: '8px',
                  }}
                >
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#0369a1', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Ход выполнения
                  </div>
                  {progressLog.map((msg, i) => {
                    const isLast = i === progressLog.length - 1;
                    return (
                      <div key={i}>
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '8px',
                            marginBottom: i < progressLog.length - 1 ? '6px' : 0,
                            opacity: isLast ? 1 : 0.5,
                          }}
                        >
                          <span style={{ fontSize: '14px', marginTop: '1px', flexShrink: 0 }}>
                            {isLast ? '⏳' : '✓'}
                          </span>
                          <span
                            style={{
                              fontSize: '14px',
                              color: isLast ? '#0c4a6e' : '#64748b',
                              fontWeight: isLast ? 500 : 400,
                              animation: isLast ? 'pulse 1.8s ease-in-out infinite' : 'none',
                            }}
                          >
                            {msg}
                          </span>
                        </div>
                        {isLast && <BatchProgressBar message={msg} />}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Cancelled message */}
              {task.status === 'cancelled' && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '14px 16px',
                    backgroundColor: '#f8fafc',
                    border: '1px solid #cbd5e1',
                    borderRadius: '8px',
                    fontSize: '14px',
                    color: '#64748b',
                  }}
                >
                  Задача была остановлена пользователем.
                  {task.task_type === 'LIST_FROM_GRAND' && results.some((r) => r.slot.startsWith('partial')) && (
                    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: '#475569' }}>
                        Частичный результат ({String(task.progress_data?.chunks_done ?? '?')} из {String(task.progress_data?.total_chunks ?? '?')} частей):
                      </div>
                      {results.filter((r) => r.slot.startsWith('partial')).map((r) => (
                        <button
                          key={r.file_id}
                          onClick={() => handleDownload(r.file_id, r.file_name)}
                          disabled={downloading === r.file_id}
                          style={{
                            alignSelf: 'flex-start',
                            padding: '8px 16px',
                            backgroundColor: downloading === r.file_id ? '#e2e8f0' : '#ffffff',
                            color: '#334155',
                            border: '1.5px solid #cbd5e1',
                            borderRadius: '8px',
                            cursor: downloading === r.file_id ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 600,
                          }}
                        >
                          {downloading === r.file_id ? 'Скачивание...' : '⬇ Скачать частичный результат'}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Error message */}
              {task.status === 'failed' && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '16px',
                    backgroundColor: '#fef2f2',
                    border: '1px solid #fecaca',
                    borderRadius: '8px',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#dc2626', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Ошибка выполнения
                  </div>
                  {task.error_message && (
                    <div
                      style={{
                        margin: 0,
                        fontSize: '13px',
                        color: '#7f1d1d',
                        lineHeight: 1.6,
                        maxHeight: '200px',
                        overflowY: 'auto',
                      }}
                    >
                      {task.error_message}
                    </div>
                  )}
                  {progressLog.length > 0 && (
                    <div style={{ marginTop: '12px', borderTop: '1px solid #fecaca', paddingTop: '10px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 600, color: '#991b1b', marginBottom: '6px' }}>
                        Последний шаг:
                      </div>
                      <span style={{ fontSize: '13px', color: '#7f1d1d' }}>
                        {progressLog[progressLog.length - 1]}
                      </span>
                    </div>
                  )}

                  {/* Resume section for LIST_FROM_GRAND with saved progress */}
                  {task.task_type === 'LIST_FROM_GRAND' && task.progress_data?.chunks_done != null && (
                    <div style={{ marginTop: '16px', borderTop: '1px solid #fecaca', paddingTop: '14px' }}>
                      <div style={{ fontSize: '14px', color: '#7f1d1d', marginBottom: '12px', fontWeight: 500 }}>
                        Обработано {String(task.progress_data.chunks_done)} из {String(task.progress_data.total_chunks ?? '?')} частей.
                        {results.some((r) => r.slot.startsWith('partial')) && ' Частичный результат доступен для скачивания.'}
                      </div>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        {results.filter((r) => r.slot.startsWith('partial')).map((r) => (
                          <button
                            key={r.file_id}
                            onClick={() => handleDownload(r.file_id, r.file_name)}
                            disabled={downloading === r.file_id}
                            style={{
                              padding: '8px 16px',
                              backgroundColor: downloading === r.file_id ? '#fca5a5' : '#ffffff',
                              color: '#dc2626',
                              border: '1.5px solid #fca5a5',
                              borderRadius: '8px',
                              cursor: downloading === r.file_id ? 'not-allowed' : 'pointer',
                              fontSize: '13px',
                              fontWeight: 600,
                            }}
                          >
                            {downloading === r.file_id ? 'Скачивание...' : '⬇ Скачать частичный результат'}
                          </button>
                        ))}
                        <button
                          onClick={handleResume}
                          disabled={resuming}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: resuming ? '#fca5a5' : '#dc2626',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: resuming ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 700,
                          }}
                        >
                          {resuming ? 'Запуск...' : '▶ Продолжить'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '32px', color: '#94a3b8' }}>
              <Spinner />
              Загрузка информации о задаче...
            </div>
          )}
        </div>

        {/* Estimation status badge */}
        {task && estimationStatus !== 'not_applicable' && (
          <div style={{ marginBottom: '16px' }}>
            <span style={{
              display: 'inline-block',
              padding: '5px 14px',
              borderRadius: '20px',
              fontSize: '13px',
              fontWeight: 600,
              ...({
                unestimated: { backgroundColor: '#fef2f2', color: '#dc2626' },
                estimated: { backgroundColor: '#fef9c3', color: '#854d0e' },
                optimized: { backgroundColor: '#f0fdf4', color: '#15803d' },
              }[estimationStatus] ?? { backgroundColor: '#f8fafc', color: '#94a3b8' }),
            }}>
              {{
                unestimated: 'Смета: не рассчитана',
                estimated: `Смета: рассчитана${taskCost !== null ? ` · ${new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(taskCost)}` : ''}`,
                optimized: `Смета: оптимизирована${taskCost !== null ? ` · ${new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(taskCost)}` : ''}`,
              }[estimationStatus] ?? estimationStatus}
            </span>
          </div>
        )}

        {/* Attach to project */}
        {task && (
          <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '16px 20px', marginBottom: '16px' }}>
            {taskProjectId ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '14px', color: '#64748b' }}>
                  Проект: <strong style={{ color: '#1e293b' }}>{projects.find((p) => p.id === taskProjectId)?.name ?? taskProjectId}</strong>
                </span>
                <button
                  onClick={async () => { await linkTaskToProject(taskId!, null); setTaskProjectId(null); }}
                  style={{ padding: '4px 12px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', color: '#64748b' }}
                >
                  Открепить
                </button>
              </div>
            ) : attachingProject ? (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <select
                  value={selectedAttachProjectId}
                  onChange={(e) => setSelectedAttachProjectId(e.target.value)}
                  style={{ flex: 1, padding: '8px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '14px' }}
                >
                  <option value="">— Выберите проект —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <button
                  onClick={handleAttachProject}
                  disabled={!selectedAttachProjectId}
                  style={{ padding: '8px 16px', backgroundColor: '#2563eb', color: '#fff', border: 'none', borderRadius: '8px', cursor: selectedAttachProjectId ? 'pointer' : 'not-allowed', fontSize: '14px', fontWeight: 600 }}
                >
                  Прикрепить
                </button>
                <button
                  onClick={() => setAttachingProject(false)}
                  style={{ padding: '8px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', color: '#64748b' }}
                >
                  Отмена
                </button>
              </div>
            ) : (
              <button
                onClick={() => setAttachingProject(true)}
                style={{ padding: '6px 16px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#2563eb', fontWeight: 500 }}
              >
                + Прикрепить к проекту
              </button>
            )}
          </div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '12px',
              boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
              padding: '24px 28px',
              border: '1px solid #e2e8f0',
              marginBottom: '20px',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: '17px', fontWeight: 700, color: '#0f172a' }}>
              Результаты
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {results.map((result) => (
                <div
                  key={result.file_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 14px',
                    backgroundColor: '#f0fdf4',
                    border: '1px solid #86efac',
                    borderRadius: '8px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '18px' }}>📊</span>
                    <span style={{ fontSize: '14px', color: '#1e293b', fontWeight: 500 }}>
                      {result.file_name}
                    </span>
                  </div>
                  <button
                    onClick={() => handleDownload(result.file_id, result.file_name)}
                    disabled={downloading === result.file_id}
                    style={{
                      padding: '7px 16px',
                      backgroundColor: downloading === result.file_id ? '#86efac' : '#16a34a',
                      color: '#ffffff',
                      border: 'none',
                      borderRadius: '6px',
                      cursor: downloading === result.file_id ? 'not-allowed' : 'pointer',
                      fontSize: '13px',
                      fontWeight: 600,
                    }}
                  >
                    {downloading === result.file_id ? 'Скачивание...' : 'Скачать'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Check completeness card — shown after LIST_FROM_GRAND completes */}
        {task && task.status === 'completed' && task.task_type === 'LIST_FROM_GRAND' && (
          <div
            style={{
              backgroundColor: '#f0f9ff',
              borderRadius: '12px',
              border: '1px solid #bae6fd',
              padding: '20px 24px',
              marginBottom: '20px',
            }}
          >
            <div style={{ fontSize: '15px', fontWeight: 700, color: '#0c4a6e', marginBottom: '6px' }}>
              Проверка полноты материалов по ГЭСН
            </div>
            <div style={{ fontSize: '14px', color: '#0369a1', marginBottom: '14px' }}>
              Хотите проверить, все ли необходимые материалы учтены согласно нормативной базе?
            </div>
            {!checkTaskId ? (
              <button
                onClick={handleCheckCompleteness}
                disabled={checkStarting}
                style={{
                  padding: '10px 22px',
                  backgroundColor: checkStarting ? '#7dd3fc' : '#0284c7',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: checkStarting ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 700,
                }}
              >
                {checkStarting ? 'Запуск...' : 'Да, проверить'}
              </button>
            ) : (
              <>
                {/* Running: progress log + stop */}
                {checkTask && (checkTask.status === 'pending' || checkTask.status === 'processing') && (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '10px' }}>
                      <Spinner />
                      <span style={{ fontSize: '14px', color: '#0369a1', fontWeight: 500, flex: 1 }}>
                        {checkTask.progress_message || 'Проверка запущена...'}
                      </span>
                      {checkElapsed > 0 && (
                        <span style={{ fontSize: '13px', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                          {checkElapsed < 60 ? `${checkElapsed} сек.` : `${Math.floor(checkElapsed / 60)} мин. ${checkElapsed % 60} сек.`}
                        </span>
                      )}
                      <button
                        onClick={handleCheckCancel}
                        disabled={checkCancelling}
                        style={{ padding: '5px 14px', backgroundColor: checkCancelling ? '#fca5a5' : '#dc2626', color: '#fff', border: 'none', borderRadius: '16px', cursor: checkCancelling ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 700 }}
                      >
                        {checkCancelling ? 'Остановка...' : '⏹ Стоп'}
                      </button>
                    </div>
                    {checkElapsed > 900 && (
                      <div style={{ marginBottom: '10px', padding: '8px 12px', backgroundColor: '#fef9c3', border: '1px solid #fde047', borderRadius: '8px', fontSize: '13px', color: '#854d0e' }}>
                        Проверка идёт уже {Math.floor(checkElapsed / 60)} мин. — это нормально для большого перечня. Если задача зависла, нажмите Стоп и продолжите с прерванного места.
                      </div>
                    )}
                    {checkProgressLog.length > 0 && (
                      <div style={{ padding: '12px 14px', backgroundColor: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '8px' }}>
                        {checkProgressLog.map((msg, i) => {
                          const isLast = i === checkProgressLog.length - 1;
                          return (
                            <div key={i}>
                              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', marginBottom: i < checkProgressLog.length - 1 ? '6px' : 0, opacity: isLast ? 1 : 0.5 }}>
                                <span style={{ fontSize: '13px', flexShrink: 0 }}>{isLast ? '⏳' : '✓'}</span>
                                <span style={{ fontSize: '13px', color: isLast ? '#0c4a6e' : '#64748b', fontWeight: isLast ? 500 : 400 }}>{msg}</span>
                              </div>
                              {isLast && <BatchProgressBar message={msg} />}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Cancelled: partial results + resume */}
                {checkTask && checkTask.status === 'cancelled' && (
                  <div style={{ padding: '12px 14px', backgroundColor: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '8px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '13px', color: '#64748b', marginBottom: '10px' }}>
                      Проверка остановлена. Обработано {String(checkTask.progress_data?.chunks_done ?? '?')} из {String(checkTask.progress_data?.total_chunks ?? '?')} частей.
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {checkResults.filter((r) => r.slot.startsWith('partial')).map((r) => (
                        <button key={r.file_id} onClick={() => handleDownload(r.file_id, r.file_name)} disabled={downloading === r.file_id}
                          style={{ alignSelf: 'flex-start', padding: '7px 14px', backgroundColor: '#fff', color: '#334155', border: '1.5px solid #cbd5e1', borderRadius: '8px', cursor: downloading === r.file_id ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                          {downloading === r.file_id ? 'Скачивание...' : '⬇ Скачать частичный результат'}
                        </button>
                      ))}
                      <button onClick={handleCheckResume} disabled={checkResuming}
                        style={{ alignSelf: 'flex-start', padding: '7px 18px', backgroundColor: checkResuming ? '#fca5a5' : '#dc2626', color: '#fff', border: 'none', borderRadius: '8px', cursor: checkResuming ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 700 }}>
                        {checkResuming ? 'Запуск...' : '▶ Продолжить'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Failed: error + resume if has progress */}
                {checkTask && checkTask.status === 'failed' && (
                  <div style={{ padding: '12px 14px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '13px', color: '#7f1d1d', marginBottom: '10px' }}>
                      Ошибка: {checkTask.error_message}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {checkResults.filter((r) => r.slot.startsWith('partial')).map((r) => (
                        <button key={r.file_id} onClick={() => handleDownload(r.file_id, r.file_name)} disabled={downloading === r.file_id}
                          style={{ alignSelf: 'flex-start', padding: '7px 14px', backgroundColor: '#fff', color: '#334155', border: '1.5px solid #fecaca', borderRadius: '8px', cursor: downloading === r.file_id ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                          {downloading === r.file_id ? 'Скачивание...' : '⬇ Скачать частичный результат'}
                        </button>
                      ))}
                      {checkTask.progress_data?.chunks_done != null && (
                        <button onClick={handleCheckResume} disabled={checkResuming}
                          style={{ alignSelf: 'flex-start', padding: '7px 18px', backgroundColor: checkResuming ? '#fca5a5' : '#dc2626', color: '#fff', border: 'none', borderRadius: '8px', cursor: checkResuming ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 700 }}>
                          {checkResuming ? 'Запуск...' : '▶ Продолжить'}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Completed */}
                {checkTask && checkTask.status === 'completed' && checkResults.length > 0 && (
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#15803d', marginBottom: '10px' }}>
                      Проверка завершена
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {checkResults.map((r) => (
                        <div key={r.file_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', backgroundColor: '#f0fdf4', border: '1px solid #86efac', borderRadius: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '18px' }}>📋</span>
                            <span style={{ fontSize: '14px', color: '#1e293b', fontWeight: 500 }}>{r.file_name}</span>
                          </div>
                          <button onClick={() => handleDownload(r.file_id, r.file_name)} disabled={downloading === r.file_id}
                            style={{ padding: '7px 16px', backgroundColor: downloading === r.file_id ? '#86efac' : '#16a34a', color: '#fff', border: 'none', borderRadius: '6px', cursor: downloading === r.file_id ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                            {downloading === r.file_id ? 'Скачивание...' : 'Скачать'}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Check completeness card — shown after LIST_FROM_PROJECT completes */}
        {task && task.status === 'completed' && task.task_type === 'LIST_FROM_PROJECT' && (
          <div
            style={{
              backgroundColor: '#f0f9ff',
              borderRadius: '12px',
              border: '1px solid #bae6fd',
              padding: '20px 24px',
              marginBottom: '20px',
            }}
          >
            <div style={{ fontSize: '15px', fontWeight: 700, color: '#0c4a6e', marginBottom: '6px' }}>
              Проверка полноты материалов по ГЭСН
            </div>
            <div style={{ fontSize: '14px', color: '#0369a1', marginBottom: '14px' }}>
              Хотите проверить, все ли необходимые материалы учтены согласно нормативной базе?
            </div>
            {!checkProjectTaskId ? (
              <button
                onClick={handleCheckProjectCompleteness}
                disabled={checkProjectStarting}
                style={{
                  padding: '10px 22px',
                  backgroundColor: checkProjectStarting ? '#7dd3fc' : '#0284c7',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: checkProjectStarting ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 700,
                }}
              >
                {checkProjectStarting ? 'Запуск...' : 'Да, проверить'}
              </button>
            ) : (
              <>
                {/* Running: progress log + stop */}
                {checkProjectTask && (checkProjectTask.status === 'pending' || checkProjectTask.status === 'processing') && (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '10px' }}>
                      <Spinner />
                      <span style={{ fontSize: '14px', color: '#0369a1', fontWeight: 500, flex: 1 }}>
                        {checkProjectTask.progress_message || 'Проверка запущена...'}
                      </span>
                      {checkProjectElapsed > 0 && (
                        <span style={{ fontSize: '13px', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                          {checkProjectElapsed < 60 ? `${checkProjectElapsed} сек.` : `${Math.floor(checkProjectElapsed / 60)} мин. ${checkProjectElapsed % 60} сек.`}
                        </span>
                      )}
                      <button
                        onClick={handleCheckProjectCancel}
                        disabled={checkProjectCancelling}
                        style={{ padding: '5px 14px', backgroundColor: checkProjectCancelling ? '#fca5a5' : '#dc2626', color: '#fff', border: 'none', borderRadius: '16px', cursor: checkProjectCancelling ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 700 }}
                      >
                        {checkProjectCancelling ? 'Остановка...' : '⏹ Стоп'}
                      </button>
                    </div>
                    {checkProjectElapsed > 900 && (
                      <div style={{ marginBottom: '10px', padding: '8px 12px', backgroundColor: '#fef9c3', border: '1px solid #fde047', borderRadius: '8px', fontSize: '13px', color: '#854d0e' }}>
                        Проверка идёт уже {Math.floor(checkProjectElapsed / 60)} мин. — это нормально для большого перечня. Если задача зависла, нажмите Стоп и продолжите с прерванного места.
                      </div>
                    )}
                    {checkProjectProgressLog.length > 0 && (
                      <div style={{ padding: '12px 14px', backgroundColor: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '8px' }}>
                        {checkProjectProgressLog.map((msg, i) => {
                          const isLast = i === checkProjectProgressLog.length - 1;
                          return (
                            <div key={i}>
                              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', marginBottom: i < checkProjectProgressLog.length - 1 ? '6px' : 0, opacity: isLast ? 1 : 0.5 }}>
                                <span style={{ fontSize: '13px', flexShrink: 0 }}>{isLast ? '⏳' : '✓'}</span>
                                <span style={{ fontSize: '13px', color: isLast ? '#0c4a6e' : '#64748b', fontWeight: isLast ? 500 : 400 }}>{msg}</span>
                              </div>
                              {isLast && <BatchProgressBar message={msg} />}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Cancelled: partial results + resume */}
                {checkProjectTask && checkProjectTask.status === 'cancelled' && (
                  <div style={{ padding: '12px 14px', backgroundColor: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '8px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '13px', color: '#64748b', marginBottom: '10px' }}>
                      Проверка остановлена. Обработано {String(checkProjectTask.progress_data?.chunks_done ?? '?')} из {String(checkProjectTask.progress_data?.total_chunks ?? '?')} частей.
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {checkProjectResults.filter((r) => r.slot.startsWith('partial')).map((r) => (
                        <button key={r.file_id} onClick={() => handleDownload(r.file_id, r.file_name)} disabled={downloading === r.file_id}
                          style={{ alignSelf: 'flex-start', padding: '7px 14px', backgroundColor: '#fff', color: '#334155', border: '1.5px solid #cbd5e1', borderRadius: '8px', cursor: downloading === r.file_id ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                          {downloading === r.file_id ? 'Скачивание...' : '⬇ Скачать частичный результат'}
                        </button>
                      ))}
                      <button onClick={handleCheckProjectResume} disabled={checkProjectResuming}
                        style={{ alignSelf: 'flex-start', padding: '7px 18px', backgroundColor: checkProjectResuming ? '#fca5a5' : '#dc2626', color: '#fff', border: 'none', borderRadius: '8px', cursor: checkProjectResuming ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 700 }}>
                        {checkProjectResuming ? 'Запуск...' : '▶ Продолжить'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Failed: error + resume if has progress */}
                {checkProjectTask && checkProjectTask.status === 'failed' && (
                  <div style={{ padding: '12px 14px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '13px', color: '#7f1d1d', marginBottom: '10px' }}>
                      Ошибка: {checkProjectTask.error_message}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {checkProjectResults.filter((r) => r.slot.startsWith('partial')).map((r) => (
                        <button key={r.file_id} onClick={() => handleDownload(r.file_id, r.file_name)} disabled={downloading === r.file_id}
                          style={{ alignSelf: 'flex-start', padding: '7px 14px', backgroundColor: '#fff', color: '#334155', border: '1.5px solid #fecaca', borderRadius: '8px', cursor: downloading === r.file_id ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                          {downloading === r.file_id ? 'Скачивание...' : '⬇ Скачать частичный результат'}
                        </button>
                      ))}
                      {checkProjectTask.progress_data?.chunks_done != null && (
                        <button onClick={handleCheckProjectResume} disabled={checkProjectResuming}
                          style={{ alignSelf: 'flex-start', padding: '7px 18px', backgroundColor: checkProjectResuming ? '#fca5a5' : '#dc2626', color: '#fff', border: 'none', borderRadius: '8px', cursor: checkProjectResuming ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 700 }}>
                          {checkProjectResuming ? 'Запуск...' : '▶ Продолжить'}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Completed */}
                {checkProjectTask && checkProjectTask.status === 'completed' && checkProjectResults.length > 0 && (
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#15803d', marginBottom: '10px' }}>
                      Проверка завершена
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {checkProjectResults.map((r) => (
                        <div key={r.file_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', backgroundColor: '#f0fdf4', border: '1px solid #86efac', borderRadius: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '18px' }}>📋</span>
                            <span style={{ fontSize: '14px', color: '#1e293b', fontWeight: 500 }}>{r.file_name}</span>
                          </div>
                          <button onClick={() => handleDownload(r.file_id, r.file_name)} disabled={downloading === r.file_id}
                            style={{ padding: '7px 16px', backgroundColor: downloading === r.file_id ? '#86efac' : '#16a34a', color: '#fff', border: 'none', borderRadius: '6px', cursor: downloading === r.file_id ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                            {downloading === r.file_id ? 'Скачивание...' : 'Скачать'}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Chat section */}
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: '12px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
            padding: '24px 28px',
            border: '1px solid #e2e8f0',
          }}
        >
          <h3 style={{ margin: '0 0 16px', fontSize: '17px', fontWeight: 700, color: '#0f172a' }}>
            Уточнить задачу
          </h3>

          {/* Chat history */}
          {chatHistory.length > 0 && (
            <div
              style={{
                maxHeight: '320px',
                overflowY: 'auto',
                marginBottom: '16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
                padding: '4px 0',
              }}
            >
              {chatHistory.map((msg, index) => (
                <div
                  key={index}
                  style={{
                    display: 'flex',
                    justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  }}
                >
                  <div
                    style={{
                      maxWidth: '80%',
                      padding: '10px 14px',
                      backgroundColor: msg.role === 'user' ? '#2563eb' : '#f1f5f9',
                      color: msg.role === 'user' ? '#ffffff' : '#1e293b',
                      borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                      fontSize: '14px',
                      lineHeight: '1.5',
                    }}
                  >
                    <p style={{ margin: 0 }}>{msg.content}</p>
                    <p
                      style={{
                        margin: '6px 0 0',
                        fontSize: '11px',
                        opacity: 0.6,
                        textAlign: 'right',
                      }}
                    >
                      {formatDate(msg.timestamp)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Message input */}
          <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end' }}>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Введите уточнение или дополнительный вопрос..."
              rows={3}
              disabled={sending}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              style={{
                flex: 1,
                padding: '10px 14px',
                fontSize: '14px',
                color: '#1e293b',
                border: '1.5px solid #e2e8f0',
                borderRadius: '8px',
                resize: 'vertical',
                outline: 'none',
                fontFamily: 'inherit',
                backgroundColor: sending ? '#f1f5f9' : '#ffffff',
                transition: 'border-color 0.15s',
              }}
              onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
              onBlur={(e) => { e.target.style.borderColor = '#e2e8f0'; }}
            />
            <button
              onClick={handleSendMessage}
              disabled={sending || !message.trim()}
              style={{
                padding: '10px 20px',
                backgroundColor: sending || !message.trim() ? '#93c5fd' : '#2563eb',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                cursor: sending || !message.trim() ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                fontWeight: 600,
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              {sending ? 'Отправка...' : 'Уточнить'}
            </button>
          </div>
          <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#94a3b8' }}>
            Ctrl+Enter для отправки
          </p>
        </div>
      </div>
    </Layout>
  );
};

export default TaskStatusPage;
