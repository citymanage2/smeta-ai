import apiClient from './client';
import { useAuthStore } from '../stores/auth';

interface LoginResponse {
  access_token: string;
  role: 'user' | 'admin';
  username?: string | null;
}

export async function login(password: string, username?: string): Promise<LoginResponse> {
  // username пуст → legacy-вход по общему паролю роли; задан → индивидуальный аккаунт.
  const payload: { password: string; username?: string } = { password };
  if (username && username.trim()) payload.username = username.trim();
  const response = await apiClient.post<LoginResponse>('/auth/login', payload);
  const { access_token, role } = response.data;

  // Persist to localStorage
  localStorage.setItem('token', access_token);
  localStorage.setItem('role', role);

  // Update zustand store
  useAuthStore.getState().setAuth(access_token, role);

  return response.data;
}
