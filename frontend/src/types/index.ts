export type TaskType =
  | 'LIST_FROM_TZ'
  | 'LIST_FROM_TZ_PROJECT'
  | 'RESEARCH_PROJECT'
  | 'LIST_FROM_PROJECT'
  | 'SMETA_FROM_GRAND_PROJECT'
  | 'SMETA_FROM_PROJECT'
  | 'SMETA_FROM_EDC_PROJECT'
  | 'SMETA_FROM_LIST'
  | 'SCAN_TO_EXCEL'
  | 'COMPARE_PROJECT_SMETA'
  | 'OPTIMIZE_SMETA';

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export type EstimationStatus = 'unestimated' | 'estimated' | 'optimized' | 'not_applicable' | 'processing_optimization';

export const ESTIMATE_TASK_TYPES: Set<TaskType> = new Set([
  'SMETA_FROM_LIST',
  'SMETA_FROM_PROJECT',
  'SMETA_FROM_EDC_PROJECT',
  'SMETA_FROM_GRAND_PROJECT',
  'SCAN_TO_EXCEL',
]);

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

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  LIST_FROM_TZ: 'Перечень из ТЗ',
  LIST_FROM_TZ_PROJECT: 'Перечень из ТЗ + Проект',
  RESEARCH_PROJECT: 'Проверка проектной документации',
  LIST_FROM_PROJECT: 'Перечень из Проекта',
  SMETA_FROM_GRAND_PROJECT: 'Смета: ГРАНД-смета + Проект',
  SMETA_FROM_PROJECT: 'Смета из Проекта',
  SMETA_FROM_EDC_PROJECT: 'Смета: ЭДЦ + Проект',
  SMETA_FROM_LIST: 'Смета из перечня',
  SCAN_TO_EXCEL: 'Скан сметы → Excel',
  COMPARE_PROJECT_SMETA: 'Сравнение проект/смета',
  OPTIMIZE_SMETA: 'Оптимизация сметы',
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
