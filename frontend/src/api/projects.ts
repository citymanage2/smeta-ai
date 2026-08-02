import apiClient from './client';
import { Project, ProjectCard, ProjectDetail, TaskBrief } from '../types';

export interface ProjectCreatePayload {
  name: string;
  description?: string;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
  /** Проценты доп. расходов проекта: подставляются во все его документы. */
  overhead_pct?: number;
  transport_pct?: number;
}

export async function listProjects(archived?: boolean): Promise<ProjectCard[]> {
  const params = archived === undefined ? undefined : { archived };
  const resp = await apiClient.get<ProjectCard[]>('/projects', { params });
  return resp.data;
}

export async function archiveProject(projectId: string, archived: boolean): Promise<Project> {
  const resp = await apiClient.patch<Project>(`/projects/${projectId}/archive`, { archived });
  return resp.data;
}

export async function reassignProjectOwner(projectId: string, ownerId: number): Promise<Project> {
  const resp = await apiClient.patch<Project>(`/projects/${projectId}/owner`, { owner_id: ownerId });
  return resp.data;
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const resp = await apiClient.get<ProjectDetail>(`/projects/${projectId}`);
  return resp.data;
}

export async function getUnassignedTasks(archived = false): Promise<TaskBrief[]> {
  const params = archived ? { archived: true } : undefined;
  const resp = await apiClient.get<TaskBrief[]>('/projects/unassigned', { params });
  return resp.data;
}

export async function archiveTask(taskId: string, archived: boolean): Promise<void> {
  await apiClient.patch(`/tasks/${taskId}/archive`, { archived });
}

export async function createProject(payload: ProjectCreatePayload): Promise<Project> {
  const resp = await apiClient.post<Project>('/projects', payload);
  return resp.data;
}

export async function updateProject(projectId: string, payload: ProjectUpdatePayload): Promise<Project> {
  const resp = await apiClient.patch<Project>(`/projects/${projectId}`, payload);
  return resp.data;
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}`);
}

export interface TrashProjectItem {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  deleted_at: string;
}

export interface TrashProjectsResponse {
  items: TrashProjectItem[];
  total: number;
}

export async function getTrashProjects(): Promise<TrashProjectsResponse> {
  const resp = await apiClient.get<TrashProjectsResponse>('/projects/trash');
  return resp.data;
}

export async function restoreProject(projectId: string): Promise<void> {
  await apiClient.post(`/projects/${projectId}/restore`);
}

export async function permanentDeleteProject(projectId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/permanent`);
}

export async function clearProjectTrash(): Promise<void> {
  await apiClient.delete('/projects/trash');
}

export async function uploadFileToSlot(
  taskId: string,
  slot: 'source' | 'estimate' | 'optimized',
  file: File,
): Promise<{ slot: string; estimation_status?: string; cost?: number | null; warning?: string }> {
  const form = new FormData();
  form.append('slot', slot);
  form.append('file', file);
  const resp = await apiClient.post(`/tasks/${taskId}/files`, form);
  return resp.data;
}

export async function deleteFileFromSlot(
  taskId: string,
  slot: 'source' | 'estimate' | 'optimized',
): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}/files/${slot}`);
}

export async function confirmOptimized(taskId: string): Promise<{ estimation_status: string }> {
  const resp = await apiClient.patch<{ estimation_status: string }>(
    `/tasks/${taskId}/estimation`,
    { estimation_status: 'optimized' },
  );
  return resp.data;
}

export async function linkTaskToProject(
  taskId: string,
  projectId: string | null,
): Promise<{ project_id: string | null }> {
  const resp = await apiClient.patch<{ project_id: string | null }>(
    `/tasks/${taskId}/project`,
    { project_id: projectId },
  );
  return resp.data;
}

export async function downloadSlotFile(taskId: string, slot: string): Promise<void> {
  const response = await apiClient.get(`/tasks/${taskId}/files/${slot}/download`, {
    responseType: 'blob',
  });
  const contentDisposition: string = response.headers['content-disposition'] ?? '';
  const rfcMatch = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/i);
  const asciiMatch = contentDisposition.match(/filename="?([^";\n]+)"?/i);
  const rawName = rfcMatch
    ? decodeURIComponent(rfcMatch[1])
    : asciiMatch
    ? asciiMatch[1]
    : `${slot}.xlsx`;
  const url = URL.createObjectURL(response.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = rawName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function exportProject(projectId: string, format: 'xlsx' | 'pdf'): Promise<void> {
  const response = await apiClient.get(`/projects/${projectId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  const contentDisposition: string = response.headers['content-disposition'] ?? '';
  const match = contentDisposition.match(/filename="?([^"]+)"?/);
  const ext = format === 'xlsx' ? 'xlsx' : 'pdf';
  const fileName = match ? match[1] : `project.${ext}`;
  const url = URL.createObjectURL(response.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
