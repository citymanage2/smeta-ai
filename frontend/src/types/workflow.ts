export type KanbanStage = 'list' | 'completeness' | 'estimate' | 'optimization'

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'

export interface InputFileBrief {
  name: string
  mime_type: string
  size_bytes: number
}

export interface TaskBrief {
  id: string
  task_type: string
  status: TaskStatus
  name: string | null
  created_at: string
  input_files: InputFileBrief[]
  progress_message: string | null
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
