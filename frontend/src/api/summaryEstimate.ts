import apiClient from './client';
import { ExportPayload } from '../components/editor/exportBuilder';
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

function downloadBlob(data: BlobPart, fileName: string): void {
  const url = window.URL.createObjectURL(new Blob([data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', fileName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export async function exportSummary(projectId: string, projectName?: string): Promise<void> {
  const response = await apiClient.get(`/api/projects/${projectId}/summary/export`, {
    responseType: 'blob',
  });
  downloadBlob(response.data, `svodnaya_${projectName ?? projectId}.xlsx`);
}

/** Выгрузка-ведомость по сводной. Формат общий для всех документов (Фаза 9). */
export async function customExport(
  projectId: string,
  payload: ExportPayload,
  fileName = 'export.xlsx',
): Promise<void> {
  const response = await apiClient.post(
    `/api/projects/${projectId}/summary/custom-export`,
    payload,
    { responseType: 'blob' },
  );
  downloadBlob(response.data, fileName);
}

export async function setPrimaryVersion(
  cardId: string,
  versionId: string | null,
): Promise<void> {
  await apiClient.patch(`/api/workflow-cards/${cardId}/primary-version`, {
    version_id: versionId,
  });
}
