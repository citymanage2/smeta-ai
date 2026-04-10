import apiClient from './client';
import { Task, TaskResult, HistoryEntry, RevertResponse } from '../types';

export interface TaskStatusResponse {
  id: string;
  status: Task['status'];
  task_type: Task['task_type'];
  progress_message?: string;
  error_message?: string;
  estimation_status: string;
  cost?: number | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  name?: string | null;
  progress_data?: Record<string, unknown>;
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

export async function cancelTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/cancel`);
}

export async function resumeTask(taskId: string): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>(`/tasks/${taskId}/resume`);
  return response.data;
}

export async function checkCompleteness(sourceTaskId: string): Promise<TaskCreateResponse> {
  const response = await apiClient.post<TaskCreateResponse>('/tasks/check-completeness', {
    source_task_id: sourceTaskId,
  });
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
