import React, { useState, useEffect, useCallback, useRef, Suspense } from 'react';
import { SpreadsheetTestEditor } from '../components/admin/SpreadsheetTestEditor';
import EstimateMigrationPanel from '../components/admin/EstimateMigrationPanel';
import { formatApiDetail } from '../utils/formatError';
import Layout from '../components/Layout';
import { AdminTask, TaskStatus, TaskType, TASK_TYPE_LABELS, STATUS_LABELS, AdminTasksParams } from '../types';
import {
  getAdminTasks, getAdminTask, deleteTask,
  getTrashTasks, restoreTask, permanentDeleteTask, clearTrash,
  getPriceListsInfo, uploadWorksPrice, uploadMaterialsPrice,
  downloadInputFile, generateEmbeddings,
  getApiHealth, getQueueHealth,
  PriceListInfo, ApiHealth, QueueHealth,
} from '../api/admin';
import { getTaskResults, downloadResult } from '../api/tasks';
import { useTaskSync } from '../stores/taskSync';
import { SectionLoader } from '../components/ui/LumaSpin';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/Select';

const STATUS_COLORS: Record<TaskStatus, { bg: string; text: string; border: string }> = {
  pending: { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  processing: { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  completed: { bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  failed: { bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
  cancelled: { bg: '#f8fafc', text: '#64748b', border: '#cbd5e1' },
  paused: { bg: '#fffbeb', text: '#b45309', border: '#fcd34d' },
};

const TASK_TYPES: TaskType[] = [
  'LIST_FROM_TZ', 'LIST_FROM_TZ_PROJECT', 'RESEARCH_PROJECT', 'LIST_FROM_PROJECT',
  'SMETA_FROM_GRAND_PROJECT', 'SMETA_FROM_PROJECT', 'SMETA_FROM_EDC_PROJECT',
  'SMETA_FROM_LIST', 'SCAN_TO_EXCEL', 'COMPARE_PROJECT_SMETA',
];

const STATUSES: TaskStatus[] = ['pending', 'processing', 'completed', 'failed', 'cancelled'];

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

// ---------------------------------------------------------------------------
// Диагностика: «почему задача висит». Два вопроса, на которые админ иначе может
// ответить только из логов сервера: отвечает ли AI-API (дошло ли пополнение)
// и разбирает ли worker очередь.
// ---------------------------------------------------------------------------

const HEALTH_TONE: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  good:  { bg: '#f0fdf4', border: '#86efac', text: '#15803d', icon: '✓' },
  warn:  { bg: '#fffbeb', border: '#fcd34d', text: '#b45309', icon: '⚠' },
  bad:   { bg: '#fef2f2', border: '#fca5a5', text: '#dc2626', icon: '✕' },
};

const API_VERDICT: Record<ApiHealth['verdict'], { label: string; tone: keyof typeof HEALTH_TONE }> = {
  ok:            { label: 'AI-API отвечает',                 tone: 'good' },
  no_balance:    { label: 'Баланс исчерпан',                 tone: 'bad'  },
  auth:          { label: 'Ключ отклонён',                   tone: 'bad'  },
  unavailable:   { label: 'AI-API недоступен',               tone: 'bad'  },
  misconfigured: { label: 'Ключ не задан в настройках',      tone: 'bad'  },
};

const QUEUE_VERDICT: Record<QueueHealth['verdict'], { label: string; tone: keyof typeof HEALTH_TONE }> = {
  idle:    { label: 'Очередь пуста',                tone: 'good' },
  ok:      { label: 'Очередь движется штатно',      tone: 'good' },
  busy:    { label: 'Очередь загружена, но живая',  tone: 'warn' },
  stalled: { label: 'Очередь не разбирается',       tone: 'bad'  },
};

function formatAge(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 60) return `${Math.round(seconds)} сек.`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин.`;
  return `${(seconds / 3600).toFixed(1)} ч.`;
}

// Экспортируется ради теста: панель — единственное место, где видно, что
// обработчик умирает, и её вывод должен проверяться отдельно от всей страницы.
export const HealthPanel: React.FC = () => {
  const [api, setApi] = useState<ApiHealth | null>(null);
  const [queue, setQueue] = useState<QueueHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function runCheck() {
    setLoading(true);
    setError('');
    try {
      // Обе проверки разом: причина зависания может быть в любой из двух,
      // и гонять их по очереди — лишний клик в момент, когда что-то сломалось.
      const [a, q] = await Promise.all([getApiHealth(), getQueueHealth()]);
      setApi(a);
      setQueue(q);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(formatApiDetail(detail, 'Не удалось выполнить проверку. Сервер не ответил.'));
    } finally {
      setLoading(false);
    }
  }

  const cardStyle = (tone: keyof typeof HEALTH_TONE): React.CSSProperties => ({
    backgroundColor: HEALTH_TONE[tone].bg,
    border: `1px solid ${HEALTH_TONE[tone].border}`,
    borderRadius: '10px',
    padding: '14px 16px',
    flex: '1 1 320px',
  });

  return (
    <div
      style={{
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        padding: '16px 20px',
        marginBottom: '20px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '15px', fontWeight: 700, color: '#0f172a' }}>Диагностика</div>
        <div style={{ fontSize: '13px', color: '#64748b', flex: 1 }}>
          Почему задача висит: отвечает ли ИИ и разбирается ли очередь
        </div>
        <button
          onClick={runCheck}
          disabled={loading}
          style={{
            padding: '8px 16px',
            fontSize: '14px',
            fontWeight: 600,
            backgroundColor: loading ? '#93c5fd' : '#2563eb',
            color: '#ffffff',
            border: 'none',
            borderRadius: '8px',
            cursor: loading ? 'default' : 'pointer',
          }}
        >
          {loading ? 'Проверяем...' : 'Проверить сейчас'}
        </button>
      </div>

      {error && (
        <div style={{ marginTop: '12px', fontSize: '14px', color: '#dc2626' }}>{error}</div>
      )}

      {(api || queue) && (
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '14px' }}>
          {api && (() => {
            const v = API_VERDICT[api.verdict];
            const tone = HEALTH_TONE[v.tone];
            return (
              <div style={cardStyle(v.tone)}>
                <div style={{ fontSize: '14px', fontWeight: 700, color: tone.text }}>
                  {tone.icon} {v.label}
                </div>
                <div style={{ fontSize: '13px', color: '#334155', marginTop: '6px', lineHeight: 1.5 }}>
                  {api.hint}
                </div>
                <div style={{ fontSize: '12px', color: '#64748b', marginTop: '8px' }}>
                  {api.via_proxy ? `Через посредника: ${api.base_url}` : 'Напрямую в Anthropic'}
                  {' · '}Модель: {api.model}
                  {' · '}Задач на паузе: {api.paused_tasks}
                </div>
              </div>
            );
          })()}

          {queue && (() => {
            const v = QUEUE_VERDICT[queue.verdict];
            const tone = HEALTH_TONE[v.tone];
            return (
              <div style={cardStyle(v.tone)}>
                <div style={{ fontSize: '14px', fontWeight: 700, color: tone.text }}>
                  {tone.icon} {v.label}
                </div>
                <div style={{ fontSize: '13px', color: '#334155', marginTop: '6px', lineHeight: 1.5 }}>
                  {queue.hint}
                </div>
                <div style={{ fontSize: '12px', color: '#64748b', marginTop: '8px' }}>
                  В очереди: {queue.counts.queued} (старейшая {formatAge(queue.queued.oldest_age_s)})
                  {' · '}В работе: {queue.counts.running} (дольше всех {formatAge(queue.running.oldest_claimed_age_s)})
                  {queue.running.stale_count > 0 && ` · Потерянных: ${queue.running.stale_count}`}
                </div>
                {/* Соединения к БД: в логе 29.07.2026 база отказывала в новом
                    соединении, а лимит тарифа никто не знал. Красным — когда
                    запас на исходе: это и есть будущий отказ. */}
                {queue.db_connections && (
                  <div
                    data-testid="db-connections"
                    style={{
                      fontSize: '12px',
                      marginTop: '4px',
                      color: queue.db_connections.reserve <= 5 ? '#dc2626' : '#64748b',
                    }}
                  >
                    Соединения к БД: {queue.db_connections.used} из{' '}
                    {queue.db_connections.max_allowed} (запас {queue.db_connections.reserve})
                  </div>
                )}
                {/* Память обработчика: он в другом контейнере, поэтому цифра
                    приходит записью в БД и только при превышении порога. */}
                {queue.worker_memory && (
                  <div
                    data-testid="worker-memory"
                    style={{ fontSize: '12px', color: '#b45309', marginTop: '4px' }}
                  >
                    Память обработчика: {queue.worker_memory.rss_mb} МБ — выше порога{' '}
                    {queue.worker_memory.threshold_mb} МБ при {queue.worker_memory.concurrency}{' '}
                    задачах разом ({formatAge(queue.worker_memory.age_s)} назад)
                  </div>
                )}
                {/* Перезапуски обработчика. Один старт на деплой — норма, поэтому
                    строка спокойная; несколько за час — он умирает от памяти, и
                    это ровно то, что видно как «все задачи повисли разом». */}
                {queue.worker_restarts && (
                  <div
                    data-testid="worker-restarts"
                    style={{
                      fontSize: '12px',
                      marginTop: '4px',
                      color: queue.worker_restarts.starts_1h >= 2 ? '#b45309' : '#64748b',
                      fontWeight: queue.worker_restarts.starts_1h >= 2 ? 600 : 400,
                    }}
                  >
                    Обработчик: старт {formatAge(queue.worker_restarts.last_age_s)} назад,{' '}
                    {queue.worker_restarts.starts_1h} за час
                    {queue.worker_restarts.slots !== null &&
                      `, слотов ${queue.worker_restarts.slots}`}
                    {queue.worker_restarts.limit_mb !== null &&
                      `, лимит памяти ${queue.worker_restarts.limit_mb} МБ`}
                    {queue.worker_restarts.rss_mb !== null &&
                      ` (на старте занято ${queue.worker_restarts.rss_mb} МБ)`}
                    {!!queue.worker_restarts.requeued &&
                      `, подобрано брошенных задач: ${queue.worker_restarts.requeued}`}
                  </div>
                )}
                {/* Ответы 429 «слишком часто». Тревожим только по свежим: вчерашние
                    429 — история, а не текущая проблема. Ноль за сутки — важный
                    ответ сам по себе: значит лишние ключи API ничего не дадут. */}
                {queue.api_rate_limits && (
                  <div
                    data-testid="api-rate-limits"
                    style={{
                      fontSize: '12px',
                      marginTop: '4px',
                      color: queue.api_rate_limits.hits_1h > 0 ? '#b45309' : '#64748b',
                      fontWeight: queue.api_rate_limits.hits_1h > 0 ? 600 : 400,
                    }}
                  >
                    Ограничения API (429): {queue.api_rate_limits.hits_1h} за час,{' '}
                    {queue.api_rate_limits.hits_24h} за сутки
                    {queue.api_rate_limits.max_wait_s_24h !== null &&
                      `, дольше всего ждали ${Math.round(queue.api_rate_limits.max_wait_s_24h)} с`}
                    {` (последний ${formatAge(queue.api_rate_limits.last_age_s)} назад, `}
                    {queue.api_rate_limits.via_proxy ? 'через посредника)' : 'напрямую)'}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
};

interface PriceUploadCardProps {
  title: string;
  info: PriceListInfo | null;
  selectedFile: File | null;
  uploading: boolean;
  message: { type: 'success' | 'error'; text: string } | null;
  embeddingLoading: boolean;
  onPickFile: () => void;
  onUpload: () => void;
  onGenerateEmbeddings: () => void;
}

const EMBEDDING_BADGE: Record<'pending' | 'ready' | 'failed', { label: string; color: string; bg: string; border: string }> = {
  pending:  { label: '⚠ Векторы не созданы',  color: '#854d0e', bg: '#fef9c3', border: '#fde047' },
  ready:    { label: '● Векторы готовы',       color: '#15803d', bg: '#f0fdf4', border: '#86efac' },
  failed:   { label: '✕ Ошибка генерации',     color: '#dc2626', bg: '#fef2f2', border: '#fca5a5' },
};

const EMBEDDING_BTN_LABEL: Record<'pending' | 'ready' | 'failed', string> = {
  pending: 'Сгенерировать векторы',
  ready:   'Перегенерировать векторы',
  failed:  'Повторить генерацию',
};

const PriceUploadCard: React.FC<PriceUploadCardProps> = ({
  title, info, selectedFile, uploading, message, embeddingLoading, onPickFile, onUpload, onGenerateEmbeddings,
}) => {
  const hasFile = !!info?.filename;
  const embStatus = info?.embedding_status ?? 'pending';
  const badge = EMBEDDING_BADGE[embStatus];

  return (
    <div
      style={{
        flex: '1 1 360px',
        minWidth: '320px',
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: '12px',
        padding: '28px',
        boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
      }}
    >
      <h3 style={{ margin: '0 0 16px', fontSize: '17px', fontWeight: 700, color: '#0f172a' }}>
        {title}
      </h3>

      {/* Current status */}
      <div
        style={{
          padding: '12px 14px',
          backgroundColor: hasFile ? '#f0fdf4' : '#f8fafc',
          border: `1px solid ${hasFile ? '#86efac' : '#e2e8f0'}`,
          borderRadius: '8px',
          marginBottom: '16px',
        }}
      >
        {hasFile ? (
          <>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#15803d', marginBottom: '2px' }}>
              {info!.filename}
            </div>
            <div style={{ fontSize: '12px', color: '#64748b' }}>
              Обновлён: {new Date(info!.updated_at!).toLocaleString('ru-RU', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              })}
            </div>
          </>
        ) : (
          <div style={{ fontSize: '13px', color: '#94a3b8' }}>Не загружен</div>
        )}
      </div>

      {/* Embedding status badge + button */}
      {hasFile && (
        <div style={{ marginBottom: '16px' }}>
          <div style={{
            display: 'inline-block',
            padding: '4px 10px',
            backgroundColor: badge.bg,
            border: `1px solid ${badge.border}`,
            borderRadius: '20px',
            fontSize: '12px',
            fontWeight: 600,
            color: badge.color,
            marginBottom: '10px',
          }}>
            {badge.label}
          </div>

          {/* Indeterminate progress bar — shown only during loading */}
          {embeddingLoading && (
            <div style={{
              width: '100%',
              height: '4px',
              backgroundColor: '#e2e8f0',
              borderRadius: '2px',
              overflow: 'hidden',
              marginBottom: '10px',
            }}>
              <div style={{
                height: '100%',
                width: '40%',
                backgroundColor: '#2563eb',
                borderRadius: '2px',
                animation: 'embProgressSlide 1.2s ease-in-out infinite',
              }} />
            </div>
          )}

          <button
            onClick={onGenerateEmbeddings}
            disabled={embeddingLoading}
            style={{
              width: '100%',
              padding: '9px',
              fontSize: '13px',
              fontWeight: 600,
              backgroundColor: embeddingLoading ? '#e2e8f0' : '#f1f5f9',
              color: embeddingLoading ? '#94a3b8' : '#374151',
              border: '1.5px solid #cbd5e1',
              borderRadius: '7px',
              cursor: embeddingLoading ? 'not-allowed' : 'pointer',
              transition: 'background-color 0.15s',
            }}
          >
            {embeddingLoading ? 'Генерация...' : EMBEDDING_BTN_LABEL[embStatus]}
          </button>
        </div>
      )}

      {/* File picker button */}
      <button
        onClick={onPickFile}
        style={{
          width: '100%',
          padding: '10px',
          fontSize: '14px',
          fontWeight: 500,
          backgroundColor: '#f1f5f9',
          color: '#374151',
          border: '1.5px dashed #cbd5e1',
          borderRadius: '8px',
          cursor: 'pointer',
          marginBottom: '10px',
          textAlign: 'left',
        }}
      >
        {selectedFile ? (
          <span>
            <span style={{ fontWeight: 600, color: '#1e293b' }}>{selectedFile.name}</span>
            <span style={{ color: '#94a3b8', fontSize: '12px' }}> — нажмите для замены</span>
          </span>
        ) : (
          <span style={{ color: '#64748b' }}>Нажмите для выбора файла (.xlsx, .csv, .txt…)</span>
        )}
      </button>

      {/* Message */}
      {message && (
        <div
          style={{
            padding: '9px 12px',
            backgroundColor: message.type === 'success' ? '#f0fdf4' : '#fef2f2',
            border: `1px solid ${message.type === 'success' ? '#86efac' : '#fca5a5'}`,
            borderRadius: '7px',
            marginBottom: '10px',
            fontSize: '13px',
            color: message.type === 'success' ? '#15803d' : '#dc2626',
          }}
        >
          {message.text}
        </div>
      )}

      {/* Upload button */}
      <button
        onClick={onUpload}
        disabled={!selectedFile || uploading}
        style={{
          width: '100%',
          padding: '11px',
          fontSize: '14px',
          fontWeight: 600,
          backgroundColor: !selectedFile || uploading ? '#93c5fd' : '#2563eb',
          color: '#ffffff',
          border: 'none',
          borderRadius: '8px',
          cursor: !selectedFile || uploading ? 'not-allowed' : 'pointer',
          transition: 'background-color 0.15s',
        }}
      >
        {uploading ? 'Загрузка...' : `Загрузить ${title.toLowerCase()}`}
      </button>
    </div>
  );
};


const AdminPage: React.FC = () => {
  const { version: taskSyncVersion, bump: bumpTaskSync } = useTaskSync();
  const [activeTab, setActiveTab] = useState<'tasks' | 'trash' | 'prices' | 'estimates' | 'spreadsheet'>('tasks');

  // Tasks state
  const [tasks, setTasks] = useState<AdminTask[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [taskError, setTaskError] = useState('');

  // Trash state
  const [trashTasks, setTrashTasks] = useState<AdminTask[]>([]);
  const [trashTotal, setTrashTotal] = useState(0);
  const [trashPage, setTrashPage] = useState(1);
  const [trashLoading, setTrashLoading] = useState(false);
  const [trashError, setTrashError] = useState('');
  const [permanentDeleteConfirm, setPermanentDeleteConfirm] = useState<string | null>(null);
  const [permanentDeleteLoading, setPermanentDeleteLoading] = useState(false);
  const [restoreLoading, setRestoreLoading] = useState<string | null>(null);

  // Per-task detail cache for expanded rows
  interface ExpandedDetail {
    loading: boolean;
    input_files: Array<{ name: string; mime_type: string; size_bytes: number }>;
    results: import('../types').TaskResult[];
    chat_history: Array<{ role: string; content: string; timestamp: string }>;
    chatExpanded: boolean;
  }
  const [expandedDetails, setExpandedDetails] = useState<Record<string, ExpandedDetail>>({});
  const [downloadingInput, setDownloadingInput] = useState<string | null>(null);

  // Filters
  const [filterStatus, setFilterStatus] = useState<TaskStatus | ''>('');
  const [filterType, setFilterType] = useState<TaskType | ''>('');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');

  // Prices state
  const worksInputRef = useRef<HTMLInputElement>(null);
  const matsInputRef = useRef<HTMLInputElement>(null);
  const [priceListsInfo, setPriceListsInfo] = useState<{ works: PriceListInfo; materials: PriceListInfo } | null>(null);
  const [priceInfoLoading, setPriceInfoLoading] = useState(false);
  const [worksFile, setWorksFile] = useState<File | null>(null);
  const [matsFile, setMatsFile] = useState<File | null>(null);
  const [worksUploading, setWorksUploading] = useState(false);
  const [matsUploading, setMatsUploading] = useState(false);
  const [worksMsg, setWorksMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [matsMsg, setMatsMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [worksEmbeddingLoading, setWorksEmbeddingLoading] = useState(false);
  const [cacheEmbeddingLoading, setCacheEmbeddingLoading] = useState(false);
  const [cacheEmbeddingMsg, setCacheEmbeddingMsg] = useState('');
  const [matsEmbeddingLoading, setMatsEmbeddingLoading] = useState(false);

  const [downloadingFile, setDownloadingFile] = useState<number | null>(null);

  const handleExpand = useCallback(async (taskId: string) => {
    if (expandedTask === taskId) {
      setExpandedTask(null);
      return;
    }
    setExpandedTask(taskId);
    if (expandedDetails[taskId]) return; // already loaded

    setExpandedDetails((prev) => ({ ...prev, [taskId]: { loading: true, input_files: [], results: [], chat_history: [], chatExpanded: false } }));
    try {
      const [detail, results] = await Promise.all([
        getAdminTask(taskId),
        getTaskResults(taskId).catch(() => []),
      ]);
      setExpandedDetails((prev) => ({
        ...prev,
        [taskId]: {
          loading: false,
          input_files: detail.input_files || [],
          results,
          chat_history: detail.chat_history || [],
          chatExpanded: false,
        },
      }));
    } catch {
      setExpandedDetails((prev) => ({ ...prev, [taskId]: { loading: false, input_files: [], results: [], chat_history: [], chatExpanded: false } }));
    }
  }, [expandedTask, expandedDetails]);

  const handleDownloadInput = async (taskId: string, fileIndex: number, fileName: string) => {
    const key = `${taskId}-${fileIndex}`;
    setDownloadingInput(key);
    try {
      await downloadInputFile(taskId, fileIndex, fileName);
    } catch {
      setTaskError('Ошибка при скачивании входного файла.');
    } finally {
      setDownloadingInput(null);
    }
  };

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
  }, [page, filterStatus, filterType, filterDateFrom, filterDateTo, taskSyncVersion]);

  const fetchPriceListsInfo = useCallback(async () => {
    setPriceInfoLoading(true);
    try {
      const info = await getPriceListsInfo();
      setPriceListsInfo(info);
    } catch {
      // non-critical — leave null
    } finally {
      setPriceInfoLoading(false);
    }
  }, []);

  const fetchTrash = useCallback(async () => {
    setTrashLoading(true);
    setTrashError('');
    try {
      const data = await getTrashTasks({ page: trashPage, page_size: PAGE_SIZE });
      setTrashTasks(data.items);
      setTrashTotal(data.total);
    } catch {
      setTrashError('Не удалось загрузить корзину.');
    } finally {
      setTrashLoading(false);
    }
  }, [trashPage, taskSyncVersion]);

  useEffect(() => {
    if (activeTab === 'tasks') fetchTasks();
    if (activeTab === 'trash') fetchTrash();
    if (activeTab === 'prices') fetchPriceListsInfo();
  }, [activeTab, fetchTasks, fetchTrash, fetchPriceListsInfo]);

  const handleDeleteTask = async (taskId: string) => {
    setDeleteLoading(true);
    try {
      await deleteTask(taskId);
      setDeleteConfirm(null);
      bumpTaskSync();
    } catch {
      setTaskError('Не удалось переместить задачу в корзину.');
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleRestoreTask = async (taskId: string) => {
    setRestoreLoading(taskId);
    try {
      await restoreTask(taskId);
      bumpTaskSync();
    } catch {
      setTrashError('Не удалось восстановить задачу.');
    } finally {
      setRestoreLoading(null);
    }
  };

  const handlePermanentDelete = async (taskId: string) => {
    setPermanentDeleteLoading(true);
    try {
      await permanentDeleteTask(taskId);
      setPermanentDeleteConfirm(null);
      bumpTaskSync();
    } catch {
      setTrashError('Не удалось удалить задачу.');
    } finally {
      setPermanentDeleteLoading(false);
    }
  };

  const [clearTrashLoading, setClearTrashLoading] = useState(false);

  const handleClearTrash = async () => {
    if (!window.confirm(`Удалить все ${trashTotal} задач из корзины навсегда? Это действие нельзя отменить.`)) return;
    setClearTrashLoading(true);
    setTrashError('');
    try {
      await clearTrash();
      setTrashTasks([]);
      setTrashTotal(0);
      bumpTaskSync();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setTrashError(`Не удалось очистить корзину: ${msg}`);
    } finally {
      setClearTrashLoading(false);
    }
  };

  const PRICE_ACCEPT = '.xlsx,.xls,.csv,.txt,.pdf,.docx';

  const handleWorksUpload = async () => {
    if (!worksFile) return;
    setWorksUploading(true);
    setWorksMsg(null);
    try {
      const result = await uploadWorksPrice(worksFile);
      setWorksMsg({ type: 'success', text: result.message });
      setWorksFile(null);
      fetchPriceListsInfo();
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setWorksMsg({ type: 'error', text: formatApiDetail(e.response?.data?.detail, 'Не удалось загрузить прайс-лист работ. Проверьте формат файла.') });
    } finally {
      setWorksUploading(false);
    }
  };

  const handleMatsUpload = async () => {
    if (!matsFile) return;
    setMatsUploading(true);
    setMatsMsg(null);
    try {
      const result = await uploadMaterialsPrice(matsFile);
      setMatsMsg({ type: 'success', text: result.message });
      setMatsFile(null);
      fetchPriceListsInfo();
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setMatsMsg({ type: 'error', text: formatApiDetail(e.response?.data?.detail, 'Не удалось загрузить прайс-лист материалов. Проверьте формат файла.') });
    } finally {
      setMatsUploading(false);
    }
  };

  const handleWorksGenerateEmbeddings = async () => {
    setWorksEmbeddingLoading(true);
    try {
      const result = await generateEmbeddings('works');
      setPriceListsInfo((prev) => prev ? {
        ...prev,
        works: { ...prev.works, embedding_status: result.status },
      } : prev);
    } catch {
      setPriceListsInfo((prev) => prev ? {
        ...prev,
        works: { ...prev.works, embedding_status: 'failed' },
      } : prev);
    } finally {
      setWorksEmbeddingLoading(false);
    }
  };

  const handleMatsGenerateEmbeddings = async () => {
    setMatsEmbeddingLoading(true);
    try {
      const result = await generateEmbeddings('materials');
      setPriceListsInfo((prev) => prev ? {
        ...prev,
        materials: { ...prev.materials, embedding_status: result.status },
      } : prev);
    } catch {
      setPriceListsInfo((prev) => prev ? {
        ...prev,
        materials: { ...prev.materials, embedding_status: 'failed' },
      } : prev);
    } finally {
      setMatsEmbeddingLoading(false);
    }
  };

  const handleCacheGenerateEmbeddings = async () => {
    setCacheEmbeddingLoading(true);
    setCacheEmbeddingMsg('');
    try {
      const result = await generateEmbeddings('cache');
      setCacheEmbeddingMsg(
        result.status === 'ready'
          ? `Готово: пересобрано ${result.updated ?? 0} записей кеша.`
          : `Не удалось: ${result.error ?? 'модель недоступна'}`,
      );
    } catch {
      setCacheEmbeddingMsg('Не удалось пересобрать векторы кеша.');
    } finally {
      setCacheEmbeddingLoading(false);
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
      <style>{`
        @keyframes embProgressSlide {
          0%   { transform: translateX(-150%); }
          100% { transform: translateX(350%); }
        }
      `}</style>
      <div>
        {/* Page title */}
        <div style={{ marginBottom: '24px' }}>
          <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
            Панель администратора
          </h2>
        </div>

        {/* Диагностика «почему задача висит» — доступна на любой вкладке */}
        <HealthPanel />

        {/* Tabs */}
        <div
          style={{
            display: 'flex',
            gap: '4px',
            borderBottom: '2px solid #e2e8f0',
            marginBottom: '28px',
          }}
        >
          {(['tasks', 'trash', 'prices', 'estimates', 'spreadsheet'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: '10px 20px',
                fontSize: '15px',
                fontWeight: 600,
                backgroundColor: 'transparent',
                color: activeTab === tab ? (tab === 'trash' ? '#dc2626' : '#2563eb') : '#64748b',
                border: 'none',
                borderBottom: activeTab === tab ? `2px solid ${tab === 'trash' ? '#dc2626' : '#2563eb'}` : '2px solid transparent',
                cursor: 'pointer',
                marginBottom: '-2px',
                transition: 'all 0.15s',
              }}
            >
              {tab === 'tasks'
                ? 'Задачи'
                : tab === 'trash'
                ? `Корзина${trashTotal > 0 ? ` (${trashTotal})` : ''}`
                : tab === 'prices'
                ? 'Прайс-листы'
                : tab === 'estimates'
                ? 'Перевод смет'
                : 'Онлайн редактор ТЕСТ'}
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
                <Select value={filterStatus || '__all__'} onValueChange={v => { setFilterStatus(v === '__all__' ? '' : v as TaskStatus); setPage(1); }} size="sm">
                  <SelectTrigger style={inputStyle}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">Все статусы</SelectItem>
                    {STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>{STATUS_LABELS[s]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '4px' }}>Тип задачи</div>
                <Select value={filterType || '__all__'} onValueChange={v => { setFilterType(v === '__all__' ? '' : v as TaskType); setPage(1); }} size="sm">
                  <SelectTrigger style={inputStyle}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">Все типы</SelectItem>
                    {TASK_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>{TASK_TYPE_LABELS[t]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
            <div style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px', overflowX: 'auto' }}>
              {loading ? (
                <SectionLoader />
              ) : tasks.length === 0 ? (
                <div style={{ padding: '48px', textAlign: 'center', color: '#94a3b8' }}>Задачи не найдены</div>
              ) : (
                <div>
                  <table style={{ width: '100%', minWidth: '700px', borderCollapse: 'collapse', fontSize: '14px' }}>
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
                        const s = STATUS_COLORS[task.status] ?? { bg: '#f8fafc', text: '#64748b', border: '#cbd5e1' };
                        return (
                          <React.Fragment key={task.id}>
                            <tr
                              style={{
                                borderBottom: '1px solid #e2e8f0',
                                backgroundColor: isExpanded ? '#f8fafc' : '#ffffff',
                                cursor: 'pointer',
                                transition: 'background-color 0.1s',
                              }}
                              onClick={() => handleExpand(task.id)}
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
                              <td style={{ padding: '12px 16px', whiteSpace: 'nowrap', width: '1%' }}>
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
                            {isExpanded && (() => {
                              const det = expandedDetails[task.id];
                              if (!det || det.loading) {
                                return (
                                  <tr style={{ backgroundColor: '#f8fafc' }}>
                                    <td colSpan={5} style={{ padding: '16px', textAlign: 'center' }}>
                                      <SectionLoader />
                                    </td>
                                  </tr>
                                );
                              }
                              return (
                                <tr style={{ backgroundColor: '#f8fafc' }}>
                                  <td colSpan={5} style={{ padding: '0 16px 20px' }}>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '12px' }}>
                                      {/* Input files */}
                                      <div>
                                        <div style={{ fontSize: '13px', fontWeight: 700, color: '#374151', marginBottom: '8px' }}>
                                          Входные файлы ({det.input_files.length})
                                        </div>
                                        {det.input_files.length > 0 ? (
                                          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                            {det.input_files.map((f, i) => {
                                              const dlKey = `${task.id}-${i}`;
                                              return (
                                                <li key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 10px', backgroundColor: '#ffffff', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                                                  <span style={{ fontSize: '13px', color: '#475569' }}>
                                                    {f.name} <span style={{ color: '#94a3b8' }}>({formatSize(f.size_bytes)})</span>
                                                  </span>
                                                  <button
                                                    onClick={() => handleDownloadInput(task.id, i, f.name)}
                                                    disabled={downloadingInput === dlKey}
                                                    style={{ padding: '3px 10px', backgroundColor: '#2563eb', color: '#fff', border: 'none', borderRadius: '5px', cursor: 'pointer', fontSize: '12px', fontWeight: 600, flexShrink: 0, marginLeft: '8px' }}
                                                  >
                                                    {downloadingInput === dlKey ? '...' : 'Скачать'}
                                                  </button>
                                                </li>
                                              );
                                            })}
                                          </ul>
                                        ) : (
                                          <p style={{ fontSize: '13px', color: '#94a3b8', margin: 0 }}>Нет файлов</p>
                                        )}
                                      </div>

                                      {/* Result files */}
                                      <div>
                                        <div style={{ fontSize: '13px', fontWeight: 700, color: '#374151', marginBottom: '8px' }}>
                                          Результаты ({det.results.length})
                                        </div>
                                        {det.results.length > 0 ? (
                                          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                            {det.results.map((r) => (
                                              <li key={r.file_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 10px', backgroundColor: '#f0fdf4', borderRadius: '6px', border: '1px solid #86efac' }}>
                                                <span style={{ fontSize: '13px', color: '#15803d' }}>{r.file_name}</span>
                                                <button
                                                  onClick={() => handleDownload(r.file_id, r.file_name)}
                                                  disabled={downloadingFile === r.file_id}
                                                  style={{ padding: '3px 10px', backgroundColor: '#16a34a', color: '#fff', border: 'none', borderRadius: '5px', cursor: 'pointer', fontSize: '12px', fontWeight: 600, flexShrink: 0, marginLeft: '8px' }}
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

                                    {/* Переписка с Claude */}
                                    <div style={{ marginTop: '16px' }}>
                                      <button
                                        onClick={() => setExpandedDetails((prev) => ({
                                          ...prev,
                                          [task.id]: { ...prev[task.id], chatExpanded: !prev[task.id].chatExpanded },
                                        }))}
                                        style={{
                                          display: 'flex', alignItems: 'center', gap: '6px',
                                          fontSize: '13px', fontWeight: 700, color: '#374151',
                                          background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginBottom: '8px',
                                        }}
                                      >
                                        <span>{det.chatExpanded ? '▾' : '▸'}</span>
                                        Переписка с Claude ({det.chat_history.length})
                                      </button>
                                      {det.chatExpanded && (
                                        det.chat_history.length > 0 ? (
                                          <div style={{ maxHeight: '300px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                            {det.chat_history.map((msg, i) => (
                                              <div
                                                key={i}
                                                style={{
                                                  padding: '8px 12px',
                                                  backgroundColor: msg.role === 'user' ? '#eff6ff' : '#ffffff',
                                                  border: `1px solid ${msg.role === 'user' ? '#bfdbfe' : '#e2e8f0'}`,
                                                  borderRadius: '8px',
                                                }}
                                              >
                                                <div style={{ fontSize: '12px', fontWeight: 700, color: msg.role === 'user' ? '#1d4ed8' : '#374151', marginBottom: '4px' }}>
                                                  {msg.role === 'user' ? 'Пользователь' : 'Ассистент'}
                                                </div>
                                                <p style={{ margin: 0, fontSize: '13px', color: '#1e293b', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>{msg.content}</p>
                                              </div>
                                            ))}
                                          </div>
                                        ) : (
                                          <p style={{ fontSize: '13px', color: '#94a3b8', margin: 0 }}>Нет данных</p>
                                        )
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })()}
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

        {/* ---- TRASH TAB ---- */}
        {activeTab === 'trash' && (
          <div>
            {trashTotal > 0 && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '12px' }}>
                <button
                  onClick={handleClearTrash}
                  disabled={clearTrashLoading}
                  style={{
                    padding: '8px 16px',
                    backgroundColor: clearTrashLoading ? '#fca5a5' : '#dc2626',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '8px',
                    cursor: clearTrashLoading ? 'not-allowed' : 'pointer',
                    fontSize: '13px',
                    fontWeight: 600,
                  }}
                >
                  {clearTrashLoading ? 'Очистка...' : `Очистить корзину (${trashTotal})`}
                </button>
              </div>
            )}
            {trashError && (
              <div style={{ padding: '12px 16px', backgroundColor: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '8px', color: '#dc2626', marginBottom: '16px', fontSize: '14px' }}>
                {trashError}
              </div>
            )}

            {trashLoading ? (
              <SectionLoader message="Загрузка корзины..." />
            ) : trashTasks.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8' }}>
                <div style={{ fontSize: '48px', marginBottom: '12px' }}>🗑</div>
                <p style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Корзина пуста</p>
                <p style={{ margin: '4px 0 0', fontSize: '14px' }}>Удалённые задачи появятся здесь</p>
              </div>
            ) : (
              <div style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                      <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>ID</th>
                      <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Тип</th>
                      <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Создана</th>
                      <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Удалена</th>
                      <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trashTasks.map((task) => (
                      <tr key={task.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontSize: '12px', color: '#475569', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {task.id}
                        </td>
                        <td style={{ padding: '12px 16px', color: '#1e293b', fontSize: '14px' }}>
                          {TASK_TYPE_LABELS[task.task_type] || task.task_type}
                        </td>
                        <td style={{ padding: '12px 16px', color: '#475569', fontSize: '13px', whiteSpace: 'nowrap' }}>
                          {formatDate(task.created_at)}
                        </td>
                        <td style={{ padding: '12px 16px', color: '#dc2626', fontSize: '13px', whiteSpace: 'nowrap' }}>
                          {task.deleted_at ? formatDate(task.deleted_at) : '—'}
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            <button
                              onClick={() => handleRestoreTask(task.id)}
                              disabled={restoreLoading === task.id}
                              style={{
                                padding: '5px 12px',
                                backgroundColor: '#f0fdf4',
                                color: '#15803d',
                                border: 'none',
                                borderRadius: '6px',
                                cursor: restoreLoading === task.id ? 'not-allowed' : 'pointer',
                                fontSize: '13px',
                                fontWeight: 600,
                              }}
                            >
                              {restoreLoading === task.id ? '...' : 'Восстановить'}
                            </button>
                            <button
                              onClick={() => setPermanentDeleteConfirm(task.id)}
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
                              Удалить навсегда
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Trash pagination */}
            {Math.ceil(trashTotal / PAGE_SIZE) > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', marginTop: '20px' }}>
                <button
                  onClick={() => setTrashPage((p) => Math.max(1, p - 1))}
                  disabled={trashPage === 1}
                  style={{ padding: '7px 14px', backgroundColor: trashPage === 1 ? '#f1f5f9' : '#ffffff', color: trashPage === 1 ? '#94a3b8' : '#374151', border: '1px solid #e2e8f0', borderRadius: '7px', cursor: trashPage === 1 ? 'not-allowed' : 'pointer', fontSize: '14px' }}
                >
                  ← Назад
                </button>
                <span style={{ fontSize: '14px', color: '#475569' }}>
                  Страница {trashPage} из {Math.ceil(trashTotal / PAGE_SIZE)} · Всего: {trashTotal}
                </span>
                <button
                  onClick={() => setTrashPage((p) => Math.min(Math.ceil(trashTotal / PAGE_SIZE), p + 1))}
                  disabled={trashPage === Math.ceil(trashTotal / PAGE_SIZE)}
                  style={{ padding: '7px 14px', backgroundColor: trashPage === Math.ceil(trashTotal / PAGE_SIZE) ? '#f1f5f9' : '#ffffff', color: trashPage === Math.ceil(trashTotal / PAGE_SIZE) ? '#94a3b8' : '#374151', border: '1px solid #e2e8f0', borderRadius: '7px', cursor: trashPage === Math.ceil(trashTotal / PAGE_SIZE) ? 'not-allowed' : 'pointer', fontSize: '14px' }}
                >
                  Вперёд →
                </button>
              </div>
            )}
          </div>
        )}

        {/* ---- PRICES TAB ---- */}
        {activeTab === 'prices' && (
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', maxWidth: '900px' }}>
            {priceInfoLoading && (
              <SectionLoader message="Загрузка информации о прайс-листах..." />
            )}

            {/* Hidden file inputs */}
            <input
              ref={worksInputRef}
              type="file"
              accept={PRICE_ACCEPT}
              style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) setWorksFile(f); e.target.value = ''; }}
            />
            <input
              ref={matsInputRef}
              type="file"
              accept={PRICE_ACCEPT}
              style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) setMatsFile(f); e.target.value = ''; }}
            />

            {/* Works card */}
            <PriceUploadCard
              title="Прайс работ"
              info={priceListsInfo?.works ?? null}
              selectedFile={worksFile}
              uploading={worksUploading}
              message={worksMsg}
              embeddingLoading={worksEmbeddingLoading}
              onPickFile={() => worksInputRef.current?.click()}
              onUpload={handleWorksUpload}
              onGenerateEmbeddings={handleWorksGenerateEmbeddings}
            />

            {/* Materials card */}
            <PriceUploadCard
              title="Прайс материалов"
              info={priceListsInfo?.materials ?? null}
              selectedFile={matsFile}
              uploading={matsUploading}
              message={matsMsg}
              embeddingLoading={matsEmbeddingLoading}
              onPickFile={() => matsInputRef.current?.click()}
              onUpload={handleMatsUpload}
              onGenerateEmbeddings={handleMatsGenerateEmbeddings}
            />

            {/* Кеш веб-поиска: при расчёте сметы он подставляет цену сразу
                после прайса, поэтому его векторы должны быть посчитаны по тем
                же правилам. Пересобирать его нужно после любой правки
                нормализации имён — иначе позиция будет искаться по старому
                написанию. */}
            <div style={{
              gridColumn: '1 / -1', border: '1px solid #e2e8f0', borderRadius: 10,
              padding: '14px 16px', background: '#fff',
            }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 6 }}>
                Кеш веб-поиска
              </div>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10, lineHeight: 1.5 }}>
                Цены, найденные ИИ в интернете. В расчёте идут сразу после прайса, поэтому
                векторы им нужны такие же. Пересоберите после изменения правил разбора
                наименований.
              </div>
              <button
                onClick={handleCacheGenerateEmbeddings}
                disabled={cacheEmbeddingLoading}
                style={{
                  padding: '7px 14px', borderRadius: 6, fontSize: 13, fontWeight: 500,
                  border: '1px solid #e2e8f0', background: '#fff', color: '#374151',
                  cursor: cacheEmbeddingLoading ? 'default' : 'pointer',
                  opacity: cacheEmbeddingLoading ? 0.7 : 1,
                }}
              >
                {cacheEmbeddingLoading ? 'Пересобираю...' : 'Пересобрать векторы кеша'}
              </button>
              {cacheEmbeddingMsg && (
                <span style={{ marginLeft: 10, fontSize: 12, color: '#64748b' }}>
                  {cacheEmbeddingMsg}
                </span>
              )}
            </div>
          </div>
        )}

        {/* ---- SPREADSHEET TAB ---- */}
        {/* ---- ПЕРЕВОД СМЕТ ---- */}
        {activeTab === 'estimates' && (
          <div style={{ padding: '8px 0' }}>
            <EstimateMigrationPanel />
          </div>
        )}

        {activeTab === 'spreadsheet' && (
          <Suspense fallback={<SectionLoader message="Загрузка редактора..." />}>
            <SpreadsheetTestEditor />
          </Suspense>
        )}
      </div>

      {/* Permanent delete confirmation modal */}
      {permanentDeleteConfirm && (
        <div
          style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
          onClick={() => setPermanentDeleteConfirm(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: '#ffffff', borderRadius: '12px', padding: '28px 32px', boxShadow: '0 8px 32px rgba(0,0,0,0.15)', maxWidth: '400px', width: '90%' }}
          >
            <h3 style={{ margin: '0 0 12px', fontSize: '18px', fontWeight: 700, color: '#dc2626' }}>
              Удалить навсегда?
            </h3>
            <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#64748b' }}>
              Это действие нельзя отменить. Задача и все связанные файлы будут уничтожены безвозвратно.
            </p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setPermanentDeleteConfirm(null)}
                style={{ padding: '9px 20px', backgroundColor: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 600 }}
              >
                Отмена
              </button>
              <button
                onClick={() => handlePermanentDelete(permanentDeleteConfirm)}
                disabled={permanentDeleteLoading}
                style={{ padding: '9px 20px', backgroundColor: permanentDeleteLoading ? '#fca5a5' : '#dc2626', color: '#ffffff', border: 'none', borderRadius: '8px', cursor: permanentDeleteLoading ? 'not-allowed' : 'pointer', fontSize: '14px', fontWeight: 600 }}
              >
                {permanentDeleteLoading ? 'Удаление...' : 'Удалить навсегда'}
              </button>
            </div>
          </div>
        </div>
      )}

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
              Переместить в корзину?
            </h3>
            <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#64748b' }}>
              Задача будет перемещена в корзину. Вы сможете восстановить её или удалить окончательно.
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
                {deleteLoading ? 'Перемещение...' : 'В корзину'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

export default AdminPage;
