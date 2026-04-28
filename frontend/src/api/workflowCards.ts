import apiClient from './client'
import { WorkflowCard, StartTaskPayload } from '../types/workflow'

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

export async function startTask(cardId: string, payload: StartTaskPayload): Promise<WorkflowCard> {
  const fd = new FormData()
  fd.append('task_type', payload.task_type)
  if (payload.source_stage !== undefined) {
    fd.append('source_stage', String(payload.source_stage))
  }
  if (payload.use_previous_stage) {
    fd.append('use_previous_stage', 'true')
  }
  if (payload.file) {
    fd.append('file', payload.file)
  }
  const resp = await apiClient.post<WorkflowCard>(`/api/workflow-cards/${cardId}/start-task`, fd)
  return resp.data
}
