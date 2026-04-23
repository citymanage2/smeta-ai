import apiClient from './client';
import {
  EstimateVersionSummary,
  EstimateVersionFull,
  EstimateRow,
  OptimizationProposal,
  OptimizationStep,
} from '../types';

export interface Expenses {
  overhead_pct: number;
  transport_pct: number;
  contingency_pct: number;
}

export async function getVersions(taskId: string): Promise<EstimateVersionSummary[]> {
  const res = await apiClient.get<EstimateVersionSummary[]>(
    `/tasks/${taskId}/estimate/versions`,
  );
  return res.data;
}

export async function getVersion(
  taskId: string,
  versionId: string,
): Promise<EstimateVersionFull> {
  const res = await apiClient.get<EstimateVersionFull>(
    `/tasks/${taskId}/estimate/versions/${versionId}`,
  );
  return res.data;
}

export async function saveRows(
  taskId: string,
  versionId: string,
  rows: EstimateRow[],
): Promise<void> {
  await apiClient.put(`/tasks/${taskId}/estimate/versions/${versionId}/rows`, { rows });
}

export async function saveExpenses(
  taskId: string,
  versionId: string,
  expenses: Expenses,
): Promise<void> {
  await apiClient.put(
    `/tasks/${taskId}/estimate/versions/${versionId}/expenses`,
    expenses,
  );
}

export async function runOptimization(
  taskId: string,
  step: OptimizationStep,
): Promise<{ status: 'running' }> {
  const res = await apiClient.post<{ status: 'running' }>(
    `/tasks/${taskId}/estimate/optimize/${step}`,
  );
  return res.data;
}

export async function runCustomOptimization(
  taskId: string,
  versionId: string,
  rowIds: string[],
): Promise<{ proposals: OptimizationProposal[] }> {
  const res = await apiClient.post<{ proposals: OptimizationProposal[] }>(
    `/tasks/${taskId}/estimate/optimize/custom`,
    { version_id: versionId, row_ids: rowIds },
  );
  return res.data;
}

export async function applyProposals(
  taskId: string,
  versionId: string,
  acceptedIds: string[],
): Promise<EstimateVersionFull> {
  const res = await apiClient.post<EstimateVersionFull>(
    `/tasks/${taskId}/estimate/apply-proposals`,
    { version_id: versionId, accepted_proposal_ids: acceptedIds },
  );
  return res.data;
}

export async function rollbackVersion(
  taskId: string,
  versionId: string,
): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/estimate/versions/${versionId}/rollback`);
}

export async function renameVersion(
  taskId: string,
  versionId: string,
  displayName: string,
): Promise<void> {
  await apiClient.patch(`/tasks/${taskId}/estimate/versions/${versionId}`, {
    version_display_name: displayName,
  });
}

export async function exportVersion(
  taskId: string,
  versionId: string,
  displayName: string,
): Promise<void> {
  const response = await apiClient.get(
    `/tasks/${taskId}/estimate/versions/${versionId}/export`,
    { responseType: 'blob' },
  );
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `smeta_${displayName}.xlsx`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
