import apiClient from './client';
import { useAuthStore } from '../stores/auth';

interface LoginResponse {
  access_token: string;
  role: string;
  username?: string | null;
  expires_in?: number;
}

export async function login(password: string, username: string): Promise<LoginResponse> {
  // Вход строго по индивидуальному логину + паролю (общие пароли отключены).
  const payload = { password, username: username.trim() };
  const response = await apiClient.post<LoginResponse>('/auth/login', payload);
  const { access_token, role, username: respUsername } = response.data;

  // Персональный логин: с бэкенда, иначе — тот, что ввёл пользователь.
  const effectiveUsername = respUsername ?? (username.trim() ? username.trim() : null);

  // setAuth сам сохраняет token/role/username в localStorage и обновляет zustand-стор.
  useAuthStore.getState().setAuth(access_token, role, effectiveUsername);

  return response.data;
}
