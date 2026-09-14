import apiClient from './client';

/** Правило для промпта, выученное из правок. Включает только менеджер. */
export interface PromptRule {
  id: number;
  text: string;
  /** ALL — все стадии конвейера; иначе тип задачи. */
  scope: string;
  enabled: boolean;
  created_by: string | null;
  enabled_by: string | null;
  enabled_at: string | null;
  created_at: string;
}

export async function getPromptRules(): Promise<PromptRule[]> {
  return (await apiClient.get<PromptRule[]>('/prompt-rules')).data;
}

export async function createPromptRule(text: string, scope: string): Promise<PromptRule> {
  return (await apiClient.post<PromptRule>('/prompt-rules', { text, scope })).data;
}

export async function setPromptRuleEnabled(id: number, enabled: boolean): Promise<PromptRule> {
  const action = enabled ? 'enable' : 'disable';
  return (await apiClient.post<PromptRule>(`/prompt-rules/${id}/${action}`)).data;
}

export async function deletePromptRule(id: number): Promise<void> {
  await apiClient.delete(`/prompt-rules/${id}`);
}
