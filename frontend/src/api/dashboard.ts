import apiClient from './client';

export interface PulseStats {
  created_today: number;
  processing_now: number;
  completed_today: number;
  failed_today: number;
}

export interface ActiveTask {
  id: string;
  task_type: string;
  status: string;
  progress_message: string | null;
  created_at: string;
  project_id: string | null;
  project_name: string | null;
}

export interface FailedTask {
  id: string;
  task_type: string;
  error_message: string | null;
  created_at: string;
  error_pattern: string;
}

export interface FailedTaskGroup {
  pattern: string;
  task_type: string;
  count: number;
  last_failed_at: string;
  tasks: FailedTask[];
}

export interface QualityFunnel {
  completed_count: number;
  estimated_count: number;
  manually_edited_count: number;
  human_edit_rate: number;
}

export interface TaskTypeBreakdown {
  list_from_grand: number;
  list_from_project: number;
  check_completeness: number;
  estimate_from_list: number;
  optimization: number;
}

export interface DashboardProjectCard {
  id: string;
  name: string;
  created_at: string;
  total_cost: number | null;
  last_task_at: string | null;
  task_breakdown: TaskTypeBreakdown;
  has_active: boolean;
  has_errors: boolean;
}

export interface ChartDay {
  date: string;
  LIST_FROM_GRAND: number;
  LIST_FROM_PROJECT: number;
  CHECK_COMPLETENESS: number;
  ESTIMATE_FROM_LIST: number;
  ESTIMATE_OPTIMIZATION: number;
}

export interface PriceListInfo {
  type: string;
  updated_at: string | null;
  embedding_status: string | null;
  items_count: number;
}

export interface DashboardStats {
  pulse: PulseStats;
  active_queue: ActiveTask[];
  errors: FailedTaskGroup[];
  quality_funnel: QualityFunnel;
  projects: DashboardProjectCard[];
  orphan_tasks_count: number;
  task_chart: ChartDay[];
  price_lists: PriceListInfo[];
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await apiClient.get<DashboardStats>('/dashboard/stats');
  return response.data;
}
