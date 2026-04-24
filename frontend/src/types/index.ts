export type TaskType = string;

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export type EstimationStatus = 'unestimated' | 'estimated' | 'optimized' | 'not_applicable' | 'optimizing';

export const ESTIMATE_TASK_TYPES: Set<TaskType> = new Set(['ESTIMATE_FROM_LIST', 'ESTIMATE_OPTIMIZATION']);

export type ClientFileType = 'Смета' | 'Проект' | 'ТЗ' | 'Другое';

export interface ClientFileMeta {
  index: number;
  type: ClientFileType;
}

export interface EstimateRow {
  id: string;
  lineage_id: string;
  num: number;
  type: 'work' | 'material' | 'section';
  name: string;
  unit: string;
  qty: number | null;
  price_work: number | null;
  price_material: number | null;
  cost: number | null;
  selected: boolean;
  abc_group?: 'A' | 'B' | 'C';
  optimization_note?: string;
  optimization_confidence?: 'high' | 'medium' | 'low';
}

export interface OptimizationProposal {
  id: string;
  row_id: string | null;
  proposal_type: 'add' | 'remove' | 'replace_tech' | 'replace_material' | 'price_search';
  description: string;
  explanation: string;
  economy_rub: number | null;
  confidence: 'high' | 'medium' | 'low';
  source?: string;
  new_value?: Partial<EstimateRow>;
}

export interface EstimateVersionSummary {
  id: string;
  task_id: string;
  version_number: number;
  version_label: string;
  version_display_name: string;
  overhead_pct: number;
  transport_pct: number;
  contingency_pct: number;
  expenses_overridden: boolean;
  is_rolled_back: boolean;
  created_at: string;
}

export interface EstimateVersionFull extends EstimateVersionSummary {
  rows: EstimateRow[];
  optimization_proposals: OptimizationProposal[] | null;
}

export type OptimizationStep = 'completeness' | 'redundancy' | 'technology' | 'materials';

export interface Task {
  id: string;
  task_type: TaskType;
  status: TaskStatus;
  user_prompt?: string;
  progress_message?: string;
  error_message?: string;
  estimation_status: EstimationStatus;
  cost?: number | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskResult {
  file_id: number;
  file_name: string;
  mime_type: string;
  slot: string;
}

export interface AdminTask extends Task {
  user_role: string;
  input_files: Array<{ name: string; mime_type: string; size_bytes: number }>;
  chat_history: Array<{ role: string; content: string; timestamp: string }>;
  results?: TaskResult[];
  deleted_at?: string | null;
  files_count?: number;
}

export interface AdminTasksParams {
  page?: number;
  page_size?: number;
  status?: TaskStatus;
  task_type?: TaskType;
  date_from?: string;
  date_to?: string;
}

export interface AdminTasksResponse {
  items: AdminTask[];
  total: number;
  page: number;
  page_size: number;
}

export const TASK_TYPE_LABELS: Record<string, string> = {
  LIST_FROM_GRAND: 'Перечень из Гранд-сметы',
  CHECK_LIST_COMPLETENESS: 'Проверка полноты перечня',
  LIST_FROM_PROJECT: 'Перечень из проекта',
  CHECK_PROJECT_COMPLETENESS: 'Проверка полноты (по проекту)',
  ESTIMATE_FROM_LIST: 'Смета из перечня',
  ESTIMATE_OPTIMIZATION: 'Оптимизация сметы',
};

export const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: 'Ожидание',
  processing: 'Обработка',
  completed: 'Завершено',
  failed: 'Ошибка',
  cancelled: 'Остановлено',
};

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCard extends Project {
  unestimated: number;
  estimated: number;
  optimized: number;
  other: number;
  total_cost: number | null;
  optimized_cost?: number | null;
}

export interface TaskBrief {
  id: string;
  task_type: string;
  status: string;
  estimation_status: EstimationStatus;
  cost: number | null;
  created_at: string;
  source_file_name?: string | null;
  slot_files?: Record<string, string>;
  name?: string | null;
}

export interface ProjectDetail extends ProjectCard {
  tasks: TaskBrief[];
}

export interface HistoryEntry {
  id: string;
  operation_type: 'optimization' | 'analog' | 'manual_edit' | 'revert';
  slot: string;
  description: string;
  created_at: string;
}

export interface RevertResponse {
  reverted?: boolean;
  warning?: boolean;
  dependent_entries?: Array<{
    id: string;
    description: string;
    created_at: string;
  }>;
}
