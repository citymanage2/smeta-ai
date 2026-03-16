import { create } from 'zustand';

interface AuthState {
  token: string | null;
  role: 'user' | 'admin' | null;
  setAuth: (token: string, role: 'user' | 'admin') => void;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
}

// Initialize from localStorage on store creation
const storedToken = localStorage.getItem('token');
const storedRole = localStorage.getItem('role') as 'user' | 'admin' | null;

export const useAuthStore = create<AuthState>((set) => ({
  token: storedToken,
  role: storedRole,
  isAuthenticated: !!storedToken,
  isAdmin: storedRole === 'admin',

  setAuth: (token: string, role: 'user' | 'admin') => {
    set({
      token,
      role,
      isAuthenticated: true,
      isAdmin: role === 'admin',
    });
  },

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    set({
      token: null,
      role: null,
      isAuthenticated: false,
      isAdmin: false,
    });
  },
}));
