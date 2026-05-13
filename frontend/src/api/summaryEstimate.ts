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

export interface CustomExportPayload {
  selected_section_ids: string[];
  row_types: string[];
  visible_columns: string[];
  rows: {
    section_name?: string | null;
    num?: number | null;
    name?: string | null;
    unit?: string | null;
    qty?: number | null;
    price_work?: number | null;
    cost_work?: number | null;
    price_material?: number | null;
    cost_material?: number | null;
  }[];
}

export async function customExport(
  projectId: string,
  payload: CustomExportPayload,
  fileName = 'export.xlsx',
): Promise<void> {
  const response = await apiClient.post(
    `/api/projects/${projectId}/summary/custom-export`,
    payload,
    { responseType: 'blob' },
  );
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', fileName);
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
