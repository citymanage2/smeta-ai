import apiClient from './client';

export interface Project {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  tasks_count: number;
}

export interface TaskSummary {
  id: string;
  task_type: string;
  status: string;
  estimate_status: 'uploaded' | 'calculated' | 'optimized';
  estimate_status_updated_by: 'manual' | 'auto';
  estimate_status_updated_at?: string;
  created_at: string;
  updated_at: string;
  input_files: { name: string; mime_type: string }[];
  project_id?: string;
}

export interface ProjectDetail extends Project {
  tasks: TaskSummary[];
}

export interface EstimateItem {
  id: string;
  position: number;
  type: 'Работа' | 'Материал';
  name: string;
  unit?: string;
  quantity?: number;
  work_price?: number;
  mat_price?: number;
  section?: string;
  notes?: string;
  is_analogue: boolean;
  original_item_id?: string;
  analogue_note?: string;
  extra: Record<string, unknown>;
}

export interface VersionInfo {
  id: string;
  task_id: string;
  version_number: number;
  change_description?: string;
  change_type?: string;
  created_at: string;
  created_by: string;
  items_count: number;
}

export interface Analogue {
  name: string;
  price: number;
  unit: string;
  supplier: string;
  saving_pct: number;
  note: string;
  source_url?: string;
}

export interface AnaloguesResult {
  item_id: string;
  original: { name: string; price: number; unit: string };
  analogues: Analogue[];
}

export interface OptimizePlanResult {
  plan: string;
  top_cost_items: { id: string; name: string; type: string; cost: number; pct: number }[];
  potential_savings_pct: number;
  items_count: number;
  total_cost: number;
}

// ── Projects CRUD ─────────────────────────────────────────────────────────────

export const createProject = (name: string, description?: string) =>
  apiClient.post<Project>('/projects', { name, description }).then(r => r.data);

export const listProjects = () =>
  apiClient.get<Project[]>('/projects').then(r => r.data);

export const getProject = (id: string) =>
  apiClient.get<ProjectDetail>(`/projects/${id}`).then(r => r.data);

export const updateProject = (id: string, name: string, description?: string) =>
  apiClient.put<Project>(`/projects/${id}`, { name, description }).then(r => r.data);

export const deleteProject = (id: string) =>
  apiClient.delete(`/projects/${id}`);

// ── Estimate membership ───────────────────────────────────────────────────────

export const addTaskToProject = (projectId: string, taskId: string) =>
  apiClient.post(`/projects/${projectId}/estimates/${taskId}`).then(r => r.data);

export const removeTaskFromProject = (projectId: string, taskId: string) =>
  apiClient.delete(`/projects/${projectId}/estimates/${taskId}`).then(r => r.data);

// ── Estimate status ───────────────────────────────────────────────────────────

export const updateEstimateStatus = (
  taskId: string,
  status: 'uploaded' | 'calculated' | 'optimized',
  updatedBy: 'manual' | 'auto' = 'manual',
) =>
  apiClient
    .patch(`/projects/estimates/${taskId}/status`, { status, updated_by: updatedBy })
    .then(r => r.data);

// ── Version history ───────────────────────────────────────────────────────────

export const listVersions = (taskId: string) =>
  apiClient.get<VersionInfo[]>(`/projects/estimates/${taskId}/versions`).then(r => r.data);

export const restoreVersion = (taskId: string, versionId: string) =>
  apiClient
    .post(`/projects/estimates/${taskId}/versions/${versionId}/restore`)
    .then(r => r.data);

// ── Estimate items ────────────────────────────────────────────────────────────

export const listEstimateItems = (taskId: string) =>
  apiClient.get<EstimateItem[]>(`/projects/estimates/${taskId}/items`).then(r => r.data);

// ── Optimization ──────────────────────────────────────────────────────────────

export interface OptimizeOptions {
  optimize_materials: boolean;
  optimize_works: boolean;
  optimize_other: boolean;
  custom_prompt?: string;
}

export const getOptimizationPlan = (taskId: string, options: OptimizeOptions) =>
  apiClient
    .post<OptimizePlanResult>(`/projects/estimates/${taskId}/optimize/plan`, options)
    .then(r => r.data);

export const executeOptimization = (taskId: string, options: OptimizeOptions) =>
  apiClient
    .post(`/projects/estimates/${taskId}/optimize/execute`, { ...options, confirmed: true })
    .then(r => r.data);

// ── Analogues ─────────────────────────────────────────────────────────────────

export const findAnalogues = (taskId: string, itemId: string) =>
  apiClient
    .post(`/projects/estimates/${taskId}/items/${itemId}/find-analogues`)
    .then(r => r.data);

export const applyAnalogue = (
  taskId: string,
  itemId: string,
  analogue: { analogue_name: string; analogue_price: number; analogue_note: string; supplier: string },
) =>
  apiClient
    .post(`/projects/estimates/${taskId}/items/${itemId}/apply-analogue`, analogue)
    .then(r => r.data);

export const revertAnalogue = (taskId: string, itemId: string) =>
  apiClient
    .post(`/projects/estimates/${taskId}/items/${itemId}/revert-analogue`)
    .then(r => r.data);
