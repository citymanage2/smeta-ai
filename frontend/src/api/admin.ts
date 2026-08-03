import apiClient from './client';
import { AdminTask, AdminTasksParams, AdminTasksResponse } from '../types';

export async function getAdminTasks(params?: AdminTasksParams): Promise<AdminTasksResponse> {
  const response = await apiClient.get<AdminTasksResponse>('/admin/tasks', { params });
  return response.data;
}

export async function deleteTask(taskId: string): Promise<void> {
  await apiClient.delete(`/admin/tasks/${taskId}`);
}

export async function getTrashTasks(params?: { page?: number; page_size?: number }): Promise<AdminTasksResponse> {
  const response = await apiClient.get<AdminTasksResponse>('/admin/tasks/trash', { params });
  return response.data;
}

export async function restoreTask(taskId: string): Promise<void> {
  await apiClient.post(`/admin/tasks/${taskId}/restore`);
}

export async function permanentDeleteTask(taskId: string): Promise<void> {
  await apiClient.delete(`/admin/tasks/${taskId}/permanent`);
}

export async function clearTrash(): Promise<void> {
  await apiClient.delete('/admin/tasks/trash');
}

export async function getAdminTask(taskId: string): Promise<AdminTask> {
  const response = await apiClient.get<AdminTask>(`/admin/tasks/${taskId}`);
  return response.data;
}

export interface PriceListInfo {
  type: string;
  filename: string | null;
  updated_at: string | null;
  embedding_status: 'pending' | 'ready' | 'failed';
}

export interface GenerateEmbeddingsResponse {
  status: 'ready' | 'failed';
  updated?: number;
  error?: string;
}

export interface PriceListsInfoResponse {
  works: PriceListInfo;
  materials: PriceListInfo;
}

export interface SinglePriceUploadResponse {
  loaded: number;
  message: string;
  added?: number;
  updated?: number;
}

export async function getPriceListsInfo(): Promise<PriceListsInfoResponse> {
  const response = await apiClient.get<PriceListsInfoResponse>('/admin/price-lists/info');
  return response.data;
}

export async function uploadWorksPrice(file: File): Promise<SinglePriceUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiClient.post<SinglePriceUploadResponse>(
    '/admin/price-lists/works',
    formData,
  );
  return response.data;
}

export async function uploadMaterialsPrice(file: File): Promise<SinglePriceUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiClient.post<SinglePriceUploadResponse>(
    '/admin/price-lists/materials',
    formData,
  );
  return response.data;
}

export async function downloadInputFile(taskId: string, fileIndex: number, fileName: string): Promise<void> {
  const response = await apiClient.get(`/admin/tasks/${taskId}/download-input/${fileIndex}`, {
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', fileName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export async function generateEmbeddings(type: 'works' | 'materials'): Promise<GenerateEmbeddingsResponse> {
  const response = await apiClient.post<GenerateEmbeddingsResponse>(
    `/admin/price-lists/${type}/generate-embeddings`,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Диагностика: доступность AI-API и состояние очереди.
// Эндпоинты существовали на бэкенде, но кнопок в UI не было — админ не мог
// проверить «дошло ли пополнение» и «разбирает ли worker очередь» без терминала.
// ---------------------------------------------------------------------------

export interface ApiHealth {
  checked_at: string;
  ok: boolean;
  status_code: number | null;
  error: string | null;
  error_code: string | null;
  is_balance_error: boolean;
  base_url: string;
  via_proxy: boolean;
  api_key_set: boolean;
  proxy_secret_set: boolean;
  model: string;
  paused_tasks: number;
  verdict: 'ok' | 'no_balance' | 'auth' | 'unavailable' | 'misconfigured';
  hint: string;
}

export interface QueueHealth {
  checked_at: string;
  counts: { queued: number; running: number; done: number; failed: number };
  queued: { count: number; oldest_age_s: number | null };
  running: { count: number; oldest_claimed_age_s: number | null; stale_count: number };
  visibility_timeout_s: number;
  verdict: 'idle' | 'ok' | 'busy' | 'stalled';
  hint: string;
  // Занятые/разрешённые соединения к БД. null — не PostgreSQL или нет прав на
  // pg_stat_activity (диагностика деградирует, но не падает).
  db_connections: { used: number; max_allowed: number; reserve: number } | null;
  // Последняя жалоба обработчика на память. null — жалоб не было.
  worker_memory: {
    rss_mb: number;
    threshold_mb: number;
    concurrency: number;
    age_s: number | null;
  } | null;
  // Перезапуски обработчика. Один старт на деплой — норма; несколько за час = он
  // умирает (почти всегда от памяти) и поднимается заново. При OOM-kill жалоба на
  // память не пишется, поэтому это единственная улика. null — событий ещё нет.
  worker_restarts: {
    starts_1h: number;
    last_age_s: number | null;
    slots: number | null;
    limit_mb: number | null;
    rss_mb: number | null;
    requeued: number | null;
  } | null;
}

export async function getApiHealth(): Promise<ApiHealth> {
  const response = await apiClient.get<ApiHealth>('/admin/api-health');
  return response.data;
}

export async function getQueueHealth(): Promise<QueueHealth> {
  const response = await apiClient.get<QueueHealth>('/admin/queue-health');
  return response.data;
}

// Legacy combined upload kept for backward compatibility
export async function uploadPrices(file: File): Promise<{ message: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiClient.post<{ message: string }>('/admin/prices/upload', formData);
  return response.data;
}

// ---------------------------------------------------------------------------
// Перевод смет на единый источник правды (разовая операция, план 2026-08-03)
// ---------------------------------------------------------------------------

export interface MigrationEntry {
  task_id: string;
  task_name: string;
  /** needs_version | in_sync | conflict | excluded | empty | resolved */
  status: string;
  items_count: number;
  version_count: number;
  /** Сколько позиций расходится между расчётом и редактором. */
  diff_count: number;
  items_total: number;
  version_total: number;
}

export interface MigrationReport {
  applied: boolean;
  counts: Record<string, number>;
  labels: Record<string, string>;
  entries: MigrationEntry[];
}

export interface MigrationResolveResult {
  task_id: string;
  task_name: string;
  status: string;
  items_total: number;
  version_total: number;
}

/** Отчёт «что будет сделано». Ничего не меняет. */
export async function getEstimateMigrationReport(): Promise<MigrationReport> {
  const response = await apiClient.get<MigrationReport>('/admin/estimates/migration');
  return response.data;
}

/** Создать недостающие рабочие версии. Сметы с расхождением не трогаются. */
export async function applyEstimateMigration(exclude: string[]): Promise<MigrationReport> {
  const response = await apiClient.post<MigrationReport>(
    '/admin/estimates/migration/apply', { exclude },
  );
  return response.data;
}

/** Разобрать расхождение по одной смете. */
export async function resolveEstimateConflict(
  taskId: string,
  prefer: 'items' | 'version',
): Promise<MigrationResolveResult> {
  const response = await apiClient.post<MigrationResolveResult>(
    '/admin/estimates/migration/resolve', { task_id: taskId, prefer },
  );
  return response.data;
}
