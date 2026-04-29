import apiClient from './client';
import { Project, ProjectCard, ProjectDetail, TaskBrief } from '../types';

export interface ProjectCreatePayload {
  name: string;
  description?: string;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
}

export async function listProjects(): Promise<ProjectCard[]> {
  const resp = await apiClient.get<ProjectCard[]>('/projects');
  return resp.data;
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const resp = await apiClient.get<ProjectDetail>(`/projects/${projectId}`);
  return resp.data;
}

export async function getUnassignedTasks(): Promise<TaskBrief[]> {
  const resp = await apiClient.get<TaskBrief[]>('/projects/unassigned');
  return resp.data;
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
