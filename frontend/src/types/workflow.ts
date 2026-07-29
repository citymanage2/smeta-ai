import { TaskEta } from '../utils/eta'

export type KanbanStage = 'list' | 'completeness' | 'estimate' | 'optimization'

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'paused'

export interface InputFileBrief {
  name: string
  mime_type: string
  size_bytes: number
}

/**
 * Безопасная выжимка прогресса задачи (белый список полей progress_data,
 * приходит из бэкенда через build_progress_summary). Не содержит контента
 * позиций/OCR/цен — только счётчики для отображения «N из M».
 */
export interface ProgressSummary {
  chunks_done?: number
  total_chunks?: number
  chunks_total?: number
  partial_count?: number
  opt_step?: string
  status?: string
  items_count?: number
}

export interface TaskBrief {
  id: string
  task_type: string
  status: TaskStatus
  name: string | null
  created_at: string
  input_files: InputFileBrief[]
  progress_message: string | null
  progress_data?: ProgressSummary | null
  /** Прогноз старта и готовности активной задачи (см. utils/eta). */
  eta?: TaskEta | null
}

export interface WorkflowCard {
  id: string
  project_id: string
  name: string
  stage: KanbanStage
  list_task_id: string | null
  completeness_task_id: string | null
  estimate_task_id: string | null
  optimization_task_id: string | null
  list_task: TaskBrief | null
  completeness_task: TaskBrief | null
  estimate_task: TaskBrief | null
  optimization_task: TaskBrief | null
  primary_version_id: string | null
  created_at: string
  updated_at: string
}

export interface GuardResult {
  allowed: boolean
  blockType: 'hard' | 'soft' | null
  message: string
}

export interface StartTaskPayload {
  task_type: string
  file?: File
  files?: File[]
  source_stage?: 1 | 2
  use_previous_stage?: boolean
}
