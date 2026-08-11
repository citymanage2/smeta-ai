import apiClient from './client';
import { Task, TaskResult, HistoryEntry, RevertResponse } from '../types';
import { TaskEta } from '../utils/eta';

export interface InputFileMeta {
  name: string;
  mime_type: string;
  size_bytes: number;
}

export interface TaskStatusResponse {
  id: string;
  status: Task['status'];
  task_type: Task['task_type'];
  progress_message?: string;
  progress_log?: string[];
  error_message?: string;
  estimation_status: string;
  cost?: number | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  /** Начало текущего прогона (переставляется на каждый запуск/перезапуск). */
  started_at?: string | null;
  name?: string | null;
  progress_data?: Record<string, unknown>;
  input_files?: InputFileMeta[];
  /** Секунд назад обработчик подал признак жизни. null — живого обработчика нет. */
  worker_heartbeat_age_s?: number | null;
  /** Прогноз старта и готовности. null — задача уже не активна. */
  eta?: TaskEta | null;
}

export interface ChatMessage {
  role: string;
  content: string;
  timestamp: string;
}

export interface TaskChatResponse {
  chat_history: ChatMessage[];
}

export interface TaskCreateResponse {
  task_id: string;
  status: string;
}

export async function createTask(
  formData: FormData,
  onUploadProgress?: (percent: number) => void,
): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>('/tasks', formData, {
    onUploadProgress: (event) => {
      if (onUploadProgress && event.total) {
        onUploadProgress(Math.round((event.loaded * 100) / event.total));
      }
    },
  });
  return response.data;
}

export async function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  const response = await apiClient.get<TaskStatusResponse>(`/tasks/${taskId}/status`);
  return response.data;
}

export async function getTaskResults(taskId: string): Promise<TaskResult[]> {
  const response = await apiClient.get<TaskResult[]>(`/tasks/${taskId}/results`);
  return response.data;
}

export async function regenerateTaskResult(taskId: string): Promise<TaskResult> {
  const response = await apiClient.post<TaskResult>(`/tasks/${taskId}/results/regenerate`);
  return response.data;
}

export async function cancelTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/cancel`);
}

export async function resumeTask(taskId: string): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>(`/tasks/${taskId}/resume`);
  return response.data;
}

export async function restartTask(taskId: string): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>(`/tasks/${taskId}/restart`);
  return response.data;
}

export async function checkCompleteness(sourceTaskId: string): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>('/tasks/check-completeness', {
    source_task_id: sourceTaskId,
  });
  return response.data;
}

export async function checkProjectCompleteness(sourceTaskId: string): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>('/tasks/check-project-completeness', {
    source_task_id: sourceTaskId,
  });
  return response.data;
}

export interface RelatedCheck {
  task_id: string;
  task_type: string;
  status: string;
}

export async function getRelatedChecks(taskId: string): Promise<RelatedCheck[]> {
  const response = await apiClient.get<RelatedCheck[]>(`/tasks/${taskId}/related-checks`);
  return response.data;
}

export async function sendMessage(taskId: string, message: string): Promise<TaskChatResponse> {
  const response = await apiClient.post<TaskChatResponse>(`/tasks/${taskId}/message`, { message });
  return response.data;
}

export async function updateTask(taskId: string, data: { name: string }): Promise<{ task_id: string; name: string | null }> {
  const response = await apiClient.patch<{ task_id: string; name: string | null }>(`/tasks/${taskId}`, data);
  return response.data;
}

export async function renameSlotFile(taskId: string, slot: string, name: string): Promise<void> {
  await apiClient.patch(`/tasks/${taskId}/files/${slot}`, { name });
}

export async function deleteInputFile(taskId: string, fileIndex: number): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}/input-file/${fileIndex}`);
}

export async function addInputFile(taskId: string, file: File): Promise<{ name: string; mime_type: string; size_bytes: number; file_index: number }> {
  const fd = new FormData();
  fd.append('file', file);
  const response = await apiClient.post(`/tasks/${taskId}/input-files`, fd);
  return response.data;
}

