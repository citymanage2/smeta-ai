import apiClient from './client';
import { Task, TaskResult } from '../types';

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

export async function sendMessage(taskId: string, message: string): Promise<TaskChatResponse> {
  const response = await apiClient.post<TaskChatResponse>(`/tasks/${taskId}/message`, { message });
  return response.data;
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
