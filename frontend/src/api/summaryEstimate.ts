import apiClient from './client';
import {
  SummaryEstimateResponse,
  SummaryEstimateCreate,
  SummaryEstimateUpdate,
} from '../types/summary';

export async function getSummary(projectId: string): Promise<SummaryEstimateResponse> {
  const res = await apiClient.get<SummaryEstimateResponse>(`/api/projects/${projectId}/summary`);
  return res.data;
}

export async function createSummary(
  projectId: string,
  data: SummaryEstimateCreate,
): Promise<SummaryEstimateResponse> {
  const res = await apiClient.post<SummaryEstimateResponse>(
    `/api/projects/${projectId}/summary`,
    data,
  );
  return res.data;
}

export async function updateSummary(
  projectId: string,
  data: SummaryEstimateUpdate,
): Promise<SummaryEstimateResponse> {
  const res = await apiClient.put<SummaryEstimateResponse>(
    `/api/projects/${projectId}/summary`,
    data,
  );
  return res.data;
}

export async function exportSummary(projectId: string, projectName?: string): Promise<void> {
  const response = await apiClient.get(`/api/projects/${projectId}/summary/export`, {
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `svodnaya_${projectName ?? projectId}.xlsx`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export async function setPrimaryVersion(
  cardId: string,
  versionId: string | null,
): Promise<void> {
  await apiClient.patch(`/api/workflow-cards/${cardId}/primary-version`, {
    version_id: versionId,
  });
}
