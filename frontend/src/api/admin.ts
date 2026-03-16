import apiClient from './client';
import { AdminTask, AdminTasksParams, AdminTasksResponse } from '../types';

export async function getAdminTasks(params?: AdminTasksParams): Promise<AdminTasksResponse> {
  const response = await apiClient.get<AdminTasksResponse>('/admin/tasks', { params });
  return response.data;
}

export async function deleteTask(taskId: string): Promise<void> {
  await apiClient.delete(`/admin/tasks/${taskId}`);
}

export async function getAdminTask(taskId: string): Promise<AdminTask> {
  const response = await apiClient.get<AdminTask>(`/admin/tasks/${taskId}`);
  return response.data;
}

export async function uploadPrices(file: File): Promise<{ message: string }> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<{ message: string }>('/admin/prices/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
}
