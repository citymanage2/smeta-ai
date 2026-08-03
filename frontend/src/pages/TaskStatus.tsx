import React, { useEffect, useState, useRef, useCallback } from 'react';
import { formatTaskError, formatApiDetail } from '../utils/formatError';
import { describeEta } from '../utils/eta';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Check, X } from 'lucide-react';
import Layout from '../components/Layout';
import { LumaSpin, SectionLoader } from '../components/ui/LumaSpin';
import { BatchProgressBar } from '../components/BatchProgressBar';
import { TaskStatus as TStatus, TaskResult, TASK_TYPE_LABELS, STATUS_LABELS, ProjectCard } from '../types';
import {
  getTaskStatus,
  getTaskResults,
  cancelTask,
  downloadResult,
  downloadInputFile,
  updateTask,
  resumeTask,
  restartTask,
  TaskStatusResponse,
} from '../api/tasks';
import { locateDocumentByTask } from '../api/documents';
import {
  linkTaskToProject,
  listProjects,
} from '../api/projects';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/Select';
import { useNotificationStore } from '../stores/notificationStore';
import { notify } from '../utils/notify';

const STATUS_COLORS: Record<TStatus, { bg: string; text: string; border: string }> = {
  pending: { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  processing: { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  completed: { bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  failed: { bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
  cancelled: { bg: '#f8fafc', text: '#64748b', border: '#cbd5e1' },
  paused: { bg: '#fffbeb', text: '#b45309', border: '#fcd34d' },
};

// Через сколько секунд молчания обработчика считаем задачу подозрительной.
// Worker продлевает jobs.claimed_at раз в 60 с (app/worker.py: hb_interval),
// поэтому 180 с — три пропущенных сигнала подряд, а не случайная задержка.
const HEARTBEAT_STALE_S = 180;

// Отсрочка перед первым предупреждением: только что созданная задача считаные
// секунды ждёт свободный обработчик, и это норма, а не поломка.
const HEARTBEAT_GRACE_S = 60;

function formatAgo(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} сек. назад`;
  const min = Math.floor(seconds / 60);
  if (min < 60) return `${min} мин. назад`;
  return `${(min / 60).toFixed(1)} ч. назад`;
}

// Типы задач, которые бэкенд умеет продолжать с чекпоинта (см. RESUMABLE_TYPES
// в backend/app/routers/tasks.py). Должен совпадать с бэкендом.
const RESUMABLE_TASK_TYPES: string[] = [
  'LIST_FROM_GRAND',
  'LIST_FROM_PROJECT',
  'CHECK_LIST_COMPLETENESS',
  'CHECK_PROJECT_COMPLETENESS',
  'ESTIMATE_FROM_LIST',
];

// Пачка отправлена в Batch API и оплачена — продолжение не пересчитывает её, а
// забирает готовый результат (см. is_batch_pending в backend/app/services/checkpoint.py).
function isBatchPending(task: TaskStatusResponse): boolean {
  const pd = task.progress_data;
  return !!pd && pd._stage === 'batch_pending' && pd.batch_id != null;
}

// Есть ли у задачи сохранённый чекпоинт для продолжения без потери прогресса.
function hasResumeCheckpoint(task: TaskStatusResponse): boolean {
  const pd = task.progress_data;
  if (!pd) return false;
  return (
    pd.chunks_done != null ||
    pd.ocr_pages_partial != null ||
    pd.ocr_pages != null ||
    pd._stage === 'pre_excel' ||
    pd._stage === 'claude_partial' ||
    isBatchPending(task)
  );
}

// Число уже распознанных страниц OCR (для сообщения при возобновлении).
function ocrDonePages(task: TaskStatusResponse): number | null {
  const pd = task.progress_data;
  if (!pd) return null;
  const arr = pd.ocr_pages ?? pd.ocr_pages_partial;
  return Array.isArray(arr) ? arr.length : null;
}

function isResumable(task: TaskStatusResponse): boolean {
  return (
    RESUMABLE_TASK_TYPES.includes((task.task_type || '').toUpperCase()) &&
    hasResumeCheckpoint(task)
  );
}

function Spinner() {
  return <LumaSpin size="sm" color="#2563eb" />;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/**
 * Задача, принадлежащая смете, живёт на странице карточки — там же её этапы,
 * файлы и таблица. Эта страница остаётся только для задач вне сметы («Входящий»,
 * архив) и как рабочая цель для старых ссылок из уведомлений и закладок.
 */
const TaskStatusPage: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [redirecting, setRedirecting] = useState(true);
  const addTask = useNotificationStore((state) => state.addTask);
  const removeTask = useNotificationStore((state) => state.removeTask);

  const [task, setTask] = useState<TaskStatusResponse | null>(null);
  const [results, setResults] = useState<TaskResult[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const [downloading, setDownloading] = useState<number | null>(null);
  const [downloadingInputFile, setDownloadingInputFile] = useState<number | null>(null);
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
  const [restarting, setRestarting] = useState(false);


  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number | null>(null);

  // Ref to latest fetch callback — used by visibilitychange handler to avoid stale closures
  const fetchStatusRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!taskId || taskId === 'undefined') {
      navigate('/task/create');
    }
  }, [taskId, navigate]);

  // Старая ссылка на задачу открывает страницу её сметы, на нужном этапе.
  // Задача без карточки (создана вне сметы) остаётся здесь.
  useEffect(() => {
    if (!taskId || taskId === 'undefined') return;
    let cancelled = false;
    locateDocumentByTask(taskId)
      .then((location) => {
        if (cancelled) return;
        navigate(
          `/projects/${location.project_id}/cards/${location.card_id}?stage=${location.kind}`,
          { replace: true },
        );
      })
      .catch(() => { if (!cancelled) setRedirecting(false); });
    return () => { cancelled = true };
  }, [taskId, navigate]);

  const stopTimers = useCallback(() => {
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const handleResume = async () => {
    if (!taskId || resuming) return;
    setResuming(true);
    try {
      const res = await resumeTask(taskId);
      setTask((prev) => prev ? { ...prev, status: (res.status as TStatus) || 'pending', error_message: undefined } : prev);
      setProgressLog([]);
      setElapsedSeconds(0);
      startTimeRef.current = null;
      if (!pollingRef.current) {
        pollingRef.current = setInterval(fetchStatus, 3000);
      }
      fetchStatus();
    } catch (e: any) {
      // Показываем причину с бэкенда (409 detail), иначе диагностировать нечем.
      setError(formatApiDetail(e?.response?.data?.detail, 'Не удалось возобновить задачу.'));
    } finally {
      setResuming(false);
    }
  };

  const handleRestart = async () => {
    if (!taskId || restarting) return;
    setRestarting(true);
    try {
      await restartTask(taskId);
      setTask((prev) => prev ? { ...prev, status: 'pending', error_message: undefined } : prev);
      setProgressLog([]);
      setElapsedSeconds(0);
      startTimeRef.current = null;
      if (!pollingRef.current) {
        pollingRef.current = setInterval(fetchStatus, 3000);
      }
      fetchStatus();
    } catch (e: any) {
      setError(formatApiDetail(e?.response?.data?.detail, 'Не удалось перезапустить задачу.'));
    } finally {
      setRestarting(false);
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

      if (data.progress_log && data.progress_log.length > 0) {
        setProgressLog(data.progress_log);
      } else if (data.progress_message) {
        setProgressLog((prev) => {
          const last = prev[prev.length - 1];
          if (last === data.progress_message) return prev;
          return [...prev, data.progress_message!];
        });
      }

      if (data.status === 'processing' || data.status === 'pending') {
        // От начала ТЕКУЩЕГО прогона, а не от создания задачи: перезапуск
        // переставляет started_at, и таймер показывает, сколько задача считается
        // сейчас, а не сколько существует. Пока прогон не начался (pending)
        // started_at пуст — считаем от создания. Якорь сверяем на каждом опросе:
        // он меняется, когда прогон стартовал или его перезапустили.
        const anchor = new Date(data.started_at ?? data.created_at).getTime();
        if (startTimeRef.current !== anchor) {
          startTimeRef.current = anchor;
        }
        setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
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
        const tracked = useNotificationStore.getState().trackedTasks.get(taskId);
        if (tracked) {
          notify('success', { taskId, projectName: tracked.projectName, taskName: tracked.taskName }, navigate);
          removeTask(taskId);
        }
        if (data.task_type === 'ESTIMATE_OPTIMIZATION') {
          navigate(`/tasks/${taskId}/estimate`);
          return;
        }
      } else if (data.status === 'failed' || data.status === 'cancelled') {
        stopTimers();
        const tracked = useNotificationStore.getState().trackedTasks.get(taskId);
        if (tracked) {
          if (data.status === 'failed') {
            notify('error', { taskId, projectName: tracked.projectName, taskName: tracked.taskName, errorText: data.error_message ?? undefined }, navigate);
          }
          removeTask(taskId);
        }
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

  // Reset all task-specific state when navigating to a different task.
  // Without this, stale values from the previous task (especially taskName)
  // persist until the new task's data arrives from the server.
  useEffect(() => {
    setTask(null);
    setTaskName(null);
    setResults([]);
    setProgressLog([]);
    setError('');
    setElapsedSeconds(0);
    setEstimationStatus('not_applicable');
    setTaskCost(null);
    setTaskProjectId(null);
    startTimeRef.current = null;
  }, [taskId]);

  useEffect(() => {
    if (!taskId || taskId === 'undefined') {
      navigate('/task/create');
      return;
    }

    fetchStatus();

    const style = document.createElement('style');
    style.textContent = `@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } } @keyframes spin { to { transform: rotate(360deg); } }`;
    document.head.appendChild(style);

    pollingRef.current = setInterval(fetchStatus, 3000);

    // Keep refs current so the visibilitychange handler always uses the latest callbacks
    fetchStatusRef.current = fetchStatus;

    // Re-fetch immediately when the user returns to the tab (browser throttles
    // background setInterval down to ~1 req/min, so without this the progress
    // messages freeze while the tab is hidden)
    const handleVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return;
      if (startTimeRef.current && timerRef.current) {
        setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }
      if (pollingRef.current) fetchStatusRef.current();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      stopTimers();
      document.head.removeChild(style);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchStatus, taskId, navigate, stopTimers]);

  // Ref для чтения последнего task в cleanup без добавления task в deps —
  // иначе cleanup вызывается при каждом poll (каждые 3 сек) пока пользователь на странице
  const taskRef = useRef(task);
  useEffect(() => { taskRef.current = task; }, [task]);

  // Когда пользователь уходит со страницы и задача ещё активна —
  // регистрируем её в notificationStore, чтобы глобальный поллер продолжил отслеживание
  useEffect(() => {
    return () => {
      const t = taskRef.current;
      if (!taskId || !t) return;
      if (t.status === 'pending' || t.status === 'processing') {
        addTask(taskId, {
          projectName: '',
          taskName: t.name ?? taskId,
        });
      }
    };
  }, [taskId, addTask]);

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


  const handleDownloadInputFile = async (fileIndex: number, fileName: string) => {
    if (!taskId) return;
    setDownloadingInputFile(fileIndex);
    try {
      await downloadInputFile(taskId, fileIndex, fileName);
    } catch {
      setError('Ошибка при скачивании исходного файла.');
    } finally {
      setDownloadingInputFile(null);
    }
  };

  const statusStyle = task ? STATUS_COLORS[task.status] : STATUS_COLORS.pending;

  // Пока неизвестно, принадлежит ли задача смете, страницу не рисуем: иначе
  // при переходе по старой ссылке мелькал бы экран, который тут же сменится.
  if (redirecting) {
    return (
      <Layout>
        <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
          <LumaSpin size="lg" color="#3b82f6" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div style={{ maxWidth: '760px', margin: '0 auto' }}>
        {/* Page title */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '24px' }}>
          <div>
            {taskProjectId && (
              <button
                onClick={() => navigate(`/projects/${taskProjectId}`)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#2563eb', fontSize: '13px', padding: 0, marginBottom: '8px', display: 'block' }}
              >
                ← {projects.find(p => p.id === taskProjectId)?.name ?? 'Проект'}
              </button>
            )}
            <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
              {task ? (taskName || TASK_TYPE_LABELS[task.task_type] || 'Статус задачи') : 'Статус задачи'}
            </h2>
            {task && (
              <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#64748b' }}>
                {TASK_TYPE_LABELS[task.task_type]}
              </p>
            )}
          </div>
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

              {/* Когда ждать результат. Рядом с таймером «сколько уже идёт»:
                  прошедшее время без прогноза не отвечает на главный вопрос
                  менеджера — можно ли обещать смету сегодня. */}
              {(() => {
                const view = describeEta(task.eta, task.status);
                if (!view) return null;
                return (
                  <div
                    data-testid="task-eta"
                    title={view.hint}
                    style={{ marginTop: '10px', fontSize: '13px', color: '#1e293b' }}
                  >
                    {/* Место в очереди — первым: задачи считаются строго по одной,
                        и «меня возьмут третьей» объясняет ожидание лучше, чем
                        любые минуты (они-то оценка, а позиция — факт). */}
                    {view.position && (
                      <span data-testid="task-queue-position" style={{ fontWeight: 600 }}>
                        {view.position[0].toUpperCase() + view.position.slice(1)} ·{' '}
                      </span>
                    )}
                    Результат {view.ready}
                    {view.start && (
                      <span style={{ color: '#64748b' }}> · {view.start}</span>
                    )}
                    {view.rough && (
                      <span style={{ color: '#94a3b8' }}> · оценка грубая</span>
                    )}
                  </div>
                );
              })()}

              {/* Признак жизни обработчика. Крутилка и растущий таймер есть и у
                  мёртвой задачи — по ним нельзя отличить работу от зависания.
                  Здесь показан факт: когда обработчик последний раз отчитался. */}
              {(task.status === 'pending' || task.status === 'processing') && (() => {
                const age = task.worker_heartbeat_age_s;
                const alive = age !== null && age !== undefined && age <= HEARTBEAT_STALE_S;

                // Пачка отправлена в Batch API: она обрабатывается на стороне
                // Anthropic, и живого обработчика за задачей нет ПО ЗАМЫСЛУ
                // (то же исключение, что в sweep_orphaned_tasks на бэкенде).
                // Тревожить тут нечем — прогресс показывает BatchProgressBar.
                if (isBatchPending(task)) return null;

                // Свежесозданная задача ждёт свободный обработчик считаные
                // секунды. Без этой отсрочки жёлтая плашка мигала бы на каждой
                // новой задаче и обесценивала бы предупреждение.
                if (!alive && elapsedSeconds < HEARTBEAT_GRACE_S) return null;

                if (alive) {
                  return (
                    <div
                      data-testid="worker-alive"
                      style={{ marginTop: '10px', fontSize: '13px', color: '#15803d' }}
                    >
                      ● Обработчик на связи{age! >= 5 ? ` — сигнал ${formatAgo(age!)}` : ''}
                    </div>
                  );
                }

                // Сигнала нет: либо задача ещё не взята в работу (pending), либо
                // обработчик умер/застрял. Второе — то, из-за чего задача висит
                // часами, поэтому предлагаем перезапуск сразу здесь.
                const neverStarted = age === null || age === undefined;
                return (
                  <div
                    data-testid="worker-stale"
                    style={{
                      marginTop: '12px',
                      padding: '12px 14px',
                      backgroundColor: '#fffbeb',
                      border: '1px solid #fcd34d',
                      borderRadius: '8px',
                    }}
                  >
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#b45309' }}>
                      ⚠ {neverStarted
                        ? (task.status === 'pending'
                            ? 'Задача ещё не взята в обработку'
                            : 'Обработчик не отвечает')
                        : `Обработчик молчит ${formatAgo(age!)}`}
                    </div>
                    <div style={{ fontSize: '13px', color: '#78350f', marginTop: '4px', lineHeight: 1.5 }}>
                      {neverStarted && task.status === 'pending'
                        ? 'Ждёт свободный обработчик. Если это надолго — проверьте очередь в панели администратора.'
                        : 'Возможно, задача зависла. Перезапуск продолжит с последнего сохранённого шага — уже посчитанное не считается заново.'}
                    </div>
                    <button
                      onClick={handleRestart}
                      disabled={restarting}
                      style={{
                        marginTop: '10px',
                        padding: '6px 14px',
                        fontSize: '13px',
                        fontWeight: 600,
                        backgroundColor: restarting ? '#e2e8f0' : '#b45309',
                        color: restarting ? '#94a3b8' : '#ffffff',
                        border: 'none',
                        borderRadius: '8px',
                        cursor: restarting ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {restarting ? 'Перезапуск...' : '↻ Перезапустить'}
                    </button>
                  </div>
                );
              })()}

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
                  <div style={{ marginTop: '14px' }}>
                    <button
                      onClick={handleRestart}
                      disabled={restarting}
                      style={{
                        padding: '8px 20px',
                        backgroundColor: restarting ? '#e2e8f0' : '#2563eb',
                        color: restarting ? '#94a3b8' : '#ffffff',
                        border: 'none',
                        borderRadius: '8px',
                        cursor: restarting ? 'not-allowed' : 'pointer',
                        fontSize: '13px',
                        fontWeight: 700,
                      }}
                    >
                      {restarting ? 'Запуск...' : '↺ Перезапустить'}
                    </button>
                  </div>
                </div>
              )}

              {/* Paused — баланс API исчерпан, задача возобновится автоматически */}
              {task.status === 'paused' && (
                <div
                  data-testid="paused-block"
                  style={{
                    marginTop: '16px',
                    padding: '16px',
                    backgroundColor: '#fffbeb',
                    border: '1px solid #fcd34d',
                    borderRadius: '8px',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#b45309', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    ⏸ На паузе
                  </div>
                  <div style={{ margin: 0, fontSize: '13px', color: '#92400e', lineHeight: 1.6 }}>
                    {task.error_message
                      ? formatTaskError(task.error_message)
                      : 'Баланс API Anthropic исчерпан. Задача продолжится автоматически после пополнения счёта — прогресс сохранён, уже посчитанные позиции повторно не считаются.'}
                  </div>
                  {progressLog.length > 0 && (
                    <div style={{ marginTop: '12px', borderTop: '1px solid #fde68a', paddingTop: '10px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 600, color: '#b45309', marginBottom: '6px' }}>
                        Остановлено на шаге:
                      </div>
                      <span style={{ fontSize: '13px', color: '#92400e' }}>
                        {progressLog[progressLog.length - 1]}
                      </span>
                    </div>
                  )}
                  <div style={{ marginTop: '16px' }}>
                    <button
                      data-testid="resume-now-button"
                      onClick={handleResume}
                      disabled={resuming}
                      style={{
                        padding: '8px 20px',
                        backgroundColor: resuming ? '#fcd34d' : '#d97706',
                        color: '#ffffff',
                        border: 'none',
                        borderRadius: '8px',
                        cursor: resuming ? 'not-allowed' : 'pointer',
                        fontSize: '13px',
                        fontWeight: 700,
                      }}
                    >
                      {resuming ? 'Запуск...' : '▶ Продолжить сейчас'}
                    </button>
                  </div>
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
                      {formatTaskError(task.error_message)}
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

                  {/* Resume section — показываем «Продолжить» для любой resumable-задачи с чекпоинтом */}
                  {isBatchPending(task) ? (
                    <div style={{ marginTop: '16px', borderTop: '1px solid #fecaca', paddingTop: '14px' }}>
                      <div style={{ fontSize: '14px', color: '#7f1d1d', marginBottom: '12px', fontWeight: 500 }}>
                        Пакетный расчёт уже выполнен и оплачен — результат хранится у Anthropic.
                        Продолжение заберёт готовый расчёт, позиции повторно считаться не будут.
                        Перезапуск с начала оплатит тот же расчёт второй раз.
                      </div>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        <button
                          data-testid="resume-batch-button"
                          onClick={handleResume}
                          disabled={resuming || restarting}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: resuming ? '#fca5a5' : '#dc2626',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: (resuming || restarting) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 700,
                          }}
                        >
                          {resuming ? 'Запуск...' : '▶ Продолжить — забрать готовый расчёт'}
                        </button>
                      </div>
                    </div>
                  ) : isResumable(task) && (task.progress_data?._stage === 'pre_excel' || task.progress_data?._stage === 'claude_partial') ? (
                    <div style={{ marginTop: '16px', borderTop: '1px solid #fecaca', paddingTop: '14px' }}>
                      <div style={{ fontSize: '14px', color: '#7f1d1d', marginBottom: '12px', fontWeight: 500 }}>
                        Часть данных от Claude сохранена. Продолжение не будет пересчитывать
                        уже обработанные позиции — токены повторно тратиться не будут.
                      </div>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        <button
                          data-testid="resume-button"
                          onClick={handleResume}
                          disabled={resuming || restarting}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: resuming ? '#fca5a5' : '#dc2626',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: (resuming || restarting) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 700,
                          }}
                        >
                          {resuming ? 'Запуск...' : '▶ Продолжить'}
                        </button>
                        <button
                          onClick={handleRestart}
                          disabled={restarting || resuming}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: restarting ? '#e2e8f0' : '#ffffff',
                            color: '#64748b',
                            border: '1.5px solid #cbd5e1',
                            borderRadius: '8px',
                            cursor: (restarting || resuming) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 600,
                          }}
                        >
                          {restarting ? 'Запуск...' : '↺ Перезапустить с начала'}
                        </button>
                      </div>
                    </div>
                  ) : isResumable(task) && task.progress_data?.chunks_done != null ? (
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
                          data-testid="resume-button"
                          onClick={handleResume}
                          disabled={resuming || restarting}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: resuming ? '#fca5a5' : '#dc2626',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: (resuming || restarting) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 700,
                          }}
                        >
                          {resuming ? 'Запуск...' : '▶ Продолжить'}
                        </button>
                        <button
                          onClick={handleRestart}
                          disabled={restarting || resuming}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: restarting ? '#e2e8f0' : '#ffffff',
                            color: '#64748b',
                            border: '1.5px solid #cbd5e1',
                            borderRadius: '8px',
                            cursor: (restarting || resuming) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 600,
                          }}
                        >
                          {restarting ? 'Запуск...' : '↺ Перезапустить с начала'}
                        </button>
                      </div>
                    </div>
                  ) : isResumable(task) && (task.progress_data?.ocr_pages_partial != null || task.progress_data?.ocr_pages != null) ? (
                    <div style={{ marginTop: '16px', borderTop: '1px solid #fecaca', paddingTop: '14px' }}>
                      <div style={{ fontSize: '14px', color: '#7f1d1d', marginBottom: '12px', fontWeight: 500 }}>
                        Распознано{ocrDonePages(task) != null ? ` ${ocrDonePages(task)} стр.` : ' часть страниц'}.
                        Продолжение распознает оставшиеся страницы, не пересчитывая уже готовые.
                      </div>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        <button
                          data-testid="resume-button"
                          onClick={handleResume}
                          disabled={resuming || restarting}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: resuming ? '#fca5a5' : '#dc2626',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: (resuming || restarting) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 700,
                          }}
                        >
                          {resuming ? 'Запуск...' : '▶ Продолжить'}
                        </button>
                        <button
                          onClick={handleRestart}
                          disabled={restarting || resuming}
                          style={{
                            padding: '8px 20px',
                            backgroundColor: restarting ? '#e2e8f0' : '#ffffff',
                            color: '#64748b',
                            border: '1.5px solid #cbd5e1',
                            borderRadius: '8px',
                            cursor: (restarting || resuming) ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 600,
                          }}
                        >
                          {restarting ? 'Запуск...' : '↺ Перезапустить с начала'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: '16px', borderTop: '1px solid #fecaca', paddingTop: '14px' }}>
                      <button
                        data-testid="restart-button"
                        onClick={handleRestart}
                        disabled={restarting}
                        style={{
                          padding: '8px 20px',
                          backgroundColor: restarting ? '#fca5a5' : '#dc2626',
                          color: '#ffffff',
                          border: 'none',
                          borderRadius: '8px',
                          cursor: restarting ? 'not-allowed' : 'pointer',
                          fontSize: '13px',
                          fontWeight: 700,
                        }}
                      >
                        {restarting ? 'Запуск...' : '↺ Перезапустить'}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <SectionLoader message="Загрузка информации о задаче..." />
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
                <Select value={selectedAttachProjectId || ''} onValueChange={setSelectedAttachProjectId} size="md">
                  <SelectTrigger style={{ flex: 1 }}>
                    <SelectValue placeholder="— Выберите проект —" />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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

        {/* Source files */}
        {task && task.input_files && task.input_files.length > 0 && (
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '12px',
              boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
              padding: '20px 24px',
              border: '1px solid #e2e8f0',
              marginBottom: '16px',
            }}
          >
            <h3 style={{ margin: '0 0 12px', fontSize: '15px', fontWeight: 700, color: '#0f172a' }}>
              Исходный файл
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {task.input_files.map((file, idx) => {
                const isXlsx = file.mime_type.includes('spreadsheet') || file.mime_type.includes('excel');
                const isPdf = file.mime_type === 'application/pdf';
                const isImage = file.mime_type.startsWith('image/');
                const icon = isXlsx ? '📊' : isPdf ? '📄' : isImage ? '🖼️' : '📁';
                const isLoading = downloadingInputFile === idx;
                return (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      backgroundColor: '#f8fafc',
                      border: '1px solid #e2e8f0',
                      borderRadius: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '18px' }}>{icon}</span>
                      <span style={{ fontSize: '14px', color: '#1e293b', fontWeight: 500 }}>
                        {file.name}
                      </span>
                    </div>
                    <button
                      onClick={() => handleDownloadInputFile(idx, file.name)}
                      disabled={isLoading}
                      style={{
                        padding: '7px 16px',
                        backgroundColor: isLoading ? '#cbd5e1' : '#2563eb',
                        color: '#ffffff',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: isLoading ? 'not-allowed' : 'pointer',
                        fontSize: '13px',
                        fontWeight: 600,
                      }}
                    >
                      {isLoading ? 'Скачивание...' : 'Скачать'}
                    </button>
                  </div>
                );
              })}
            </div>
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
                    <div>
                      <span style={{ fontSize: '14px', color: '#1e293b', fontWeight: 500 }}>
                        {result.file_name}
                      </span>
                      {result.slot === 'result' && (
                        <span style={{ display: 'block', fontSize: '11px', color: '#64748b' }}>оригинал</span>
                      )}
                      {result.slot === 'estimate' && (
                        <span style={{ display: 'block', fontSize: '11px', color: '#16a34a' }}>актуальная версия</span>
                      )}
                      {result.slot.startsWith('partial') && (
                        <span style={{ display: 'block', fontSize: '11px', color: '#64748b' }}>частичный результат</span>
                      )}
                    </div>
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

        {/* Editor card — shown after LIST_FROM_GRAND or LIST_FROM_PROJECT completes */}
        {task && task.status === 'completed' && (task.task_type === 'LIST_FROM_GRAND' || task.task_type === 'LIST_FROM_PROJECT') && (
          <div style={{
            backgroundColor: '#f0fdf4',
            border: '1px solid #86efac',
            borderRadius: '12px',
            padding: '24px 28px',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
          }}>
            <div>
              <div style={{ fontSize: '16px', fontWeight: 700, color: '#15803d', marginBottom: '4px' }}>
                Перечень готов — редактор доступен
              </div>
              <div style={{ fontSize: '14px', color: '#166534' }}>
                Откройте онлайн-редактор чтобы просматривать и редактировать перечень с историей изменений
              </div>
            </div>
            <button
              onClick={() => navigate(`/tasks/${taskId}/estimate`)}
              style={{
                flexShrink: 0,
                padding: '12px 28px',
                backgroundColor: '#16a34a',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '15px',
                fontWeight: 700,
              }}
            >
              Открыть редактор →
            </button>
          </div>
        )}

        {/* Смета и оптимизация — таблица живёт в редакторе, не на этой странице.
            Для задач внутри сметы сюда вообще не попадают: их открывает страница
            карточки. Это путь для задач вне сметы («Входящий», архив). */}
        {task && task.status === 'completed'
          && (task.task_type === 'ESTIMATE_OPTIMIZATION' || task.task_type === 'ESTIMATE_FROM_LIST') && (
          <div style={{
            backgroundColor: '#f0fdf4',
            border: '1px solid #86efac',
            borderRadius: '12px',
            padding: '24px 28px',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
          }}>
            <div>
              <div style={{ fontSize: '16px', fontWeight: 700, color: '#15803d', marginBottom: '4px' }}>
                Смета загружена — редактор готов
              </div>
              <div style={{ fontSize: '14px', color: '#166534' }}>
                Откройте онлайн-редактор чтобы работать со сметой
              </div>
            </div>
            <button
              onClick={() => navigate(`/tasks/${taskId}/estimate`)}
              style={{
                flexShrink: 0,
                padding: '12px 28px',
                backgroundColor: '#16a34a',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '15px',
                fontWeight: 700,
              }}
            >
              Открыть редактор →
            </button>
          </div>
        )}

      </div>
    </Layout>
  );
};

export default TaskStatusPage;
