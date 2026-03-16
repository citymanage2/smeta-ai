import apiClient from './client';
import { useAuthStore } from '../stores/auth';

interface LoginResponse {
  access_token: string;
  role: 'user' | 'admin';
}

export async function login(password: string): Promise<LoginResponse> {
  const response = await apiClient.post<LoginResponse>('/auth/login', { password });
  const { access_token, role } = response.data;

  // Persist to localStorage
  localStorage.setItem('token', access_token);
  localStorage.setItem('role', role);

  // Update zustand store
  useAuthStore.getState().setAuth(access_token, role);

  return response.data;
}
