import apiClient from './client';

// Роли, назначаемые сотрудникам через админку (без legacy 'user').
// supply_manager и contractor_manager — отдел производства работ (запрос КП).
export type AssignableRole =
  | 'admin'
  | 'head_of_sales'
  | 'project_manager'
  | 'supply_manager'
  | 'contractor_manager';

export interface AdminUser {
  id: number;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface AssignableUser {
  id: number;
  display_name: string;
  role: string;
}

export interface CreateUserPayload {
  username: string;
  password: string;
  role: AssignableRole;
  full_name?: string;
}

export interface UpdateUserPayload {
  full_name?: string;
  role?: string;
  is_active?: boolean;
}

export async function listUsers(): Promise<AdminUser[]> {
  const resp = await apiClient.get<AdminUser[]>('/admin/users');
  return resp.data;
}

export async function listAssignable(): Promise<AssignableUser[]> {
  const resp = await apiClient.get<AssignableUser[]>('/admin/users/assignable');
  return resp.data;
}

export async function createUser(payload: CreateUserPayload): Promise<{ user: AdminUser }> {
  const resp = await apiClient.post<{ user: AdminUser }>('/admin/users', payload);
  return resp.data;
}

export async function updateUser(id: number, payload: UpdateUserPayload): Promise<{ user: AdminUser }> {
  const resp = await apiClient.patch<{ user: AdminUser }>(`/admin/users/${id}`, payload);
  return resp.data;
}

export async function resetPassword(id: number, password: string): Promise<void> {
  await apiClient.post(`/admin/users/${id}/reset-password`, { password });
}

// Человекочитаемые названия ролей — одно место на весь фронт. Record по
// AssignableRole: забытая подпись новой роли — ошибка компиляции.
const ASSIGNABLE_ROLE_LABELS: Record<AssignableRole, string> = {
  admin: 'Администратор',
  head_of_sales: 'Руководитель отдела продаж',
  project_manager: 'Проектный менеджер',
  supply_manager: 'Менеджер снабжения',
  contractor_manager: 'Менеджер по работе с подрядчиками',
};

export const ROLE_LABELS: Record<string, string> = {
  ...ASSIGNABLE_ROLE_LABELS,
  user: 'Сотрудник',
};

// Роли, доступные для назначения в формах.
export const ASSIGNABLE_ROLES: AssignableRole[] = [
  'admin',
  'head_of_sales',
  'project_manager',
  'supply_manager',
  'contractor_manager',
];
