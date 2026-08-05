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

/**
 * Во что обошлась стадия и сколько она шла.
 *
 * Токены — сумма всех четырёх видов за все прогоны задачи; время — только
 * последнего прогона (перезапуск переставляет отметки, а деньги остаются).
 * `extra_*` — доспросы ИИ по уже сформированному файлу стадии: поиск цены,
 * аналоги, шаги оптимизации.
 *
 * Растущие счётчики приходят с точностью до минуты — иначе список карточек
 * менял бы ETag на каждом опросе. См. `services/usage_metrics.py`.
 */
export interface TaskUsage {
  tokens: number
  cost_usd: number
  extra_tokens: number
  extra_cost_usd: number
  queue_seconds: number | null
  work_seconds: number | null
  queue_running: boolean
  work_running: boolean
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
  /** Сумма сформированной сметы в рублях. Не путать с cost_usd в usage. */
  cost?: number | null
  /** Затраты и тайминги стадии (см. utils/usageMetrics). */
  usage?: TaskUsage | null
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
