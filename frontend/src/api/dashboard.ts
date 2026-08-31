import apiClient from './client';
import { TaskEta } from '../utils/eta';

export interface PulseStats {
  created_today: number;
  processing_now: number;
  /** Ждут очереди. Отдельно от «в обработке»: разные поводы вмешаться. */
  pending_now: number;
  completed_today: number;
  failed_today: number;
}

/** Карточка пульса — она же адрес списка задач под ней. */
export type PulseBucket = 'created' | 'processing' | 'pending' | 'completed' | 'failed';

export interface PulseTaskRow {
  id: string;
  task_type: string;
  status: string;
  name: string | null;
  project_id: string | null;
  project_name: string | null;
  created_at: string;
  /** Время фактической обработки. null — не стартовала или оборвалась. */
  work_seconds: number | null;
  work_running: boolean;
  /** Токены и доллары за все прогоны задачи, вместе с допами. */
  tokens: number;
  cost_usd: number;
}

export interface PulseBucketDetail {
  bucket: PulseBucket;
  count: number;
  total_tokens: number;
  total_cost_usd: number;
  total_work_seconds: number;
  tasks: PulseTaskRow[];
}

export interface ActiveTask {
  id: string;
  task_type: string;
  status: string;
  progress_message: string | null;
  created_at: string;
  project_id: string | null;
  project_name: string | null;
  /** Прогноз старта и готовности. null — прогноза нет. */
  eta: TaskEta | null;
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

export interface ApiCostByTaskType {
  task_type: string | null;
  cost_usd: number;
  calls_count: number;
}

export interface ApiCosts {
  today_usd: number;
  week_usd: number;
  month_usd: number;
  cache_hit_rate: number;
  by_task_type: ApiCostByTaskType[];
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
  api_costs: ApiCosts;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await apiClient.get<DashboardStats>('/dashboard/stats');
  return response.data;
}

/**
 * Задачи под одной карточкой пульса.
 *
 * Отдельным запросом по клику, а не полем в `/dashboard/stats`: дашборд
 * поллится раз в 10 секунд, а сюда заходят изредка.
 */
export async function getPulseBucket(bucket: PulseBucket): Promise<PulseBucketDetail> {
  const response = await apiClient.get<PulseBucketDetail>(`/dashboard/pulse/${bucket}`);
  return response.data;
}
