export type TaskType =
  | 'LIST_FROM_TZ'
  | 'LIST_FROM_TZ_PROJECT'
  | 'SMETA_FROM_GRAND_PROJECT'
  | 'SMETA_FROM_PROJECT'
  | 'SMETA_FROM_EDC_PROJECT'
  | 'SMETA_FROM_LIST'
  | 'SCAN_TO_EXCEL'
  | 'COMPARE_PROJECT_SMETA';

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface Task {
  id: string;
  task_type: TaskType;
  status: TaskStatus;
  user_prompt?: string;
  progress_message?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface TaskResult {
  file_id: number;
  file_name: string;
  mime_type: string;
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
  SMETA_FROM_GRAND_PROJECT: 'Смета: ГРАНД-смета + Проект',
  SMETA_FROM_PROJECT: 'Смета из Проекта',
  SMETA_FROM_EDC_PROJECT: 'Смета: ЭДЦ + Проект',
  SMETA_FROM_LIST: 'Смета из перечня',
  SCAN_TO_EXCEL: 'Скан сметы → Excel',
  COMPARE_PROJECT_SMETA: 'Сравнение проект/смета',
};

export const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: 'Ожидание',
  processing: 'Обработка',
  completed: 'Завершено',
  failed: 'Ошибка',
};
