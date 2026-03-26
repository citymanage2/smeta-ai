import apiClient from './client';
import { Project, ProjectCard, ProjectDetail } from '../types';

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
