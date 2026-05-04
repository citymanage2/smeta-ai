import apiClient from './client';
import {
  EstimateVersionSummary,
  EstimateVersionFull,
  EstimateRow,
  GenericRow,
  OptimizationProposal,
  OptimizationStep,
} from '../types';

export interface Expenses {
  overhead_pct: number;
  transport_pct: number;
  contingency_pct: number;
}

export async function getVersions(taskId: string, fileSlot?: string): Promise<EstimateVersionSummary[]> {
  const res = await apiClient.get<EstimateVersionSummary[]>(
    `/tasks/${taskId}/estimate/versions`,
    fileSlot ? { params: { file_slot: fileSlot } } : undefined,
  );
  return res.data;
}

export async function initVersionFromResult(taskId: string): Promise<{ status: string; version_id?: string }> {
  const res = await apiClient.post<{ status: string; version_id?: string }>(
    `/tasks/${taskId}/estimate/init-from-result`,
  );
  return res.data;
}

export async function initVersionFromInput(taskId: string, fileIndex: number): Promise<{ status: string; version_id?: string }> {
  const res = await apiClient.post<{ status: string; version_id?: string }>(
    `/tasks/${taskId}/estimate/init-from-input`,
    null,
    { params: { file_index: fileIndex } },
  );
  return res.data;
}

export async function saveGenericRows(
  taskId: string,
  versionId: string,
  rows: GenericRow[],
): Promise<void> {
  await apiClient.put(`/tasks/${taskId}/estimate/versions/${versionId}/rows`, { rows });
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
  const urlStep = step.replace(/_/g, '-');
  const res = await apiClient.post<{ status: 'running' }>(
    `/tasks/${taskId}/estimate/optimize/${urlStep}`,
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
  displayName?: string,
): Promise<EstimateVersionFull> {
  const res = await apiClient.post<EstimateVersionFull>(
    `/tasks/${taskId}/estimate/apply-proposals`,
    {
      version_id: versionId,
      accepted_proposal_ids: acceptedIds,
      ...(displayName ? { version_display_name: displayName } : {}),
    },
  );
  return res.data;
}

export async function createManualVersion(
  taskId: string,
  sourceVersionId: string,
  displayName?: string,
): Promise<EstimateVersionFull> {
  const res = await apiClient.post<EstimateVersionFull>(
    `/tasks/${taskId}/estimate/versions`,
    { source_version_id: sourceVersionId, ...(displayName ? { version_display_name: displayName } : {}) },
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

export interface CustomerEstimateExport {
  works: number;
  materials: number;
  vat: number;
  grand_total: number;
}

export async function exportComparison(
  taskId: string,
  versionIds: string[],
  customerEstimate?: CustomerEstimateExport,
): Promise<void> {
  const response = await apiClient.post(
    `/tasks/${taskId}/estimate/comparison/export`,
    { version_ids: versionIds, customer_estimate: customerEstimate ?? null },
    { responseType: 'blob' },
  );
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', 'sravnenie_smety.xlsx');
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
