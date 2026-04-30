import apiClient from './client'
import { WorkflowCard, StartTaskPayload } from '../types/workflow'

// ---------------------------------------------------------------------------
// Card Detail — pipeline file metadata
// ---------------------------------------------------------------------------

export interface InputFileDetail {
  index: number
  name: string
  size_bytes: number
  mime_type: string
}

export interface ResultFileDetail {
  result_id: number
  slot: string
  file_name: string
  size_bytes: number
  mime_type: string
  created_at: string
}

export interface StageDetail {
  task_id: string
  task_type: string
  task_status: string
  task_name: string | null
  task_created_at: string
  manually_edited_at: string | null
  input_files: InputFileDetail[]
  result_files: ResultFileDetail[]
}

export interface CardDetail {
  id: string
  project_id: string
  name: string
  stage: string
  source_stage: StageDetail | null
  completeness_stage: StageDetail | null
  estimate_stage: StageDetail | null
  optimization_stage: StageDetail | null
}

export async function getWorkflowCards(projectId: string): Promise<WorkflowCard[]> {
  const resp = await apiClient.get<WorkflowCard[]>(`/api/projects/${projectId}/workflow-cards`)
  return resp.data
}

export async function createWorkflowCard(projectId: string, name: string): Promise<WorkflowCard> {
  const resp = await apiClient.post<WorkflowCard>(`/api/projects/${projectId}/workflow-cards`, { name })
  return resp.data
}

export async function updateWorkflowCard(
  cardId: string,
  patch: Partial<Pick<WorkflowCard, 'name' | 'stage'>>
): Promise<WorkflowCard> {
  const resp = await apiClient.patch<WorkflowCard>(`/api/workflow-cards/${cardId}`, patch)
  return resp.data
}

export async function deleteWorkflowCard(cardId: string): Promise<void> {
  await apiClient.delete(`/api/workflow-cards/${cardId}`)
}

export async function getCardDetail(cardId: string): Promise<CardDetail> {
  const resp = await apiClient.get<CardDetail>(`/api/workflow-cards/${cardId}/detail`)
  return resp.data
}

export async function getCardFilesMeta(cardId: string): Promise<CardDetail> {
  const resp = await apiClient.get<CardDetail>(`/api/workflow-cards/${cardId}/files-meta`)
  return resp.data
}

export async function downloadSlotFileById(taskId: string, slot: string): Promise<void> {
  const token = localStorage.getItem('token') ?? ''
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'https://smeta-ai-backend.onrender.com'
  const url = `${baseUrl}/tasks/${taskId}/files/${slot}/download?token=${encodeURIComponent(token)}`
  const a = document.createElement('a')
  a.href = url
  a.target = '_blank'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export async function downloadInputFileById(taskId: string, fileIndex: number): Promise<void> {
  const token = localStorage.getItem('token') ?? ''
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'https://smeta-ai-backend.onrender.com'
  const url = `${baseUrl}/tasks/${taskId}/input-file/${fileIndex}?token=${encodeURIComponent(token)}`
  const a = document.createElement('a')
  a.href = url
  a.target = '_blank'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export async function startTask(cardId: string, payload: StartTaskPayload): Promise<WorkflowCard> {
  const fd = new FormData()
  fd.append('task_type', payload.task_type)
  if (payload.source_stage !== undefined) {
    fd.append('source_stage', String(payload.source_stage))
  }
  if (payload.use_previous_stage) {
    fd.append('use_previous_stage', 'true')
  }
  const allFiles = payload.files ?? (payload.file ? [payload.file] : [])
  for (const f of allFiles) {
    fd.append('files', f)
  }
  const resp = await apiClient.post<WorkflowCard>(`/api/workflow-cards/${cardId}/start-task`, fd)
  return resp.data
}
