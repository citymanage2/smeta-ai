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

export interface PriceListInfo {
  type: string;
  filename: string | null;
  updated_at: string | null;
}

export interface PriceListsInfoResponse {
  works: PriceListInfo;
  materials: PriceListInfo;
}

export interface SinglePriceUploadResponse {
  loaded: number;
  message: string;
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

// Legacy combined upload kept for backward compatibility
export async function uploadPrices(file: File): Promise<{ message: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiClient.post<{ message: string }>('/admin/prices/upload', formData);
  return response.data;
}
