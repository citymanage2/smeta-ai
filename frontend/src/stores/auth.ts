import { create } from 'zustand';
import { isProductionRole } from '../utils/roles';

// role приходит с бэкенда строкой: 'admin' | 'head_of_sales' | 'project_manager' |
// 'supply_manager' | 'contractor_manager' | 'user' (legacy).
// Тип оставлен строковым ради совместимости с новыми ролями.
type Role = string;

interface AuthState {
  token: string | null;
  role: Role | null;
  username: string | null;
  setAuth: (token: string, role: Role, username?: string | null) => void;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isManager: boolean;
  // Отдел производства работ: видит только запросы КП своей роли.
  isProduction: boolean;
}

// Initialize from localStorage on store creation
const storedToken = localStorage.getItem('token');
const storedRole = localStorage.getItem('role');
const storedUsername = localStorage.getItem('username');

// Менеджер = admin или руководитель отдела продаж (полный доступ к данным).
const computeIsManager = (role: Role | null): boolean =>
  role === 'admin' || role === 'head_of_sales';

export const useAuthStore = create<AuthState>((set) => ({
  token: storedToken,
  role: storedRole,
  username: storedUsername,
  isAuthenticated: !!storedToken,
  isAdmin: storedRole === 'admin',
  isManager: computeIsManager(storedRole),
  isProduction: isProductionRole(storedRole),

  setAuth: (token: string, role: Role, username?: string | null) => {
    localStorage.setItem('token', token);
    localStorage.setItem('role', role);
    if (username && username.trim()) {
      localStorage.setItem('username', username.trim());
    } else {
      localStorage.removeItem('username');
    }
    set({
      token,
      role,
      username: username && username.trim() ? username.trim() : null,
      isAuthenticated: true,
      isAdmin: role === 'admin',
      isManager: computeIsManager(role),
      isProduction: isProductionRole(role),
    });
  },

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    localStorage.removeItem('username');
    set({
      token: null,
      role: null,
      username: null,
      isAuthenticated: false,
      isAdmin: false,
      isManager: false,
      isProduction: false,
    });
  },
}));