export async function downloadInputFile(taskId: string, fileIndex: number, _fileName: string): Promise<void> {
  const token = localStorage.getItem('token') ?? '';
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'https://smeta-ai-backend.onrender.com';
  const url = `${baseUrl}/tasks/${taskId}/input-file/${fileIndex}?token=${encodeURIComponent(token)}`;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export async function downloadResult(fileId: number, fileName: string): Promise<void> {
  const response = await apiClient.get(`/results/${fileId}/download`, {
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

// ---------------------------------------------------------------------------
// Optimization
// ---------------------------------------------------------------------------

export interface OptimizeItem {
  row_index: number;
  name: string;
  type: string;
  quantity: number;
  unit: string;
  price_excl_vat: number;
  price_incl_vat: number;
  total: number;
  selected?: boolean;
}

export interface AnalyzeOptimizeResponse {
  items: OptimizeItem[];
  total_analyzed: number;
  total_selected: number;
  coverage_pct: number;
}

export async function analyzeOptimize(
  taskId: string,
  categories: string[],
  otherDescription?: string
): Promise<AnalyzeOptimizeResponse> {
  const res = await apiClient.post(`/tasks/${taskId}/optimize/analyze`, {
    categories,
    other_description: otherDescription ?? null,
  });
  return res.data;
}

export async function runOptimize(
  taskId: string,
  items: OptimizeItem[],
  prompt: string,
  categories: string[]
): Promise<{ task_id: string; status: string }> {
  const res = await apiClient.post(`/tasks/${taskId}/optimize/run`, {
    items,
    prompt,
    categories,
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export async function getTaskHistory(taskId: string): Promise<HistoryEntry[]> {
  const res = await apiClient.get<HistoryEntry[]>(`/tasks/${taskId}/history`);
  return res.data;
}

export async function revertHistory(
  taskId: string,
  entryId: string,
  confirm: boolean,
): Promise<RevertResponse> {
  const res = await apiClient.post<RevertResponse>(
    `/tasks/${taskId}/history/${entryId}/revert`,
    { confirm },
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// ESTIMATE_FROM_LIST — источники, редактирование позиций, переопределение цен
// ---------------------------------------------------------------------------

export interface EstimateSourceStage {
  stage: number;
  label: string;
  items_count: number;
  check_task_id?: string;
}

export interface EstimateSource {
  task_id: string;
  task_type: string;
  name: string | null;
  created_at: string;
  stages: EstimateSourceStage[];
}

export async function getEstimateSources(): Promise<EstimateSource[]> {
  const res = await apiClient.get<EstimateSource[]>('/tasks/estimate-sources');
  return res.data;
}

export interface EstimateItem {
  type: string;
  name: string;
  unit: string;
  quantity: number | null;
  work_price: number | null;
  material_price: number | null;
  price_list_name: string | null;
  sources: string | null;
  notes: string | null;
}

export interface PatchEstimateItemsResponse {
  task_id: string;
  grand_total: number;
  items_count: number;
}

export async function patchEstimateItems(
  taskId: string,
  items: EstimateItem[],
): Promise<PatchEstimateItemsResponse> {
  const res = await apiClient.patch<PatchEstimateItemsResponse>(
    `/tasks/${taskId}/estimate-items`,
    { items },
  );
  return res.data;
}

export interface RepriceItemResponse {
  item_index: number;
  work_price: number | null;
  material_price: number | null;
  sources: string;
  notes: string;
}

export interface FixEmptyPricesResponse {
  empty_count: number;
  status: 'started' | 'no_empty_items';
}

export async function fixEmptyPrices(taskId: string): Promise<FixEmptyPricesResponse> {
  const res = await apiClient.post<FixEmptyPricesResponse>(
    `/tasks/${taskId}/estimate-items/fix-empty-prices`,
  );
  return res.data;
}

export async function repriceEstimateItem(
  taskId: string,
  itemIndex: number,
): Promise<RepriceItemResponse> {
  const res = await apiClient.post<RepriceItemResponse>(
    `/tasks/${taskId}/estimate-items/${itemIndex}/reprice`,
  );
  return res.data;
}

export interface TrashTaskItem {
  id: string;
  task_type: string;
  status: string;
  name: string | null;
  created_at: string;
  deleted_at: string;
  owner_name?: string | null;
}

export interface TrashTasksResponse {
  items: TrashTaskItem[];
  total: number;
}

export async function softDeleteTask(taskId: string): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}`);
}

export async function getMyTrashTasks(params?: { page?: number; page_size?: number }): Promise<TrashTasksResponse> {
  const response = await apiClient.get<TrashTasksResponse>('/tasks/trash', { params });
  return response.data;
}

export async function restoreMyTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/restore`);
}

export async function permanentDeleteMyTask(taskId: string): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}/permanent`);
}

export async function clearMyTrash(): Promise<void> {
  await apiClient.delete('/tasks/trash');
}
